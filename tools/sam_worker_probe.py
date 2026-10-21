"""Two real requests through one persistent research worker; never enables service readiness."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from agemorph3d.sam_worker import SamWorkerClient  # noqa: E402


def pin(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


async def probe(args) -> int:
    output = args.output_dir.resolve()
    image = args.image.resolve(strict=True)
    if not output.is_relative_to(ROOT) or not image.is_relative_to(ROOT):
        raise ValueError("Research input/output must stay in this repository.")
    image_bytes = image.read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "scope": "persistent SAM stdio research worker smoke, two identical requests",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "years_calibrated": False,
        "identity_accepted": False,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "input": pin(image),
        "manifest": pin(args.manifest.resolve()),
        "worker_source": pin(ROOT / "tools/sam_worker.py"),
        "client_source": pin(ROOT / "backend/src/agemorph3d/sam_worker.py"),
        "target_age": args.target_age,
        "status": "running",
        "runs": [],
    }
    client = SamWorkerClient(
        python_executable=args.python,
        worker_script=ROOT / "tools/sam_worker.py",
        manifest_path=args.manifest,
        sam_root=args.sam_root,
        device=args.device,
        research_allow_unresolved=args.research_allow_unresolved,
        startup_timeout_s=args.startup_timeout_s,
        request_timeout_s=args.request_timeout_s,
        shutdown_timeout_s=args.shutdown_timeout_s,
    )
    failure = None
    try:
        began = perf_counter()
        report["startup"] = await client.start()
        report["startup_wall_seconds"] = perf_counter() - began
        report["health"] = await client.health()
        for index in (1, 2):
            began = perf_counter()
            generated = await client.generate(image_bytes, args.target_age)
            destination = output / f"request-{index}-age-{args.target_age:03d}.png"
            destination.write_bytes(generated.png)
            report["runs"].append(
                {
                    "request": index,
                    "pid": generated.pid,
                    "load_count": generated.load_count,
                    "input_sha256": generated.input_sha256,
                    "target_age": generated.target_age,
                    "forward_seconds": generated.seconds,
                    "request_wall_seconds": perf_counter() - began,
                    "peak_vram_bytes": generated.peak_vram_bytes,
                    "output": pin(destination),
                }
            )
        first, second = report["runs"]
        assert first["pid"] == second["pid"] == report["startup"]["pid"]
        assert first["load_count"] == second["load_count"] == 1
        assert first["output"]["sha256"] == second["output"]["sha256"]
        report["same_worker_two_requests"] = True
        report["identical_png_sha256"] = True
        report["status"] = "passed"
    except Exception as error:
        failure = error
        report.update(status="failed", error_code=getattr(error, "code", "PROBE_FAILED"))
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["close"] = await client.close()
        report["process_exit_confirmed"] = report["close"]["returncode"] is not None
        if sys.platform == "win32":
            report["process_exit_confirmed"] &= report["close"]["worker_exitcode"] is not None
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        if report["status"] == "passed" and report["close"]["returncode"] != 0:
            report["status"] = "failed"
            report["error_code"] = "WORKER_EXIT"
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"status": report["status"], "output": str(output), "research_only": True}))
    if failure is not None:
        print(report["error"], file=sys.stderr)
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=ROOT / "data/envs/sam/Scripts/python.exe")
    parser.add_argument("--sam-root", type=Path, default=ROOT / "data/third_party/SAM")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/models/sam/manifest.json")
    parser.add_argument("--image", type=Path, required=True, help="Existing FFHQ 256x256 RGB PNG.")
    parser.add_argument("--target-age", type=int, choices=range(20, 71), default=45)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--startup-timeout-s", type=float, default=120)
    parser.add_argument("--request-timeout-s", type=float, default=120)
    parser.add_argument("--shutdown-timeout-s", type=float, default=15)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--research-allow-unresolved", action="store_true")
    return asyncio.run(probe(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
