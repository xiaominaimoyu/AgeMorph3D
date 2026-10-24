"""Synthetic pipeline wiring/lifecycles; no real SAM inference or quality evidence."""

import asyncio
import hashlib
import io
import json
import shutil
import struct
import sys
import threading
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import numpy as np
import pytest
from agemorph3d import research_aging_pipeline as pipeline
from agemorph3d.aging_sessions import AgingCoordinator, AgingSessionCache, SessionCapacityError
from agemorph3d.asset_cache import AssetCache, AssetCacheClosed, AssetCapacityError
from agemorph3d.errors import ApiError
from agemorph3d.sam_worker import SamGeneration, SamWorkerClient
from agemorph3d.tddfa import TddfaResult
from PIL import Image

UNKNOWN = {"value": None, "method": "unknown", "calibration_id": None}
KNOWN = {"value": 42.5, "method": "user", "calibration_id": None}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def png(array):
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, "PNG")
    return stream.getvalue()


def face_points():
    points = np.full((68, 2), [100.0, 90.0])
    contour = np.array([[-4, 0], [-2, -2], [2, -2], [4, 0], [2, 2], [-2, 2]])
    points[36:42] = contour + [80, 80]
    points[42:48] = contour + [120, 80]
    points[48], points[54] = [85, 120], [115, 120]
    return points


def topology(vertices, triangles, keypoints):
    result = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for value in (
        np.array([len(vertices), len(triangles)], dtype="<i8"),
        triangles.astype("<i8"),
        keypoints.astype("<i8"),
    ):
        result.update(value.tobytes())
    return result.hexdigest()


@pytest.fixture
def bindings():
    return pipeline.ResearchBindings(*(sha(b"synthetic-manifest-" + bytes([i])) for i in range(4)))


@pytest.fixture
def source_fixture(bindings):
    # All68 addresses really project to valid FFHQ landmarks; every vertex has a normal.
    xy = np.vstack((face_points(), [[10, 190], [190, 190]]))
    vertices = np.column_stack((xy[:, 0] + 1, 120 - xy[:, 1], np.zeros(70))).astype(np.float32)
    triangles = np.array([[68, i, 69] for i in range(68)], dtype=np.int64)
    keypoints = np.arange(204, dtype=np.int64).reshape(68, 3)
    raw = TddfaResult(
        np.zeros(40, np.float32),
        np.zeros(10, np.float32),
        vertices,
        triangles,
        np.eye(3, 4, dtype=np.float32),
        (0.0, 0.0, 120.0, 120.0),
        topology(vertices, triangles, keypoints),
    )
    yy, xx = np.mgrid[:200, :200]
    rgb = np.stack((xx, yy, np.full_like(xx, 37)), axis=-1).astype(np.uint8)
    uv = np.column_stack((xy[:, 0] / 200, 1 - xy[:, 1] / 200)).astype(np.float32)
    source = pipeline.prepare_source_context(rgb, raw, keypoints, uv, KNOWN, bindings)
    return source, rgb, raw, keypoints, uv


@pytest.fixture
def color_fixture(monkeypatch, bindings):
    # Explicitly isolate the68-landmark bridge for this three-point UV color oracle.
    # The separate70-vertex fixture above exercises real projection and FFHQ geometry.
    real_project = pipeline.project_vertices

    def landmark_bridge(raw, coordinates=None):
        return (
            np.column_stack((face_points(), np.zeros(68)))
            if coordinates is not None
            else real_project(raw)
        )

    monkeypatch.setattr(pipeline, "project_vertices", landmark_bridge)
    vertices = np.array([[2, 115, 0], [10, 115, 0], [2, 107, 0]], dtype=np.float32)
    triangles = np.array([[0, 1, 2]], dtype=np.int64)
    keypoints = np.tile(np.arange(3, dtype=np.int64), (68, 1))
    raw = TddfaResult(
        np.zeros(40, np.float32),
        np.zeros(10, np.float32),
        vertices,
        triangles,
        np.eye(3, 4, dtype=np.float32),
        (0.0, 0.0, 120.0, 120.0),
        topology(vertices, triangles, keypoints),
    )
    yy, xx = np.mgrid[:200, :200]
    rgb = np.stack((xx, yy, np.full_like(xx, 37)), axis=-1).astype(np.uint8)
    uv = np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float32)
    source = pipeline.prepare_source_context(rgb, raw, keypoints, uv, KNOWN, bindings)
    return source, raw


