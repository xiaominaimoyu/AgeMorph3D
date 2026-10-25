"""Private real-photo research HTTP session probe, with explicit user source age.

All images and exact user metadata go to a fresh ignored local directory. This
launches an owned ephemeral loopback server, never the production API, and waits
for an explicitly hash-bound review of the new generated PNG.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import socket
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "tools"))

import httpx
import numpy as np
import uvicorn
from agemorph3d.aging_sessions import AgingSessionCache
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.images import decode_image
from agemorph3d.model_assets import load_verified_manifest
from agemorph3d.research_aging_app import create_research_app
from agemorph3d.research_aging_pipeline import (
    ResearchAgingProcessor,
    ResearchBindings,
    _read_fit,
    prepare_source_context,
)
from agemorph3d.research_aging_service import ResearchAgingService
from agemorph3d.sam_worker import SamWorkerClient
from agemorph3d.schemas import SourceAge
from agemorph3d.static_probe import _construct_model
from agemorph3d.tddfa import _npz_arrays, project_vertices
from PIL import Image
from research_aging_pipeline_probe import (
    MANIFESTS,
    SAM_PYTHON,
    UV,
    UV_SHA,
    CountingWorker,
    environment,
    frozen_inputs,
    geometry,
    pin,
    save,
    write_json,
)


async def run(args) -> int:
    age = SourceAge.from_form(args.source_age)
    if age.value is None or args.target_condition == age.value:
        raise ValueError("Use an explicit source age and a different integer target condition.")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "output/research"):
        raise ValueError("Private output must remain under ignored output/research.")
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "status": "running",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "quality_accepted": False,
        "source_age": age.model_dump(mode="json"),
        "target_condition": args.target_condition,
        "input_basis": "Explicit local-photo path and photo age supplied by its owner in chat",
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    inputs, env_before, models, source_records, target_fits = [], None, {}, [], []
    service = worker = server = server_task = listener = None
    try:
        source_path = args.image.resolve(strict=True)
        if source_path.stat().st_size > Settings().max_image_bytes:
            raise ValueError("Private image exceeds the bounded photo budget.")
        data = source_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != args.image_sha256:
            raise ValueError("Explicit private input SHA does not match.")
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(source_path.suffix.lower())
        if media_type is None:
            raise ValueError("Unsupported private image extension.")
        input_pin = save(output / ("private-source" + source_path.suffix.lower()), data)
        inputs = frozen_inputs() + [
            input_pin,
            pin(Path(__file__)),
            pin(ROOT / "docs/research-aging-service-v1.json"),
        ]
        inputs += [
            pin(p) for p in sorted((ROOT / "backend/tests").glob("test_research_aging_service*.py"))
        ]
        inputs += [
            pin(p) for p in sorted((ROOT / "backend/tests").glob("test_research_aging_app*.py"))
        ]
        inputs = list({p["path"]: p for p in inputs}.values())
        env_before = environment()
        write_json(
            output / "freeze.json",
            {
                "inputs": inputs,
                "environment": env_before,
                "source_age": report["source_age"],
                "private_input": input_pin,
                "input_basis": report["input_basis"],
                "target_condition": args.target_condition,
                "baseline_fgnet_pin_is_unused_reference": True,
                "same_source_condition_previously_inspected": args.prior_condition_seen,
                "evaluation_split": "User-owned development input, not independent evaluation",
                "review_wait_seconds": 180,
                "protocol": "research-aging-service-v1",
            },
        )
        bindings = ResearchBindings(
            *(pin(MANIFESTS[k])["sha256"] for k in ("detector", "reconstructor", "sam")), UV_SHA
        )
        for role in ("detector", "reconstructor"):
            assets = load_verified_manifest(MANIFESTS[role], research_allow_unresolved=True)
            models[role] = _construct_model(role, assets)
        uv_asset = _npz_arrays(UV, ("uv", "topology_sha256"))
        uv = np.asarray(uv_asset["uv"], dtype=np.float32)

        def fit(rgb):
            faces = models["detector"].detect(rgb)
            if len(faces) != 1:
                raise ApiError(
                    422, "NO_FACE" if not faces else "MULTI_FACE", "研究输入必须恰有一张人脸。"
                )
            result = models["reconstructor"].reconstruct(rgb, faces[0].bbox)
            if result.topology_sha256 != str(uv_asset["topology_sha256"].item()):
                raise ValueError("Fixed common UV topology differs from the actual model.")
            return result

        def source_builder(image_bytes, content_type, source_age):
            with decode_image(image_bytes, content_type, Settings()) as image:
                rgb = np.asarray(image).copy()
            raw = fit(rgb)
            result = prepare_source_context(
                rgb, raw, models["reconstructor"].keypoint_coordinates, uv, source_age, bindings
            )
            source_records.append(result)
            return result

        def target_refitter(rgb):
            raw = fit(rgb)
            target_fits.append(raw)
            return raw

        worker = SamWorkerClient(
            python_executable=SAM_PYTHON,
            worker_script=ROOT / "tools/sam_worker.py",
            manifest_path=MANIFESTS["sam"],
            sam_root=ROOT / "data/third_party/SAM",
            device="cuda",
            research_allow_unresolved=True,
            startup_timeout_s=180,
            request_timeout_s=180,
            shutdown_timeout_s=15,
        )
        counted = CountingWorker(worker)
        processor = ResearchAgingProcessor(counted, target_refitter, bindings)
        cache = AgingSessionCache(max_entries=2, ttl_seconds=300)
        service = ResearchAgingService(processor, source_builder, cache=cache)
        app = create_research_app(service)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
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
        began = time.monotonic()
        while not server.started:
            if server_task.done():
                await server_task
                raise RuntimeError("Research server exited before starting.")
            if time.monotonic() - began > 30:
                raise TimeoutError("Research server startup timed out.")
            await asyncio.sleep(0.05)
        report["loopback"] = {"host": "127.0.0.1", "port": port}
        http_records = []
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=190) as client:

            async def request(method, url, expected=200, **kwargs):
                response = await client.request(method, url, **kwargs)
                http_records.append({"method": method, "path": url, "status": response.status_code})
                assert response.status_code == expected, (
                    url,
                    response.status_code,
                    response.text[:256],
                )
                assert response.headers.get("cache-control") == "no-store"
                assert response.headers.get("x-content-type-options") == "nosniff"
                return response

            health = (await request("GET", "/research/health")).json()
            assert health["research_only"] and not health["service_ready"]
            await request("POST", "/api/aging", expected=404, json={})
            await request(
                "GET",
                "/research/health",
                expected=403,
                headers={"Origin": "https://example.invalid"},
            )
            created = (
                await request(
                    "POST",
                    "/research/sessions",
                    content=data,
                    headers={"Content-Type": media_type},
                    params={"source_age": args.source_age},
                )
            ).json()
            sid = created["session_id"]
            source_url = created["source_glb_url"]
            source_glb = (await request("GET", source_url)).content
            source_texture = (await request("GET", created["source_texture_url"])).content
            save(output / "source.glb", source_glb)
            save(output / "source-texture.png", source_texture)
            save(output / "source-context.json", source_records[0].correspondence)
            save(output / "source-aligned.png", source_records[0].aligned_png)
            assert created["source_age"] == report["source_age"]
            reset = (
                await request("POST", f"/research/sessions/{sid}/absolute", json={"age": age.value})
            ).json()
            assert reset["kind"] == "source_reset" and counted.calls == 0
            assert (await request("GET", reset["mesh_url"])).content == source_glb
            report["initial_exact_source_reset"] = True
            fractional = age.value + 0.125 if age.value <= 69 else age.value - 0.125
            rejected = (
                await request(
                    "POST",
                    f"/research/sessions/{sid}/absolute",
                    expected=422,
                    json={"age": fractional},
                )
            ).json()
            assert rejected["code"] == "INTEGER_AGE_REQUIRED" and counted.calls == 0
            generating = asyncio.create_task(
                request(
                    "POST",
                    f"/research/sessions/{sid}/absolute",
                    expected=409,
                    json={"age": args.target_condition},
                )
            )
            try:
                await asyncio.wait_for(counted.entered.wait(), 60)
                busy = (
                    await request(
                        "POST",
                        "/research/sessions",
                        expected=429,
                        content=data,
                        headers={"Content-Type": media_type},
                        params={"source_age": args.source_age},
                    )
                ).json()
                assert busy["code"] == "BUSY" and len(source_records) == 1
                assert (await request("GET", "/research/health")).json()["service_ready"] is False
                staged_response = (await generating).json()
            finally:
                if not generating.done():
                    await asyncio.gather(generating, return_exceptions=True)
            assert staged_response["code"] == "REVIEW_REQUIRED"
            target = staged_response["staged"]
            preview_png = (await request("GET", staged_response["preview_url"])).content
            fit_bytes = (await request("GET", staged_response["fit_url"])).content
            assert hashlib.sha256(preview_png).hexdigest() == target["generated_sha256"]
            assert hashlib.sha256(fit_bytes).hexdigest() == target["fit_sha256"]
            save(output / "generated.png", preview_png)
            save(output / "target-fit.json", fit_bytes)
            repeated_stage = (
                await request(
                    "POST",
                    f"/research/sessions/{sid}/conditions",
                    json={"condition": args.target_condition},
                )
            ).json()
            assert repeated_stage["staged"] == target and counted.calls == len(target_fits) == 1
            points = project_vertices(
                _read_fit(json.loads(fit_bytes)), models["reconstructor"].keypoint_coordinates
            )[:, :2]
            write_json(
                output / "review-request.json",
                {
                    "target": target,
                    "landmarks_xy": points.tolist(),
                    "image_size": [1024, 1024],
                    "review_scope": ("New user-owned pixels; AI local development review only"),
                },
            )
            print(
                json.dumps({"status": "review_required", "output": str(output), "target": target}),
                flush=True,
            )
            deadline = time.monotonic() + 180
            review_path = output / "review-input.json"
            while not review_path.exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Explicit local review was not supplied within180seconds.")
                await asyncio.sleep(0.2)
            if review_path.stat().st_size > 16384:
                raise ValueError("Review metadata exceeds the local budget.")
            record = json.loads(review_path.read_bytes())
            payload = {
                k: record[k]
                for k in (
                    "source_fingerprint",
                    "generated_sha256",
                    "fit_sha256",
                    "reviewer",
                    "method",
                    "version",
                    "reviewer_kind",
                )
            }
            for field in ("allowed", "occluded"):
                path = (output / record[field]).resolve(strict=True)
                if path.parent != output or path.stat().st_size > 4 * 1024**2:
                    raise ValueError("Review masks must be bounded files beside this run.")
                payload[field + "_png_b64"] = base64.b64encode(path.read_bytes()).decode("ascii")
            review_url = f"/research/sessions/{sid}/stages/{target['stage_id']}/reviews"
            mismatch = (
                await request(
                    "POST", review_url, expected=409, json={**payload, "fit_sha256": "f" * 64}
                )
            ).json()
            assert mismatch["code"] == "REVIEW_REQUIRED"
            registered = (await request("POST", review_url, json=payload)).json()
            glb = (await request("GET", registered["mesh_url"])).content
            texture = (await request("GET", registered["texture_url"])).content
            save(output / "registered.glb", glb)
            save(output / "registered-texture.png", texture)
            provenance = json.dumps(
                registered["provenance"], sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            save(output / "registered-provenance.json", provenance)
            assert geometry(glb)[1] == geometry(source_glb)[1]
            with Image.open(io.BytesIO(texture)) as atlas:
                rgba = np.asarray(atlas).copy()
            assert rgba.shape == (256, 256, 4) and not np.any(rgba[rgba[:, :, 3] == 0])
            known_texels = int(np.count_nonzero(rgba[:, :, 3]))
            assert known_texels > 0
            cached = (
                await request(
                    "POST",
                    f"/research/sessions/{sid}/absolute",
                    json={"age": args.target_condition},
                )
            ).json()
            assert cached["kind"] == "sam_registered_uv"
            assert (await request("GET", cached["mesh_url"])).content == glb
            reset = (
                await request("POST", f"/research/sessions/{sid}/absolute", json={"age": age.value})
            ).json()
            assert reset["kind"] == "source_reset"
            assert (await request("GET", reset["mesh_url"])).content == source_glb
            assert (await request("GET", reset["texture_url"])).content == source_texture
            assert counted.calls == len(target_fits) == 1
            unknown = (
                await request(
                    "POST", "/research/sessions", content=data, headers={"Content-Type": media_type}
                )
            ).json()
            unknown_error = (
                await request(
                    "POST",
                    f"/research/sessions/{unknown['session_id']}/absolute",
                    expected=422,
                    json={"age": args.target_condition},
                )
            ).json()
            assert unknown["source_age"]["value"] is None
            assert unknown_error["code"] == "SOURCE_AGE_REQUIRED" and counted.calls == 1
            report.update(
                status="passed",
                http=http_records,
                http_checks=len(http_records),
                source_age=created["source_age"],
                real_known_source_reset_verified=True,
                reviewed_cache_hit_verified=True,
                sam_generate_calls=counted.calls,
                target_refits=len(target_fits),
                source_builds=len(source_records),
                source_geometry_exact=True,
                known_texels=known_texels,
                unknown_texels=65536 - known_texels,
                unknown_rgba_zero=True,
                stage_hit_verified=True,
                unknown_source_rejected=True,
                service_before_close=service.snapshot(),
                worker_before_close=worker.snapshot(),
            )
    except Exception as error:  # noqa: BLE001 -- preserve private probe failure evidence
        report.update(
            status="failed",
            error_code=getattr(error, "code", "PROBE_FAILED"),
            error=f"{type(error).__name__}: {error}",
            traceback=traceback.format_exc(),
        )
    finally:
        cleanup_errors = []
        if server is not None:
            server.should_exit = True
        for label, job in (("server", server_task), ("service", service), ("worker", worker)):
            if job is None:
                continue
            try:
                if label == "server":
                    await job
                else:
                    await job.close()
            except Exception as error:  # noqa: BLE001 -- finish all owned cleanup
                cleanup_errors.append({"operation": label, "error": str(error)})
        if listener is not None:
            listener.close()
        for model in models.values():
            close = getattr(model, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as error:  # noqa: BLE001 -- retain cleanup failure
                    cleanup_errors.append({"operation": "model.close", "error": str(error)})
        models.clear()
        source_records.clear()
        target_fits.clear()
        if service is not None:
            report["service_after_close"] = service.snapshot()
            final_state = report["service_after_close"]
            if (
                not final_state["closed"]
                or final_state["active"]
                or final_state["native_cpu_active"]
                or final_state["downloads"]
                or any(
                    final_state["cache"][key]
                    for key in ("entries", "payload_bytes", "pins", "results")
                )
            ):
                cleanup_errors.append(
                    {"operation": "service.release", "error": "Owned work or charged cache remains"}
                )
        if worker is not None:
            report["worker_after_close"] = worker.snapshot()
            if worker.snapshot()["returncode"] != 0 or worker.snapshot()["worker_exitcode"] != 0:
                cleanup_errors.append(
                    {"operation": "worker.exit", "error": "Normal exit not confirmed"}
                )
        report["server_task_finished"] = server_task is not None and server_task.done()
        report["cleanup_errors"] = cleanup_errors
        changed = []
        for item in inputs:
            try:
                if pin(ROOT / item["path"]) != item:
                    changed.append(item["path"])
            except OSError:
                changed.append(item["path"])
        report["inputs_checked"] = len(inputs)
        report["inputs_unchanged"] = bool(inputs) and not changed
        report["changed_inputs"] = changed
        try:
            report["environment_unchanged"] = env_before is not None and environment() == env_before
        except Exception as error:  # noqa: BLE001 -- always write private receipt
            report["environment_unchanged"] = False
            cleanup_errors.append({"operation": "environment", "error": str(error)})
        if cleanup_errors or changed or not report["environment_unchanged"]:
            report["status"] = "failed"
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        write_json(output / "report.json", report)
    print(json.dumps({"status": report["status"], "output": str(output)}), flush=True)
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--source-age", required=True)
    parser.add_argument("--target-condition", type=int, choices=range(20, 71), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-condition-seen", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
