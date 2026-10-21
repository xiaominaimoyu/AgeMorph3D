"""Persistent framed-stdio SAM worker for explicitly permitted local research.

Run only with data/envs/sam. PNG bytes enter/leave pipes; no input paths, source
photos, generated images or checkpoints are written by this worker. stdout is
reserved for 4-byte big-endian length + UTF-8 JSON frames (maximum 8 MiB).
"""

from __future__ import annotations

import argparse
import base64
import gc
import hashlib
import io
import json
import os
import struct
import sys
from argparse import Namespace
from pathlib import Path
from time import perf_counter

MAX_FRAME_BYTES = 8 * 1024**2
MAX_INPUT_BYTES = 1024**2
CHECKPOINT_SHA256 = "6fbd6085e2e6001f51f6dee896ae5ba7bd6c3fab5c06fadba75f2a12188ba143"
CHECKPOINT_BYTES = 2270547237
SAM_REVISION = "c1895aef275e702fba7560284dc16df60d65210e"
CODE_PINS = {
    "models/psp.py": "3bfe3daff808bb42834d334502b9206be6696d80e762151db7309a9a04173620",
    "models/stylegan2/op/fused_act.py": (
        "eb4be5277f5ac0c6a7702f8808c65f7d12cc0eec1b50b32835c0f78ff5ec927d"
    ),
    "models/stylegan2/op/upfirdn2d.py": (
        "1e27ad094bf4345288f1c7376698c7ffb9ea8261c15c4601833cebcda095a588"
    ),
}


class ResearchWorkerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024**2):
            digest.update(block)
    return digest.hexdigest()


def verify_assets(manifest_path: Path, root: Path, *, allow_unresolved: bool) -> dict:
    """Reject unrecognized assets before torch import or checkpoint unpickling."""
    manifest_path, root = manifest_path.resolve(strict=True), root.resolve(strict=True)
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("license", {}).get("status") != "research-only-unresolved":
        raise ResearchWorkerError("ASSET_LICENSE", "Unrecognized research manifest license state.")
    if not allow_unresolved:
        raise ResearchWorkerError("ASSET_LICENSE", "Explicit research permission is required.")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("model_id") != "sam-ffhq-aging"
        or manifest.get("source", {}).get("code_revision") != SAM_REVISION
    ):
        raise ResearchWorkerError("ASSET_HASH", "Unexpected SAM manifest or source revision.")
    artifacts = manifest.get("artifacts", [])
    if len(artifacts) != 1:
        raise ResearchWorkerError("ASSET_HASH", "Expected one pinned SAM checkpoint.")
    artifact = artifacts[0]
    checkpoint = (manifest_path.parent / artifact.get("path", "")).resolve(strict=True)
    if (
        not checkpoint.is_relative_to(manifest_path.parent)
        or artifact.get("role") != "aging_generator_checkpoint"
        or artifact.get("sha256") != CHECKPOINT_SHA256
        or artifact.get("size_bytes") != CHECKPOINT_BYTES
        or not checkpoint.is_file()
        or checkpoint.stat().st_size != CHECKPOINT_BYTES
        or _sha256(checkpoint) != CHECKPOINT_SHA256
    ):
        raise ResearchWorkerError("ASSET_HASH", "SAM checkpoint pin mismatch.")
    for relative, expected in CODE_PINS.items():
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or _sha256(path) != expected:
            raise ResearchWorkerError("ASSET_HASH", "SAM loader/native shim pin mismatch.")
    marker_path = root / "models/stylegan2/op/NATIVE_OPS.json"
    marker = json.loads(marker_path.read_bytes())
    if marker.get("sam_commit") != SAM_REVISION:
        raise ResearchWorkerError("ASSET_HASH", "Unexpected SAM native-op marker revision.")
    for name in ("fused_act.py", "upfirdn2d.py"):
        if (
            marker.get("files", {}).get(name, {}).get("installed_sha256")
            != CODE_PINS["models/stylegan2/op/" + name]
        ):
            raise ResearchWorkerError("ASSET_HASH", "SAM native-op marker pin mismatch.")
    return {
        "manifest_sha256": _sha256(manifest_path),
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_bytes": CHECKPOINT_BYTES,
        "code_revision_claim": SAM_REVISION,
        "code_pins": dict(CODE_PINS),
        "native_marker_sha256": _sha256(marker_path),
        "license_status": "research-only-unresolved",
        "checkpoint_path": str(checkpoint),
    }


