"""Owned loopback research server for the independent session display page.

No source image is embedded or written by this server. Model permission remains
research-only; an explicit unresolved-license override never enables production.
The owner stops this process by writing its PID to control-dir/stop.json.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import socket
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np
import uvicorn
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.images import decode_image
from agemorph3d.model_assets import load_verified_manifest
from agemorph3d.research_aging_app import create_research_app
from agemorph3d.research_aging_pipeline import (
    ResearchAgingProcessor,
    ResearchBindings,
    prepare_source_context,
)
from agemorph3d.research_aging_service import ResearchAgingService
from agemorph3d.sam_worker import SamWorkerClient
from agemorph3d.static_probe import _construct_model
from agemorph3d.tddfa import _npz_arrays
from research_aging_pipeline_probe import (
    MANIFESTS,
    SAM_PYTHON,
    UV,
    UV_SHA,
    environment,
    pin,
    write_json,
)


class _CountingWorker:
    def __init__(self, worker):
        self.worker, self.generate_calls = worker, 0

    async def generate(self, image, condition):
        self.generate_calls += 1
        return await self.worker.generate(image, condition)

    async def wait_idle(self):
        return await self.worker.wait_idle()

    async def close(self):
        return await self.worker.close()


async def serve(args) -> int:
    control = args.control_dir.resolve()
    if not control.is_relative_to(ROOT / "output/research"):
        raise ValueError("Use a fresh owned control directory under ignored output/research.")
    control.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "status": "starting",
        "pid": os.getpid(),
        "research_only": True,
        "service_ready": False,
        "production_enabled": False,
        "g3_complete": False,
        "quality_accepted": False,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "input_images_written": False,
    }
    models, counts = {}, {"source_builds": 0, "target_refits": 0}
    worker = counted = service = server = server_task = watcher = listener = None
    try:
        report["environment_before"] = environment()
        bindings = ResearchBindings(
            *(pin(MANIFESTS[k])["sha256"] for k in ("detector", "reconstructor", "sam")), UV_SHA
        )
        for role in ("detector", "reconstructor"):
            assets = load_verified_manifest(
                MANIFESTS[role], research_allow_unresolved=args.research_allow_unresolved
            )
            models[role] = _construct_model(role, assets)
        if pin(UV)["sha256"] != UV_SHA:
            raise ValueError("Frozen common UV fingerprint differs.")
        uv_asset = _npz_arrays(UV, ("uv", "topology_sha256"))
        uv = np.asarray(uv_asset["uv"], dtype=np.float32)

        def fit(rgb):
            faces = models["detector"].detect(rgb)
            if len(faces) != 1:
                raise ApiError(
                    422, "NO_FACE" if not faces else "MULTI_FACE", "研究输入必须恰有一张人脸。"
                )
            raw = models["reconstructor"].reconstruct(rgb, faces[0].bbox)
            if raw.topology_sha256 != str(uv_asset["topology_sha256"].item()):
                raise ValueError("Common UV no longer matches the model topology.")
            return raw

        def source_builder(data, media_type, source_age):
            with decode_image(data, media_type, Settings()) as image:
                rgb = np.asarray(image).copy()
            raw = fit(rgb)
            result = prepare_source_context(
                rgb, raw, models["reconstructor"].keypoint_coordinates, uv, source_age, bindings
            )
            counts["source_builds"] += 1
            return result

        def target_refitter(rgb):
            raw = fit(rgb)
            counts["target_refits"] += 1
            return raw

        worker = SamWorkerClient(
            python_executable=SAM_PYTHON,
            worker_script=ROOT / "tools/sam_worker.py",
            manifest_path=MANIFESTS["sam"],
            sam_root=ROOT / "data/third_party/SAM",
            device="cuda",
            research_allow_unresolved=args.research_allow_unresolved,
            startup_timeout_s=180,
            request_timeout_s=180,
            shutdown_timeout_s=15,
        )
        counted = _CountingWorker(worker)
        service = ResearchAgingService(
            ResearchAgingProcessor(counted, target_refitter, bindings), source_builder
        )
        settings = Settings(
            allowed_origins=tuple(args.allowed_origin),
            max_json_bytes=12 * 1024**2,
            http_timeout_seconds=180,
        )
        app = create_research_app(service, settings)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", args.port))
        listener.listen(16)
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
                lifespan="on",
                timeout_graceful_shutdown=30,
            )
        )
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started:
            if server_task.done():
                await server_task
                raise RuntimeError("Owned server stopped before startup.")
            await asyncio.sleep(0.05)
        report.update(
            status="serving",
            base_url=f"http://127.0.0.1:{port}",
            allowed_origins=list(settings.allowed_origins),
        )
        write_json(control / "ready.json", report)
        print(
            json.dumps(
                {"status": "serving", "control_dir": str(control), "base_url": report["base_url"]}
            ),
            flush=True,
        )

        async def stop_when_requested():
            while not server.should_exit:
                path = control / "stop.json"
                if path.exists():
                    if path.stat().st_size > 256:
                        raise ValueError("Stop request exceeds its small owner budget.")
                    value = json.loads(path.read_bytes())
                    if value != {"pid": os.getpid(), "stop": True}:
                        raise ValueError("Stop request does not match this owned server PID.")
                    server.should_exit = True
                    return
                await asyncio.sleep(0.2)

        watcher = asyncio.create_task(stop_when_requested())
        done, _ = await asyncio.wait({server_task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            watcher.result()
        await server_task
        report["status"] = "closed"
    except Exception as error:  # noqa: BLE001 -- retain owned research failure evidence
        report.update(
            status="failed",
            error_code=getattr(error, "code", "SERVER_FAILED"),
            error=f"{type(error).__name__}: {error}",
            traceback=traceback.format_exc(),
        )
    finally:
        errors = []
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        if server is not None:
            server.should_exit = True
        for label, value in (("server", server_task), ("service", service), ("worker", worker)):
            if value is None:
                continue
            try:
                if label == "server":
                    await value
                else:
                    await value.close()
            except Exception as error:  # noqa: BLE001 -- complete all owned cleanup
                errors.append({"operation": label, "error": str(error)})
        if listener is not None:
            listener.close()
        for model in models.values():
            close = getattr(model, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as error:  # noqa: BLE001 -- record cleanup error
                    errors.append({"operation": "model.close", "error": str(error)})
        models.clear()
        gc.collect()
        report["counts"] = {
            **counts,
            "sam_generate_calls": 0 if counted is None else counted.generate_calls,
        }
        report["service_after_close"] = None if service is None else service.snapshot()
        report["worker_after_close"] = None if worker is None else worker.snapshot()
        report["cleanup_errors"] = errors
        try:
            report["environment_unchanged"] = environment() == report.get("environment_before")
        except Exception as error:  # noqa: BLE001 -- always keep the owner receipt
            report["environment_unchanged"] = False
            errors.append({"operation": "environment", "error": str(error)})
        if not report["environment_unchanged"]:
            report["status"] = "failed"
        if errors:
            report["status"] = "failed"
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        write_json(control / "closed.json", report)
    return 0 if report["status"] == "closed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--allowed-origin", action="append", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--research-allow-unresolved", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be within0..65535")
    return asyncio.run(serve(args))


if __name__ == "__main__":
    raise SystemExit(main())