class TinyWorker:
    """Protocol-shaped synthetic worker with independently owned pending work."""

    def __init__(self, bindings, *, blocked=False):
        yy, xx = np.mgrid[:1024, :1024]
        self.png = png(
            np.stack((xx * 10 % 256, yy * 10 % 256, (xx * 3 + yy) % 256), axis=-1).astype(np.uint8)
        )
        self.bindings, self.calls, self.waits = bindings, [], 0
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        if not blocked:
            self.release.set()
        self.pending, self.closed = None, False

    @property
    def busy(self):
        return self.pending is not None and not self.pending.done()

    async def generate(self, data, age):
        self.calls.append((data, age))
        self.entered.set()

        async def run():
            await self.release.wait()
            return SamGeneration(
                self.png,
                sha(self.png),
                sha(data),
                age,
                123,
                1,
                0.01,
                0,
                {
                    "pid": 123,
                    "load_count": 1,
                    "research_only": True,
                    "service_ready": False,
                    "pins": {"manifest_sha256": self.bindings.sam_manifest_sha256},
                },
            )

        self.pending = asyncio.create_task(run())
        return await asyncio.shield(self.pending)

    async def wait_idle(self):
        self.waits += 1
        cancelled = False
        while self.pending is not None and not self.pending.done():
            try:
                await asyncio.shield(self.pending)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def close(self):
        await self.wait_idle()
        self.closed = True
        return {"closed": True, "returncode": 0}


def review_for(preview, *, allowed=None):
    with Image.open(io.BytesIO(preview.png)) as image:
        width, height = image.size
    allowed = np.ones((height, width), dtype=bool) if allowed is None else allowed
    return pipeline.TargetMaskReview(
        preview.target.source_fingerprint,
        preview.target.generated_sha256,
        preview.target.fit_sha256,
        png(allowed.astype(np.uint8) * 255),
        png(np.zeros((height, width), dtype=np.uint8)),
        "synthetic-reviewer",
        "synthetic explicit mask",
        "v1",
    )