class SamEngine:
    def __init__(self, root: Path, checkpoint: Path, device: str) -> None:
        sys.path.insert(0, str(root))
        import torch
        from models.psp import pSp

        self.torch, self.device, self.net = torch, device, None
        if device == "cuda" and not torch.cuda.is_available():
            raise ResearchWorkerError("DEVICE_UNAVAILABLE", "Requested CUDA device is unavailable.")
        began = perf_counter()
        try:
            checkpoint_data = torch.load(checkpoint, map_location="cpu", weights_only=False)
            options = checkpoint_data["opts"]
            options = vars(options).copy() if isinstance(options, Namespace) else dict(options)
            del checkpoint_data
            for key, value in {
                "start_from_latent_avg": True,
                "start_from_encoded_w_plus": False,
                "input_nc": 4,
                "output_size": 1024,
            }.items():
                options.setdefault(key, value)
            if options["input_nc"] != 4 or options["output_size"] != 1024:
                raise ResearchWorkerError("MODEL_SELFTEST", "Unexpected SAM input/output contract.")
            options.update(checkpoint_path=str(checkpoint), device=device)
            # pSp owns a second checkpoint read. One model is built for the entire process.
            self.net = pSp(Namespace(**options))
            self.net.eval().to(device)
            self.load_seconds = perf_counter() - began
            with torch.inference_mode():
                test_input = torch.zeros((1, 4, 256, 256), device=device)
                test_input[:, 3] = 0.45
                output, seconds, peak = self._forward(test_input)
                del output, test_input
            self.selftest = {
                "passed": True,
                "scope": "synthetic-input finite 1x3x1024x1024 forward; no quality claim",
                "seconds": seconds,
                "peak_vram_bytes": peak,
            }
        except BaseException:
            self.close()
            raise

    def _forward(self, model_input):
        torch = self.torch
        if self.device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        started = perf_counter()
        output = self.net(model_input, randomize_noise=False, resize=False)
        if self.device == "cuda":
            torch.cuda.synchronize()
        seconds = perf_counter() - started
        if tuple(output.shape) != (1, 3, 1024, 1024) or not torch.isfinite(output).all().item():
            raise ResearchWorkerError("MODEL_SELFTEST", "SAM produced invalid output tensors.")
        peak = int(torch.cuda.max_memory_allocated()) if self.device == "cuda" else 0
        return output, seconds, peak

    def generate(self, request: dict) -> dict:
        import numpy as np
        from PIL import Image

        if set(request) != {"id", "type", "png_b64", "input_sha256", "target_age"}:
            raise ResearchWorkerError("INVALID_REQUEST", "Unexpected generation fields.")
        age = request["target_age"]
        if type(age) is not int or not 20 <= age <= 70:
            raise ResearchWorkerError("INVALID_REQUEST", "SAM requires an integer age in 20..70.")
        try:
            encoded = request["png_b64"]
            if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_INPUT_BYTES + 2) // 3):
                raise ValueError("Oversized PNG.")
            image_bytes = base64.b64decode(encoded, validate=True)
            input_hash = hashlib.sha256(image_bytes).hexdigest()
            if not 0 < len(image_bytes) <= MAX_INPUT_BYTES or input_hash != request["input_sha256"]:
                raise ValueError("PNG integrity mismatch.")
            with Image.open(io.BytesIO(image_bytes)) as image:
                if (
                    image.format != "PNG"
                    or image.size != (256, 256)
                    or image.mode != "RGB"
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise ValueError("Expected an aligned 256x256 RGB PNG.")
                image.load()
                rgb = np.asarray(image, dtype=np.float32) / 255.0
        except (ValueError, TypeError, OSError) as error:
            raise ResearchWorkerError("INVALID_REQUEST", "Invalid aligned PNG bytes.") from error
        torch = self.torch
        with torch.inference_mode():
            base = (torch.from_numpy(rgb).permute(2, 0, 1) - 0.5) / 0.5
            age_channel = torch.full((1, 256, 256), age / 100.0, dtype=torch.float32)
            model_input = torch.cat((base, age_channel)).unsqueeze(0).to(self.device)
            output, seconds, peak = self._forward(model_input)
            pixels = output[0].clamp(-1, 1).add(1).mul(127.5).to(torch.uint8)
            array = pixels.permute(1, 2, 0).cpu().numpy()
            destination = io.BytesIO()
            Image.fromarray(array).save(destination, format="PNG")
            png = destination.getvalue()
        return {
            "png_b64": base64.b64encode(png).decode("ascii"),
            "sha256": hashlib.sha256(png).hexdigest(),
            "input_sha256": input_hash,
            "target_age": age,
            "seconds": seconds,
            "peak_vram_bytes": peak,
        }

    def close(self) -> None:
        net, self.net = self.net, None
        if net is not None:
            # Upstream latent_avg is a plain tensor, not a registered buffer.
            net.latent_avg = None
        del net
        gc.collect()
        if self.device == "cuda" and self.torch.cuda.is_initialized():
            try:
                self.torch.cuda.synchronize()
            finally:
                self.torch.cuda.empty_cache()


def _read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            raise EOFError
        chunks.extend(chunk)
    return bytes(chunks)


def read_frame(stream) -> dict:
    length = struct.unpack(">I", _read_exact(stream, 4))[0]
    if not 2 <= length <= MAX_FRAME_BYTES:
        raise ResearchWorkerError("WORKER_PROTOCOL", "Invalid frame size.")
    value = json.loads(_read_exact(stream, length))
    if not isinstance(value, dict):
        raise ResearchWorkerError("WORKER_PROTOCOL", "Expected a JSON object.")
    return value


def write_frame(stream, value: dict) -> None:
    encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if not 2 <= len(encoded) <= MAX_FRAME_BYTES:
        raise ResearchWorkerError("WORKER_PROTOCOL", "Output frame exceeds budget.")
    stream.write(struct.pack(">I", len(encoded)) + encoded)
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sam-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--research-allow-unresolved", action="store_true")
    args = parser.parse_args()
    protocol_output, protocol_input = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr  # Third-party model loading prints must never corrupt frames.
    identity = {"pid": os.getpid(), "load_count": 1, "research_only": True, "service_ready": False}
    write_frame(
        protocol_output,
        {
            "type": "hello",
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
        },
    )
    engine = None
    try:
        pins = verify_assets(
            args.manifest, args.sam_root, allow_unresolved=args.research_allow_unresolved
        )
        engine = SamEngine(args.sam_root.resolve(), Path(pins.pop("checkpoint_path")), args.device)
        ready = {
            **identity,
            "type": "ready",
            "protocol_version": 1,
            "state": "research_loaded",
            "pins": pins,
            "device": args.device,
            "torch": engine.torch.__version__,
            "load_seconds": engine.load_seconds,
            "checkpoint_reads_at_startup": 2,
            "selftest": engine.selftest,
        }
        write_frame(protocol_output, ready)
    except Exception as error:
        print(f"SAM startup failed: {type(error).__name__}: {error}", file=sys.stderr)
        write_frame(
            protocol_output,
            {
                "type": "startup_error",
                "code": getattr(error, "code", "MODEL_NOT_READY"),
                "research_only": True,
                "service_ready": False,
            },
        )
        return 1
    try:
        while True:
            try:
                request = read_frame(protocol_input)
            except EOFError:
                break
            if not isinstance(request.get("id"), str) or not 1 <= len(request["id"]) <= 64:
                raise ResearchWorkerError("WORKER_PROTOCOL", "Invalid request ID.")
            kind = request.get("type")
            response = {**identity, "id": request["id"], "type": str(kind) + "_result"}
            try:
                if kind == "generate":
                    response.update(engine.generate(request))
                elif kind == "health" and set(request) == {"type", "id"}:
                    response.update(state="research_loaded", selftest=engine.selftest, pins=pins)
                elif kind == "shutdown" and set(request) == {"type", "id"}:
                    engine.close()
                    engine = None
                    response["context_release_requires_process_exit"] = True
                    write_frame(protocol_output, response)
                    break
                else:
                    raise ResearchWorkerError("INVALID_REQUEST", "Unknown request or fields.")
            except ResearchWorkerError as error:
                fatal = error.code != "INVALID_REQUEST"
                response.update(type="error", code=error.code, fatal=fatal)
                write_frame(protocol_output, response)
                if fatal:
                    return 1
                continue
            except Exception as error:
                print(f"SAM inference failed: {type(error).__name__}: {error}", file=sys.stderr)
                response.update(type="error", code="MODEL_INFERENCE_FAILED", fatal=True)
                write_frame(protocol_output, response)
                return 1
            write_frame(protocol_output, response)
    except Exception as error:
        print(f"SAM protocol failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
