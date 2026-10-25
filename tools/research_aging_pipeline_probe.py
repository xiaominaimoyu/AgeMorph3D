"""One frozen development image through the isolated real SAM/review/UV pipeline.

The review is supplied separately after inspecting the newly generated PNG. The
worker remains alive while waiting, with a bounded deadline. No production API,
source-age inference, automatic mask or quality acceptance is provided here.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import inspect
import io
import json
import struct
import subprocess
import sys
import time
import traceback
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

import numpy as np
from agemorph3d.aging_sessions import AgingCoordinator, AgingSessionCache
from agemorph3d.asset_cache import AssetCache, AssetCacheClosed
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.images import decode_image
from agemorph3d.model_assets import load_verified_manifest
from agemorph3d.research_aging_pipeline import (
    ResearchAgingProcessor,
    ResearchBindings,
    TargetMaskReview,
    prepare_source_context,
    source_fingerprint,
)
from agemorph3d.sam_worker import SamWorkerClient
from agemorph3d.schemas import SourceAge
from agemorph3d.static_probe import _construct_model
from agemorph3d.tddfa import _npz_arrays
from PIL import Image

IMAGE = ROOT / "data/datasets/fgnet/FGNET/images/006A55.JPG"
IMAGE_SHA = "b8a99ca31e94e5e52578a2ddc6f4460029616c1a7532a2928812d49af95c73b3"
UV = ROOT / "output/backend/b45/combined-real/uv_bound.npz"
UV_SHA = "7e412e7e1f7337816db7175c2db0020854b9a77292e7582763e9d45b06e3ad7b"
MANIFESTS = {
    "detector": ROOT / "data/models/yolov5n05-face/manifest.json",
    "reconstructor": ROOT / "data/models/3ddfa-v2/manifest.json",
    "sam": ROOT / "data/models/sam/manifest.json",
}
SAM_PYTHON = ROOT / "data/envs/sam/Scripts/python.exe"


def pin(path: Path) -> dict:
    path = path.resolve(strict=True)
    if not path.is_relative_to(ROOT):
        raise ValueError("Research inputs must stay inside the workspace.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(1024**2):
            digest.update(data)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def save(path: Path, data: bytes) -> dict:
    with path.open("xb") as stream:
        stream.write(data)
    return pin(path)


def environment() -> dict:
    code = (
        "import importlib.metadata,json,sys; "
        "print(json.dumps({'python':sys.version,'packages':sorted("
        "(d.metadata['Name'],d.version) for d in importlib.metadata.distributions())}))"
    )
    sam = subprocess.run(
        [str(SAM_PYTHON), "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "backend": {
            "python": sys.version,
            "packages": sorted(
                (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
            ),
        },
        "sam": json.loads(sam.stdout),
    }


def geometry(glb: bytes) -> tuple[dict, dict]:
    if glb[:4] != b"glTF" or struct.unpack_from("<I", glb, 8)[0] != len(glb):
        raise ValueError("Invalid standalone GLB.")
    size, kind = struct.unpack_from("<I4s", glb, 12)
    if kind != b"JSON":
        raise ValueError("Missing GLB document.")
    doc, binary = json.loads(glb[20 : 20 + size]), glb[28 + size :]
    primitive = doc["meshes"][0]["primitives"][0]
    values = {}
    for name, index in {
        **primitive["attributes"],
        "indices": primitive["indices"],
    }.items():
        accessor = doc["accessors"][index]
        view = doc["bufferViews"][accessor["bufferView"]]
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        width = {5123: 2, 5125: 4, 5126: 4}[accessor["componentType"]]
        length = accessor["count"] * {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[accessor["type"]] * width
        values[name] = hashlib.sha256(binary[start : start + length]).hexdigest()
    return doc, values


class CountingWorker:
    def __init__(self, worker):
        self.worker, self.calls = worker, 0
        self.entered = asyncio.Event()

    async def generate(self, data, age):
        self.calls += 1
        self.entered.set()
        return await self.worker.generate(data, age)

    async def wait_idle(self):
        return await self.worker.wait_idle()

    async def close(self):
        return await self.worker.close()


def frozen_inputs() -> list[dict]:
    paths = {
        IMAGE,
        UV,
        *MANIFESTS.values(),
        Path(__file__),
        ROOT / "backend/tests/test_research_aging_pipeline.py",
        ROOT / "docs/research-aging-pipeline-v1.json",
        ROOT / "tools/sam_worker.py",
        ROOT / "data/third_party/SAM/models/stylegan2/op/NATIVE_OPS.json",
    }
    paths.update((ROOT / "backend/src/agemorph3d").glob("*.py"))
    paths.update((ROOT / "data/third_party/SAM").rglob("*.py"))
    for manifest in MANIFESTS.values():
        obj = json.loads(manifest.read_bytes())
        for artifact in obj["artifacts"]:
            paths.add(manifest.parent / artifact["path"])
    protected = json.loads(
        (ROOT / "output/research/age-stage6-20261022/preserved-files.json").read_bytes()
    )
    for item in protected["files"]:
        paths.add(ROOT / item["path"])
    pins = [pin(path) for path in sorted(paths)]
    by_path = {item["path"]: item for item in pins}
    if by_path[IMAGE.relative_to(ROOT).as_posix()]["sha256"] != IMAGE_SHA:
        raise ValueError("Frozen development source changed.")
    if by_path[UV.relative_to(ROOT).as_posix()]["sha256"] != UV_SHA:
        raise ValueError("Frozen common UV changed.")
    return pins


async def probe(args) -> int:
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "output/research"):
        raise ValueError("Use a fresh directory under ignored output/research.")
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "status": "running",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "quality_accepted": False,
        "known_source_age_live_reset_verified": False,
        "source_age": {"value": None, "method": "unknown", "calibration_id": None},
        "target_condition": args.target_condition,
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    processor = worker = coordinator = source_cache = source_lease = None
    models, inputs, original_environment = {}, [], None
    try:
        inputs, original_environment = frozen_inputs(), environment()
        historical = json.loads(
            (ROOT / "output/research/age-stage6-20261022/preserved-files.json").read_bytes()
        )
        report["historical_protected_differences"] = [
            {"historical": item, "current": pin(ROOT / item["path"])}
            for item in historical["files"]
            if pin(ROOT / item["path"]) != item
        ]
        write_json(
            output / "freeze.json",
            {
                "inputs": inputs,
                "environment": original_environment,
                "protocol": "research-aging-pipeline-v1",
                "condition": args.target_condition,
                "review_wait_seconds": args.review_wait_seconds,
                "source_age": report["source_age"],
                "historical_protected_differences": report["historical_protected_differences"],
                "ttl_probe": ("Controlled clock offset after registration; not elapsed wall time"),
                "historical_source_seen": True,
                "this_run_output_written_before_freeze": False,
                "same_source_condition_previously_inspected": True,
                "evaluation_split": "development-only; no blind evaluation claim",
            },
        )
        bindings = ResearchBindings(
            *(pin(MANIFESTS[k])["sha256"] for k in ("detector", "reconstructor", "sam")),
            UV_SHA,
        )
        for role in ("detector", "reconstructor"):
            assets = load_verified_manifest(MANIFESTS[role], research_allow_unresolved=True)
            models[role] = _construct_model(role, assets)
        with decode_image(IMAGE.read_bytes(), "image/jpeg", Settings()) as image:
            rgb = np.asarray(image).copy()

        fit_calls = []

        def fit(pixels):
            faces = models["detector"].detect(pixels)
            if len(faces) != 1:
                raise ApiError(
                    422,
                    "NO_FACE" if not faces else "MULTI_FACE",
                    "研究输入必须恰有一张人脸。",
                )
            raw = models["reconstructor"].reconstruct(pixels, faces[0].bbox)
            fit_calls.append({"dimensions": list(pixels.shape), "bbox": list(faces[0].bbox)})
            return raw

        source_raw = await asyncio.to_thread(fit, rgb)
        uv = _npz_arrays(UV, ("uv", "topology_sha256"))
        if str(uv["topology_sha256"].item()) != source_raw.topology_sha256:
            raise ValueError("Common UV topology does not match actual source.")
        source = await asyncio.to_thread(
            prepare_source_context,
            rgb,
            source_raw,
            models["reconstructor"].keypoint_coordinates,
            np.asarray(uv["uv"], dtype=np.float32),
            SourceAge.model_validate(report["source_age"]),
            bindings,
        )
        save(output / "source.glb", source.glb)
        save(output / "source-texture.png", source.texture_png)
        save(output / "source-aligned.png", source.aligned_png)
        save(output / "source-context.json", source.correspondence)
        report["source_fingerprint"] = source_fingerprint(source)
        offset = [0.0]

        def clock():
            return time.monotonic() + offset[0]

        stages = AssetCache(
            max_bytes=32 * 1024**2,
            max_entries=1,
            max_asset_bytes=16 * 1024**2,
            ttl_seconds=300,
            clock=clock,
        )
        source_cache = AgingSessionCache(max_entries=1, ttl_seconds=300, clock=clock)
        identifier = source_cache.publish(source)
        source_lease = source_cache.acquire(identifier)
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
        processor = ResearchAgingProcessor(
            counted, fit, bindings, stage_cache=stages, max_stage_entries=1
        )
        coordinator = AgingCoordinator(source_cache, processor)
        try:
            await coordinator.generate(identifier, args.target_condition)
            raise AssertionError("Unknown absolute age unexpectedly accepted.")
        except ApiError as error:
            assert error.code == "SOURCE_AGE_REQUIRED" and counted.calls == 0
            report["unknown_absolute_age_rejection"] = error.code
        began = time.perf_counter()
        task = asyncio.create_task(processor.stage_condition(source, args.target_condition))
        try:
            await asyncio.wait_for(counted.entered.wait(), 30)
            try:
                await processor.stage_condition(source, 70 if args.target_condition != 70 else 20)
                raise AssertionError("Native admission was released early.")
            except ApiError as error:
                assert error.code == "BUSY"
                report["concurrent_request"] = error.code
            handle = await task
        finally:
            if not task.done():
                await asyncio.gather(task, return_exceptions=True)
        report["stage_seconds"] = time.perf_counter() - began
        assert await processor.stage_condition(source, args.target_condition) == handle
        assert counted.calls == 1 and len(fit_calls) == 2
        report["stage_hit"] = {
            "same_handle": True,
            "sam_calls": counted.calls,
            "target_refits": 1,
        }
        preview = processor.preview_staged(handle)
        save(output / "generated.png", preview.png)
        save(output / "target-fit.json", preview.fit_bytes)
        write_json(
            output / "review-request.json",
            {
                "target": asdict(handle),
                "landmarks_xy": preview.landmarks_xy,
                "review_scope": ("New PNG and target fit only; AI review is not human acceptance"),
                "required_review_file": "review-input.json",
                "masks": "Allowed/occluded local L PNG0/255,1024x1024,disjoint",
            },
        )
        try:
            await processor.register_reviewed(source, handle, None)
            raise AssertionError("Unreviewed target unexpectedly registered.")
        except ApiError as error:
            assert error.code == "REVIEW_REQUIRED"
            report["missing_review_rejection"] = error.code
        print(
            json.dumps(
                {
                    "status": "review_required",
                    "output": str(output),
                    "target": asdict(handle),
                }
            ),
            flush=True,
        )
        deadline = time.monotonic() + args.review_wait_seconds
        review_path = output / "review-input.json"
        while not review_path.exists():
            if time.monotonic() >= deadline:
                raise ApiError(409, "REVIEW_REQUIRED", "等待明确审核记录超时。")
            await asyncio.sleep(0.2)
        if review_path.stat().st_size > 16384:
            raise ValueError("Review record exceeds its byte budget.")
        record = json.loads(review_path.read_bytes())

        def mask(name):
            path = (output / record[name]).resolve(strict=True)
            if path.parent != output or path.stat().st_size > 4 * 1024**2:
                raise ValueError("Masks must be bounded files beside this review.")
            return path.read_bytes()

        review = TargetMaskReview(
            record["source_fingerprint"],
            record["generated_sha256"],
            record["fit_sha256"],
            mask("allowed"),
            mask("occluded"),
            record["reviewer"],
            record["method"],
            record["version"],
            reviewer_kind=record["reviewer_kind"],
        )
        result = await processor.register_reviewed(source, handle, review)
        save(output / "registered.glb", result.result.glb)
        save(output / "registered-texture.png", result.result.texture_png)
        save(output / "registered-provenance.json", result.provenance_json)
        original_doc, original_geometry = geometry(source.glb)
        registered_doc, registered_geometry = geometry(result.result.glb)
        assert original_geometry == registered_geometry
        assert (
            original_doc["extras"]["source_age"]
            == registered_doc["extras"]["source_age"]
            == report["source_age"]
        )
        with Image.open(io.BytesIO(result.result.texture_png)) as texture:
            rgba = np.asarray(texture)
            assert not np.any(rgba[rgba[:, :, 3] == 0])
            known = int(np.count_nonzero(rgba[:, :, 3]))
        assert known > 0 and result.result.shape == source.shape
        report["registration"] = {
            "geometry_accessors": original_geometry,
            "source_geometry_exact": True,
            "shape_exact": True,
            "known_texels": known,
            "unknown_texels": int(rgba.shape[0] * rgba.shape[1] - known),
            "unknown_rgba_zero": True,
            "source_age_unknown": True,
            "result_kind": result.result.kind,
        }
        source_cache.remember(source_lease, args.target_condition, result.result)
        assert source_cache.get_result(source_lease, args.target_condition) is result.result
        try:
            await coordinator.generate(identifier, args.target_condition)
            raise AssertionError("Cached result bypassed unknown source-age guard.")
        except ApiError as error:
            assert error.code == "SOURCE_AGE_REQUIRED" and counted.calls == 1
            report["cached_unknown_absolute_age_rejection"] = error.code
        offset[0] = 301
        source_cache.sweep()
        assert source_cache.stats["pins"] == 1 and source_cache.stats["payload_bytes"] > 0
        report["expired_pinned_source"] = source_cache.stats
        try:
            processor.preview_staged(handle)
            raise AssertionError("Expired stage unexpectedly revived.")
        except ApiError as error:
            assert error.code == "STAGE_EXPIRED"
            report["expired_stage_rejection"] = error.code
        processor.sweep_stages()
        report["clock_probe"] = (
            "Controlled offset+301seconds after actual registration; no claim301wallseconds elapsed"
        )
        report["worker_before_close"] = worker.snapshot()
        report["fit_calls"] = fit_calls
        report["status"] = "passed"
    except Exception as error:  # noqa: BLE001 -- preserve local probe failure evidence
        report.update(
            status="failed",
            error_code=getattr(error, "code", "PROBE_FAILED"),
            error=f"{type(error).__name__}: {error}",
            traceback=traceback.format_exc(),
        )
    finally:
        cleanup_errors = []

        async def checked(label, operation):
            try:
                value = operation()
                return await value if inspect.isawaitable(value) else value
            except Exception as error:  # noqa: BLE001 -- continue all owned cleanup
                cleanup_errors.append(
                    {
                        "operation": label,
                        "error": f"{type(error).__name__}: {error}",
                        "traceback": traceback.format_exc(),
                    }
                )
                return None

        if source_lease is not None:
            await checked("source_lease.close", source_lease.close)
        if processor is not None:
            report["processor_close"] = await checked("processor.close", processor.close)
        if worker is not None:
            await checked("worker.close", worker.close)
        if coordinator is not None:
            await checked("coordinator.close", coordinator.close)
        if source_cache is not None:
            await checked("source_cache.close", source_cache.close)
        for role, model in models.items():
            close = getattr(model, "close", None)
            if close is not None:
                await checked(role + ".close", close)
        report["source_cache_after_close"] = None if source_cache is None else source_cache.stats
        if worker is not None:
            report["worker_after_close"] = worker.snapshot()
            if (
                report["worker_after_close"]["returncode"] != 0
                or sys.platform == "win32"
                and report["worker_after_close"]["worker_exitcode"] != 0
                or report["worker_after_close"]["forced_termination"]
            ):
                cleanup_errors.append(
                    {"operation": "worker.exit", "error": "Normal process exit not confirmed"}
                )
        if processor is not None:

            def check_stage_closed():
                try:
                    stages.publish(b"closed stage storage check")
                    raise AssertionError("Closed stage cache accepted data.")
                except AssetCacheClosed:
                    return True

            report["stage_cache_closed"] = await checked("stage_cache.closed", check_stage_closed)
        verified_inputs = [
            await checked(
                "pin:" + item["path"],
                lambda item=item: pin(ROOT / item["path"]) == item,
            )
            for item in inputs
        ]
        report["inputs_checked"] = len(verified_inputs)
        report["inputs_unchanged"] = bool(inputs) and all(verified_inputs)
        report["environment_unchanged"] = original_environment is not None and await checked(
            "environment", lambda: environment() == original_environment
        )
        report["cleanup_errors"] = cleanup_errors
        if cleanup_errors or not report["inputs_unchanged"] or not report["environment_unchanged"]:
            report["status"] = "failed"
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        write_json(output / "report.json", report)
    print(json.dumps({"status": report["status"], "output": str(output)}), flush=True)
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-condition", type=int, choices=range(20, 71), required=True)
    parser.add_argument("--review-wait-seconds", type=int, choices=range(30, 181), default=180)
    return asyncio.run(probe(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