def glb_geometry(raw):
    length, kind = struct.unpack_from("<I4s", raw, 12)
    assert kind == b"JSON"
    doc = json.loads(raw[20 : 20 + length])
    binary = raw[28 + length :]
    result = {}
    primitive = doc["meshes"][0]["primitives"][0]
    for name, index in {**primitive["attributes"], "indices": primitive["indices"]}.items():
        ac = doc["accessors"][index]
        bv = doc["bufferViews"][ac["bufferView"]]
        start = bv.get("byteOffset", 0) + ac.get("byteOffset", 0)
        count = ac["count"] * {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[ac["type"]]
        result[name] = binary[start : start + count * 4]
    return doc, result


async def eventually(predicate):
    loop, ready, handle = asyncio.get_running_loop(), asyncio.Event(), None

    def check():
        nonlocal handle
        if predicate():
            ready.set()
        else:
            handle = loop.call_later(0.001, check)

    check()
    try:
        await asyncio.wait_for(ready.wait(), 3)
    finally:
        if handle is not None:
            handle.cancel()


def test_source_builder_uses_real68_projection_ffhq_and_immutable_valid_bytes(source_fixture):
    source, rgb, raw, keypoints, _ = source_fixture
    assert source.source_age.model_dump() == KNOWN and source.shape == tuple(raw.shape)
    with Image.open(io.BytesIO(source.aligned_png)) as image:
        assert image.mode == "RGB" and image.size == (256, 256)
    document, geometry = glb_geometry(source.glb)
    assert len(geometry["POSITION"]) == 70 * 3 * 4
    assert document["extras"]["source_age"] == KNOWN
    assert document["extras"]["asset_mode"] == "static"
    assert json.loads(source.correspondence)
    assert pipeline.source_fingerprint(source) == pipeline.source_fingerprint(source)
    with pytest.raises(FrozenInstanceError):
        source.glb = b"mutation"
    np.testing.assert_array_equal(pipeline.project_vertices(raw, keypoints)[:, :2], face_points())
    assert rgb.dtype == np.uint8


async def test_staging_is_opaque_cached_and_does_not_automatically_register(
    color_fixture, bindings
):
    source, raw = color_fixture
    worker = TinyWorker(bindings)
    processor = pipeline.ResearchAgingProcessor(worker, lambda rgb: raw, bindings)
    try:
        first = await processor.stage_condition(source, 20)
        assert await processor.stage_condition(source, 20) == first
        assert len(worker.calls) == 1 and worker.waits >= 1
        assert {field.name for field in fields(first)} == {
            "stage_id",
            "source_fingerprint",
            "target_condition",
            "generated_sha256",
            "fit_sha256",
        }
        preview = processor.preview_staged(first)
        assert preview.target == first and sha(preview.png) == first.generated_sha256
        assert sha(preview.fit_bytes) == first.fit_sha256
        assert first.source_fingerprint == pipeline.source_fingerprint(source)
    finally:
        await processor.close()


async def test_target_own_projection_changes_known_rgb_but_source_glb_geometry_stays_exact(
    color_fixture, bindings
):
    source, raw = color_fixture
    worker, fit_calls = TinyWorker(bindings), []

    def fit(rgb):
        fit_calls.append(rgb.copy())
        projection = raw.projection.copy()
        projection[0, 3] = 0 if len(fit_calls) == 1 else 2
        return replace(raw, projection=projection, shape=np.ones(40, np.float32) * 5)

    processor = pipeline.ResearchAgingProcessor(worker, fit, bindings)
    try:
        results = []
        for age in (20, 70):
            handle = await processor.stage_condition(source, age)
            preview = processor.preview_staged(handle)
            registered = await processor.register_reviewed(source, handle, review_for(preview))
            results.append(registered.result)
            assert (
                registered.result.kind == "sam_registered_uv"
                and registered.result.shape == source.shape
            )
            assert glb_geometry(registered.result.glb)[1] == glb_geometry(source.glb)[1]
        rgba = [np.asarray(Image.open(io.BytesIO(result.texture_png))) for result in results]
        # At256² UV center(.5/256,.5/256): target XY(1.015625,5.015625), then x+2.
        np.testing.assert_array_equal(rgba[0][0, 0], [10, 50, 8, 255])
        np.testing.assert_array_equal(rgba[1][0, 0], [30, 50, 14, 255])
        assert all(np.array_equal(rgb, fit_calls[0]) for rgb in fit_calls)
        assert [age for _, age in worker.calls] == [20, 70]
    finally:
        await processor.close()


async def test_no_review_returns_same_staged_target_without_regenerating(color_fixture, bindings):
    source, raw = color_fixture
    worker = TinyWorker(bindings)
    processor = pipeline.ResearchAgingProcessor(worker, lambda rgb: raw, bindings)
    try:
        staged = []
        for _ in range(2):
            with pytest.raises(ApiError) as caught:
                await processor(source, 20)
            assert caught.value.code == "REVIEW_REQUIRED"
            staged.append(caught.value.staged)
        assert staged[0] == staged[1] and len(worker.calls) == 1
        preview = processor.preview_staged(staged[0])
        assert (
            await processor.register_reviewed(source, staged[0], review_for(preview))
        ).result.kind == "sam_registered_uv"
    finally:
        await processor.close()


@pytest.mark.parametrize("field", ["source_fingerprint", "generated_sha256", "fit_sha256"])
async def test_review_binding_mismatch_never_registers_or_generates_again(
    color_fixture, bindings, field
):
    source, raw = color_fixture
    worker = TinyWorker(bindings)
    processor = pipeline.ResearchAgingProcessor(worker, lambda rgb: raw, bindings)
    try:
        handle = await processor.stage_condition(source, 20)
        review = replace(review_for(processor.preview_staged(handle)), **{field: "f" * 64})
        with pytest.raises(ApiError) as caught:
            await processor.register_reviewed(source, handle, review)
        assert caught.value.code == "REVIEW_REQUIRED" and len(worker.calls) == 1
    finally:
        await processor.close()


@pytest.mark.parametrize("problem", ["shape", "nonbinary", "overlap", "rgb_mode"])
async def test_review_masks_require_exact_target_frame_and_disjoint_binary_pixels(
    color_fixture, bindings, problem
):
    source, raw = color_fixture
    worker = TinyWorker(bindings)
    processor = pipeline.ResearchAgingProcessor(worker, lambda rgb: raw, bindings)
    try:
        handle = await processor.stage_condition(source, 20)
        review = review_for(processor.preview_staged(handle))
        if problem == "shape":
            review = replace(review, allowed_png=png(np.ones((32, 32), dtype=np.uint8) * 255))
        elif problem == "nonbinary":
            review = replace(review, allowed_png=png(np.ones((1024, 1024), dtype=np.uint8) * 128))
        elif problem == "overlap":
            review = replace(review, occluded_png=review.allowed_png)
        else:
            review = replace(
                review, allowed_png=png(np.ones((1024, 1024, 3), dtype=np.uint8) * 255)
            )
        with pytest.raises(ApiError) as caught:
            await processor.register_reviewed(source, handle, review)
        assert caught.value.code == "REVIEW_REQUIRED" and len(worker.calls) == 1
    finally:
        await processor.close()


@pytest.mark.parametrize(
    "problem", ["output_sha", "input_sha", "manifest", "condition", "load_count"]
)
async def test_unbound_worker_generation_is_rejected_before_target_refit(
    color_fixture, bindings, problem
):
    source, _ = color_fixture

    class BadWorker(TinyWorker):
        async def generate(self, data, age):
            result = await super().generate(data, age)
            if problem == "output_sha":
                return replace(result, sha256="f" * 64)
            if problem == "input_sha":
                return replace(result, input_sha256="f" * 64)
            if problem == "manifest":
                return replace(
                    result, provenance={**result.provenance, "pins": {"manifest_sha256": "f" * 64}}
                )
            if problem == "condition":
                return replace(result, target_age=70)
            return replace(result, load_count=2)

    worker = BadWorker(bindings)

    def forbidden(rgb):
        pytest.fail("Unverified generated evidence cannot reach refitting")

    processor = pipeline.ResearchAgingProcessor(worker, forbidden, bindings)
    try:
        with pytest.raises(ApiError):
            await processor.stage_condition(source, 20)
        assert worker.waits >= 1
    finally:
        await processor.close()


@pytest.mark.parametrize("field", ["original_rgb", "glb", "correspondence"])
async def test_source_payload_tampering_is_rejected_before_worker(color_fixture, bindings, field):
    source, raw = color_fixture
    worker = TinyWorker(bindings)
    processor = pipeline.ResearchAgingProcessor(worker, lambda rgb: raw, bindings)
    try:
        changed = replace(source, **{field: b'{"unbound":"source payload"}'})
        with pytest.raises(ApiError):
            await processor.stage_condition(changed, 20)
        assert not worker.calls
    finally:
        await processor.close()


async def test_changed_model_binding_cannot_reuse_an_existing_source_context(
    color_fixture, bindings
):
    source, raw = color_fixture
    other = replace(bindings, reconstructor_manifest_sha256="f" * 64)
    worker = TinyWorker(other)
    processor = pipeline.ResearchAgingProcessor(worker, lambda rgb: raw, other)
    try:
        with pytest.raises(ApiError):
            await processor.stage_condition(source, 20)
        assert not worker.calls
    finally:
        await processor.close()


async def test_fractional_source_reset_bypasses_worker_refitter_and_review(
    source_fixture, bindings
):
    source, *_ = source_fixture
    worker = TinyWorker(bindings)

    def forbidden(*args):
        pytest.fail("Exact source reset cannot call model/refit/review")

    processor = pipeline.ResearchAgingProcessor(worker, forbidden, bindings, forbidden)
    try:
        result = await processor(source, 42.5)
        assert (
            result.kind == "source_reset"
            and result.glb is source.glb
            and result.texture_png is source.texture_png
        )
        assert not worker.calls
        with pytest.raises(ApiError) as caught:
            await processor(source, 42.6)
        assert caught.value.code == "INTEGER_AGE_REQUIRED" and not worker.calls
    finally:
        await processor.close()


async def test_unknown_source_allows_condition_staging_but_never_defaults_absolute_age(
    source_fixture, bindings
):
    _, rgb, raw, keypoints, uv = source_fixture
    source = pipeline.prepare_source_context(rgb, raw, keypoints, uv, UNKNOWN, bindings)
    worker = TinyWorker(bindings)
    processor = pipeline.ResearchAgingProcessor(worker, lambda rgb: raw, bindings)
    try:
        handle = await processor.stage_condition(source, 20)
        assert source.source_age.model_dump() == UNKNOWN
        with pytest.raises(ApiError) as caught:
            await processor(source, 20)
        assert caught.value.code == "SOURCE_AGE_REQUIRED" and len(worker.calls) == 1
        assert processor.preview_staged(handle).target == handle
        preview = processor.preview_staged(handle)
        registered = await processor.register_reviewed(source, handle, review_for(preview))
        assert glb_geometry(registered.result.glb)[0]["extras"]["source_age"] == UNKNOWN
        cache = AgingSessionCache()
        identifier = cache.publish(source)
        coordinator = AgingCoordinator(cache, processor)
        try:
            with pytest.raises(ApiError) as caught:
                await coordinator.generate(identifier, 20)
            assert caught.value.code == "SOURCE_AGE_REQUIRED"
            assert cache.stats["results"] == cache.stats["pins"] == 0 and len(worker.calls) == 1
        finally:
            await coordinator.close()
    finally:
        await processor.close()


async def test_stage_ttl_is_absolute_and_expired_handle_cannot_revive_payload(
    color_fixture, bindings
):
    source, raw = color_fixture
    now = [0.0]
    cache = AssetCache(ttl_seconds=1, max_entries=1, clock=lambda: now[0])
    worker = TinyWorker(bindings)
    processor = pipeline.ResearchAgingProcessor(
        worker, lambda rgb: raw, bindings, stage_cache=cache
    )
    try:
        old = await processor.stage_condition(source, 20)
        now[0] = 0.9
        assert processor.preview_staged(old).target == old
        now[0] = 1.0
        with pytest.raises(ApiError):
            processor.preview_staged(old)
        fresh = await processor.stage_condition(source, 20)
        assert fresh.stage_id != old.stage_id and len(worker.calls) == 2
    finally:
        await processor.close()
    assert worker.closed
    with pytest.raises(AssetCacheClosed):
        cache.publish(b"cannot publish after processor close")


async def test_cancelled_staging_waits_for_underlying_sam_before_releasing_admission(
    color_fixture, bindings
):
    source, raw = color_fixture
    worker = TinyWorker(bindings, blocked=True)
    processor = pipeline.ResearchAgingProcessor(worker, lambda rgb: raw, bindings)
    work = asyncio.create_task(processor.stage_condition(source, 20))
    await worker.entered.wait()
    work.cancel()
    await asyncio.sleep(0)
    try:
        assert worker.busy and not work.done()
        with pytest.raises(ApiError) as caught:
            await processor.stage_condition(source, 70)
        assert caught.value.code == "BUSY"
        worker.release.set()
        with pytest.raises(asyncio.CancelledError):
            await work
        assert worker.waits >= 1 and not worker.busy
    finally:
        worker.release.set()
        await asyncio.gather(work, return_exceptions=True)
        await processor.close()


async def test_coordinator_cancellation_keeps_source_pin_through_native_refit(
    color_fixture, bindings
):
    source, raw = color_fixture
    worker = TinyWorker(bindings)
    entered, release = threading.Event(), threading.Event()

    def fit(rgb):
        entered.set()
        assert release.wait(3), "test failed to release synthetic refit thread"
        return raw

    processor = pipeline.ResearchAgingProcessor(worker, fit, bindings, review_for)
    cache = AgingSessionCache(max_entries=1)
    identifier = cache.publish(source)
    coordinator = AgingCoordinator(cache, processor)
    work = asyncio.create_task(coordinator.generate(identifier, 20))
    assert await asyncio.to_thread(entered.wait, 2)
    work.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await work
        assert not worker.busy and cache.stats["pins"] == 1 and cache.stats["results"] == 0
        with pytest.raises(ApiError) as caught:
            await coordinator.generate(identifier, 70)
        assert caught.value.code == "BUSY"
        with pytest.raises(ApiError) as caught:
            await processor.stage_condition(source, 70)
        assert caught.value.code == "BUSY"
        release.set()
        await eventually(lambda: cache.stats["pins"] == 0)
        assert cache.stats["results"] == 0
    finally:
        release.set()
        await coordinator.close()
        await processor.close()


@pytest.mark.parametrize("late", ["ttl", "close"])
async def test_registration_native_completion_cannot_publish_after_stage_expiry_or_close(
    color_fixture, bindings, monkeypatch, late
):
    source, raw = color_fixture
    now = [0.0]
    cache = AssetCache(ttl_seconds=1, max_entries=1, clock=lambda: now[0])
    worker = TinyWorker(bindings)
    processor = pipeline.ResearchAgingProcessor(
        worker, lambda rgb: raw, bindings, stage_cache=cache
    )
    handle = await processor.stage_condition(source, 20)
    review = review_for(processor.preview_staged(handle))
    entered, release = threading.Event(), threading.Event()
    real_register = pipeline.register_generated_texture

    def register(*args, **kwargs):
        entered.set()
        assert release.wait(3), "test failed to release synthetic registration thread"
        return real_register(*args, **kwargs)

    monkeypatch.setattr(pipeline, "register_generated_texture", register)
    registering = asyncio.create_task(processor.register_reviewed(source, handle, review))
    assert await asyncio.to_thread(entered.wait, 2)
    closing = None
    try:
        if late == "ttl":
            now[0] = 2.0
            with pytest.raises(AssetCapacityError):
                cache.publish(b"still charged while native registration holds its lease")
        else:
            closing = asyncio.create_task(processor.close())
            await asyncio.sleep(0)
            assert not closing.done()
        release.set()
        with pytest.raises(ApiError):
            await registering
        if closing is not None:
            await closing
        else:
            assert cache.publish(b"released after expired native registration")
    finally:
        release.set()
        await asyncio.gather(registering, return_exceptions=True)
        if closing is not None:
            await closing
        await processor.close()


async def test_actual_synthetic_stdio_timeout_drains_before_coordinator_releases_pin(
    source_fixture, bindings, tmp_path, monkeypatch
):
    import agemorph3d.sam_worker as worker_module

    source, *_ = source_fixture
    monkeypatch.setattr(worker_module, "_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(worker_module, "_DEVICE_LOCK_PATH", tmp_path / "synthetic-device.lock")
    script = tmp_path / "synthetic_sam_worker.py"
    shutil.copyfile(Path(__file__).parent / "fixtures/synthetic_sam_worker.py", script)
    (tmp_path / "fake-sam-config.json").write_text(
        json.dumps({"generate_delay": 0.25}), encoding="utf-8"
    )
    worker = SamWorkerClient(
        python_executable=sys.executable,
        worker_script=script,
        manifest_path=tmp_path / "manifest.json",
        sam_root=tmp_path,
        research_allow_unresolved=True,
        startup_timeout_s=3,
        request_timeout_s=0.01,
        shutdown_timeout_s=1,
    )

    def forbidden(rgb):
        pytest.fail("Timed out worker output cannot reach target refitting")

    processor = pipeline.ResearchAgingProcessor(worker, forbidden, bindings)
    now = [0.0]
    cache = AgingSessionCache(max_entries=1, ttl_seconds=1, clock=lambda: now[0])
    identifier = cache.publish(source)
    coordinator = AgingCoordinator(cache, processor)
    try:
        await worker.start()
        with pytest.raises(ApiError) as caught:
            await coordinator.generate(identifier, 20, timeout_seconds=0.04)
        assert caught.value.code == "TIMEOUT"
        assert worker.busy and cache.stats["pins"] == 1 and cache.stats["results"] == 0
        now[0] = 2
        with pytest.raises(SessionCapacityError):
            cache.publish(source)
        await coordinator.close()
        assert cache.stats["payload_bytes"] == cache.stats["pins"] == 0
        # The persistent child/device lease survives idle until its actual close.
        assert worker.snapshot()["returncode"] is None
        await processor.close()
        assert worker.snapshot()["returncode"] == 0 and worker.snapshot()["closed"]
    finally:
        await coordinator.close()
        await processor.close()
