"""Offline SAM inference probe: one aligned face, selected target ages.

This runs the official ``sam_ffhq_aging.pt`` checkpoint in an isolated research
environment. It produces 1024x1024 2-D images only; it does not register them to
the project's UV atlas, does not build a mesh, does not calibrate years and does
not change service capabilities.

The input must already be an FFHQ-style aligned crop (as in SAM's notebooks).
The project's 3DDFA crop is a different alignment and is not fed here.

Usage:
    python tools/sam_probe.py \
        --sam-root data/third_party/SAM \
        --checkpoint data/models/sam/sam_ffhq_aging.pt \
        --image data/third_party/SAM/notebooks/images/866.jpg \
        --target-ages 20,45,70 \
        --output-dir output/research/sam-probe-20261020
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ages(value: str) -> list[int]:
    try:
        ages = [int(item) for item in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("Target ages must be comma-separated integers.") from error
    if not 1 <= len(ages) <= 10 or any(not 0 <= age <= 100 for age in ages):
        raise argparse.ArgumentTypeError("Use 1 to 10 ages between 0 and 100.")
    if len(set(ages)) != len(ages):
        raise argparse.ArgumentTypeError("Target ages must be unique.")
    return ages


def _opts_dict(value) -> dict:
    if isinstance(value, Namespace):
        return vars(value)
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("Checkpoint opts must be a dict or Namespace.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sam-root", type=Path, default=Path("data/third_party/SAM"))
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--target-ages", type=_ages, default=[45])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()

    root = args.sam_root.resolve()
    checkpoint_path = args.checkpoint.resolve()
    image_path = args.image.resolve()
    if not (root / "models" / "psp.py").is_file():
        raise SystemExit(f"not a SAM checkout: {root}")
    if not checkpoint_path.is_file():
        raise SystemExit(f"missing checkpoint: {checkpoint_path}")
    if not image_path.is_file():
        raise SystemExit(f"missing image: {image_path}")
    if args.output_dir.exists():
        raise SystemExit(f"output directory already exists: {args.output_dir}")

    sys.path.insert(0, str(root))
    import numpy as np
    import torch
    from models.psp import pSp
    from PIL import Image

    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but torch.cuda.is_available() is false.")

    started_at = datetime.now(UTC).isoformat()
    torch.set_grad_enabled(False)

    load_started = perf_counter()
    try:
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    except TypeError:
        checkpoint = torch.load(checkpoint_path, map_location="cpu")
    load_seconds = perf_counter() - load_started

    options = _opts_dict(checkpoint["opts"])
    defaults = {
        "start_from_latent_avg": True,
        "start_from_encoded_w_plus": False,
        "input_nc": 4,
        "output_size": 1024,
    }
    for key, value in defaults.items():
        options.setdefault(key, value)
    options["checkpoint_path"] = str(checkpoint_path)
    options["device"] = args.device

    del checkpoint

    build_started = perf_counter()
    net = pSp(Namespace(**options))
    net.eval()
    net.to(args.device)
    build_seconds = perf_counter() - build_started

    source = Image.open(image_path).convert("RGB")
    original_size = source.size
    aligned = source.resize((256, 256), Image.BICUBIC)
    rgb = np.asarray(aligned, dtype=np.float32) / 255.0
    base = torch.from_numpy(rgb).permute(2, 0, 1)
    base = (base - 0.5) / 0.5

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=False)
    runs = []
    for age in args.target_ages:
        age_channel = torch.full((1, 256, 256), age / 100.0, dtype=torch.float32)
        model_input = torch.cat((base, age_channel), dim=0).unsqueeze(0).to(args.device)
        if args.device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        started = perf_counter()
        output = net(model_input, randomize_noise=False, resize=False)
        if args.device == "cuda":
            torch.cuda.synchronize()
            peak_vram = torch.cuda.max_memory_allocated()
        else:
            peak_vram = 0
        seconds = perf_counter() - started

        image = output[0].clamp(-1, 1).add(1).mul(127.5).to(torch.uint8)
        array = image.permute(1, 2, 0).cpu().numpy()
        name = f"age-{age:03d}.png"
        path = output_dir / name
        Image.fromarray(array).save(path)
        runs.append(
            {
                "target_age": age,
                "seconds": seconds,
                "peak_vram_bytes": int(peak_vram),
                "output": name,
                "output_sha256": _sha256(path),
                "pixel_min": int(array.min()),
                "pixel_max": int(array.max()),
                "pixel_mean": float(array.mean()),
            }
        )

    marker = root / "models" / "stylegan2" / "op" / "NATIVE_OPS.json"
    report = {
        "schema_version": 1,
        "scope": "offline SAM checkpoint inference probe at selected target ages",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "years_calibrated": False,
        "uv_registered": False,
        "identity_accepted": False,
        "outputs_written": all(run["output_sha256"] for run in runs),
        "started_at_utc": started_at,
        "checkpoint": {
            "path": str(checkpoint_path),
            "bytes": checkpoint_path.stat().st_size,
            "sha256": _sha256(checkpoint_path),
        },
        "environment": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "cuda_build": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "device": args.device,
            "device_name": torch.cuda.get_device_name(0) if args.device == "cuda" else "cpu",
            "capability": list(torch.cuda.get_device_capability(0))
            if args.device == "cuda"
            else None,
            "total_vram_bytes": torch.cuda.get_device_properties(0).total_memory
            if args.device == "cuda"
            else 0,
        },
        "options": {
            key: options.get(key)
            for key in (
                "input_nc",
                "output_size",
                "start_from_latent_avg",
                "start_from_encoded_w_plus",
                "target_age",
            )
        },
        "input": {
            "path": str(image_path),
            "sha256": _sha256(image_path),
            "original_size": list(original_size),
            "aligned_size": [256, 256],
            "alignment": "FFHQ-style crop assumed; no alignment is performed here",
        },
        "timing": {
            "checkpoint_load_s": load_seconds,
            "model_build_s": build_seconds,
        },
        "op_shim": json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else None,
        "runs": runs,
        "limitations": [
            "2-D 1024x1024 images only; not registered to the BFM/UV atlas and not a mesh.",
            "No age calibration: target_age is the checkpoint's normalized conditioning input.",
            "One aligned sample is a feasibility check, not an accuracy or identity evaluation.",
            "Checkpoint and FFHQ-derived weights remain research-only and license-unresolved.",
        ],
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "device": report["environment"]["device_name"],
                "torch": report["environment"]["torch"],
                "cuda_build": report["environment"]["cuda_build"],
                "ages": args.target_ages,
                "seconds": [round(run["seconds"], 3) for run in runs],
                "peak_vram_mb": [
                    round(run["peak_vram_bytes"] / 1024**2, 1) for run in runs
                ],
            },
            ensure_ascii=False,
        )
    )
    print(f"wrote {output_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
