"""Private, bounded SAM-condition staging and reviewed UV registration.

The caller verifies/owns reconstruction models and their licences. This module
loads no model or file and grants no production capability. A SAM integer
condition can be studied with unknown source age; the coordinator adapter still
requires known source age. Shapes always use the original static source mesh.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import math
import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
from PIL import Image

from .aging_sessions import SessionResult, SessionSource
from .asset_cache import AssetCache, AssetCacheClosed, AssetCapacityError, AssetNotFound
from .errors import ApiError
from .ffhq_alignment import align_ffhq
from .sam_worker import SamGeneration, SamWorkerError
from .schemas import SourceAge
from .static_mesh import build_static_mesh
from .target_uv import register_generated_texture
from .tddfa import TddfaResult, project_vertices
from .uv_texture import project_photo_texture

CONTEXT_VERSION = "agemorph3d-research-source-v1"
STAGE_VERSION = "agemorph3d-research-stage-v1"
MAX_CONTEXT_BYTES = 32 * 1024**2
MAX_STAGE_BYTES = 16 * 1024**2
MAX_SOURCE_BYTES = 128 * 1024**2
MAX_PNG_BYTES = 4 * 1024**2
MAX_SOURCE_PNG_BYTES = 48 * 1024**2
_META_BYTES = 64 * 1024
_SHA = re.compile(r"[0-9a-f]{64}")
_STAGE_ID = re.compile(r"[0-9a-f]{32}")
_CLOSED_FLAGS = {
    "research_only": True,
    "service_ready": False,
    "production_enabled": False,
    "g3_complete": False,
    "age_quality_accepted": False,
    "identity_quality_accepted": False,
    "visual_seam_quality_accepted": False,
    "years_calibrated": False,
    "human_review_completed": False,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError("A complete lowercase SHA-256 is required.")
    return value


def _condition(value: object) -> int:
    if type(value) is not int or not 20 <= value <= 70:
        raise ApiError(422, "INTEGER_AGE_REQUIRED", "研究生成条件必须为20—70的整数。")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("Bounded nonempty review provenance is required.")
    return value


def _json(data: bytes, limit: int) -> dict:
    if type(data) is not bytes or not 0 < len(data) <= limit:
        raise ValueError("Serialized context exceeds its byte budget.")

    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("Duplicate context key.")
            result[name] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite JSON is forbidden.")

    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid serialized context.") from error
    if not isinstance(value, dict):
        raise ValueError("A context object is required.")
    return value


def _encode(value: dict, limit: int) -> bytes:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if not 0 < len(data) <= limit:
        raise ValueError("Serialized context exceeds its byte budget.")
    return data


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _bytes(value: object, limit: int, exact: int | None = None) -> bytes:
    budget = exact if exact is not None else limit
    if (
        not isinstance(value, str)
        or len(value) > 4 * ((budget + 2) // 3)
        or exact is not None and len(value) != 4 * ((exact + 2) // 3)
    ):
        raise ValueError("Encoded payload exceeds its declared byte budget.")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeError) as error:
        raise ValueError("Invalid encoded payload.") from error
    if len(data) > limit or exact is not None and len(data) != exact or _b64(data) != value:
        raise ValueError("Encoded payload has inconsistent length or encoding.")
    return data


def _array(value: np.ndarray, dtype: str, shape: tuple[int, ...]) -> dict:
    value = np.asarray(value)
    if value.dtype != np.dtype(dtype) or value.shape != shape or not np.isfinite(value).all():
        raise ValueError("Context array shape, dtype or finite values differ.")
    return {"dtype": dtype, "shape": list(shape), "data": _b64(value.tobytes(order="C"))}


def _read_array(value: dict, dtype: str, shape: tuple[int, ...]) -> np.ndarray:
    if (
        not isinstance(value, dict)
        or set(value) != {"dtype", "shape", "data"}
        or value["dtype"] != dtype
        or value["shape"] != list(shape)
        or any(type(n) is not int or n < 0 for n in value["shape"])
    ):
        raise ValueError("Context array schema differs.")
    size = math.prod(shape) * np.dtype(dtype).itemsize
    if size > 16 * 1024**2:
        raise ValueError("Context array exceeds its allocation budget.")
    data = _bytes(value["data"], size, size)
    array = np.frombuffer(data, dtype=dtype).reshape(shape)
    if not np.isfinite(array).all():
        raise ValueError("Context arrays must remain finite.")
    return array


def _png(array: np.ndarray) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format="PNG")
    return stream.getvalue()


def _image(data: bytes, mode: str, size=None, *, source=False) -> np.ndarray:
    limit = MAX_SOURCE_PNG_BYTES if source else MAX_PNG_BYTES
    if type(data) is not bytes or not 0 < len(data) <= limit:
        raise ValueError("PNG exceeds its byte budget.")
    with Image.open(io.BytesIO(data)) as image:
        if (
            image.format != "PNG"
            or image.mode != mode
            or getattr(image, "n_frames", 1) != 1
            or min(image.size) < 2
            or image.width * image.height > (16_000_000 if source else 1024**2)
            or size is not None and image.size != size
        ):
            raise ValueError("PNG mode or pixel frame differs.")
        return np.asarray(image).copy()


@dataclass(frozen=True)
class ResearchBindings:
    detector_manifest_sha256: str
    reconstructor_manifest_sha256: str
    sam_manifest_sha256: str
    common_uv_asset_sha256: str

    def __post_init__(self):
        for value in asdict(self).values():
            _digest(value)


def _fit_object(raw: TddfaResult) -> dict:
    if not isinstance(raw, TddfaResult) or raw.coordinate_system != "bfm_model_raw":
        raise ValueError("Raw BFM coordinate geometry is required.")
    n, m = len(raw.vertices), len(raw.triangles)
    if not 3 <= n <= 200_000 or not 1 <= m <= 300_000:
        raise ValueError("Raw geometry exceeds its work budget.")
    arrays = {
        "shape": _array(raw.shape, "<f4", (40,)),
        "expr": _array(raw.expr, "<f4", (10,)),
        "vertices": _array(raw.vertices, "<f4", (n, 3)),
        "triangles": _array(raw.triangles, "<i8", (m, 3)),
        "projection": _array(raw.projection, "<f4", (3, 4)),
        "roi": _array(np.asarray(raw.roi, dtype="<f8"), "<f8", (4,)),
    }
    if (
        np.any(raw.triangles < 0)
        or np.any(raw.triangles >= n)
        or np.any(np.diff(np.sort(raw.triangles, axis=1), axis=1) == 0)
        or raw.roi[2] <= raw.roi[0]
        or raw.roi[3] <= raw.roi[1]
    ):
        raise ValueError("Raw topology or ROI is invalid.")
    return {"version": "agemorph3d-research-fit-v1", "n": n, "m": m,
            "topology_sha256": _digest(raw.topology_sha256), "arrays": arrays}


def _read_fit(value: dict) -> TddfaResult:
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "n", "m", "topology_sha256", "arrays"}
        or value["version"] != "agemorph3d-research-fit-v1"
        or type(value["n"]) is not int
        or type(value["m"]) is not int
        or not 3 <= value["n"] <= 200_000
        or not 1 <= value["m"] <= 300_000
    ):
        raise ValueError("Raw fit schema or dimensions differ.")
    n, m, arrays = value["n"], value["m"], value["arrays"]
    if not isinstance(arrays, dict) or set(arrays) != {"shape", "expr", "vertices", "triangles", "projection", "roi"}:
        raise ValueError("Raw fit array names differ.")
    raw = TddfaResult(
        _read_array(arrays["shape"], "<f4", (40,)),
        _read_array(arrays["expr"], "<f4", (10,)),
        _read_array(arrays["vertices"], "<f4", (n, 3)),
        _read_array(arrays["triangles"], "<i8", (m, 3)),
        _read_array(arrays["projection"], "<f4", (3, 4)),
        tuple(_read_array(arrays["roi"], "<f8", (4,)).tolist()),
        _digest(value["topology_sha256"]),
    )
    _fit_object(raw)
    return raw


def fit_fingerprint(raw: TddfaResult) -> str:
    """Versioned canonical fit bytes, independent of NPZ compression/timestamps."""
    return _sha(_encode(_fit_object(raw), MAX_CONTEXT_BYTES))


def source_fingerprint(source: SessionSource) -> str:
    if not isinstance(source, SessionSource) or source.payload_bytes > MAX_SOURCE_BYTES:
        raise ValueError("A bounded immutable source is required.")
    digest = hashlib.sha256(b"agemorph3d:research-source:v1\0")
    for data in (source.source_age_json, source.original_rgb, source.aligned_png, source.correspondence,
                 source.glb, source.texture_png, np.asarray(source.shape, dtype="<f8").tobytes()):
        digest.update(len(data).to_bytes(8, "little"))
        digest.update(data)
    return digest.hexdigest()


def _topology(raw: TddfaResult, keypoints: np.ndarray) -> None:
    if keypoints.dtype != np.int64 or keypoints.shape != (68, 3) or np.any(keypoints < 0) or np.any(keypoints >= 3 * len(raw.vertices)):
        raise ValueError("Keypoints must be68 ordered triples of coordinate addresses.")
    digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for array in (np.array([len(raw.vertices), len(raw.triangles)], dtype="<i8"),
                  raw.triangles.astype("<i8"), keypoints.astype("<i8")):
        digest.update(array.tobytes(order="C"))
    if digest.hexdigest() != raw.topology_sha256:
        raise ValueError("Raw topology and keypoint order differ from topology-v2 identity.")


def prepare_source_context(rgb, raw, keypoint_coordinates, common_uv, source_age, bindings) -> SessionSource:
    """Build original RGB/FFHQ/fit/source-canonical assets without model or file IO."""
    if not isinstance(bindings, ResearchBindings) or not isinstance(source_age, SourceAge):
        raise ValueError("Explicit model bindings and validated source-age provenance are required.")
    rgb, keypoints, uv = np.asarray(rgb), np.asarray(keypoint_coordinates), np.asarray(common_uv)
    _fit_object(raw)
    _topology(raw, keypoints)
    if uv.dtype != np.float32 or uv.shape != (len(raw.vertices), 2) or not np.isfinite(uv).all() or np.any(uv < 0) or np.any(uv > 1):
        raise ValueError("Source UV must bind the complete ordered source topology.")
    alignment = align_ffhq(rgb, project_vertices(raw, keypoints))
    original, aligned = _png(rgb), _png(alignment.rgb)
    _image(original, "RGB", source=True)
    _image(aligned, "RGB", (256, 256))
    texture = project_photo_texture(rgb, raw, uv)
    mesh = build_static_mesh(raw, source_age.model_dump(), texture=texture)
    metadata = {
        "version": CONTEXT_VERSION, "bindings": asdict(bindings), "raw": _fit_object(raw),
        "keypoints": _array(keypoints, "<i8", (68, 3)), "uv": _array(uv, "<f4", (len(raw.vertices), 2)),
        "alignment": {"source_to_aligned": _array(alignment.source_to_aligned, "<f8", (3, 3)),
            "aligned_to_source": _array(alignment.aligned_to_source, "<f8", (3, 3)),
            "source_quad": _array(alignment.source_quad, "<f8", (4, 2)),
            "valid_mask": _array(alignment.valid_mask.astype(np.uint8), "|u1", (256, 256)),
            "metadata": alignment.metadata},
        "source_age": source_age.model_dump(mode="json"), "original_sha256": _sha(original),
        "aligned_sha256": _sha(aligned), "glb_sha256": _sha(mesh.glb), "texture_sha256": _sha(texture.png),
        "uv_array_sha256": _sha(uv.tobytes(order="C")), **_CLOSED_FLAGS,
    }
    result = SessionSource(source_age.model_dump_json().encode(), original, aligned,
        _encode(metadata, MAX_CONTEXT_BYTES), mesh.glb, texture.png, tuple(float(x) for x in raw.shape))
    source_fingerprint(result)
    return result


def _load_source(source: SessionSource, bindings: ResearchBindings):
    fingerprint = source_fingerprint(source)
    meta = _json(source.correspondence, MAX_CONTEXT_BYTES)
    if meta.get("version") != CONTEXT_VERSION or meta.get("bindings") != asdict(bindings):
        raise ValueError("Source version or model/UV binding changed.")
    if any(meta.get(name) is not expected for name, expected in _CLOSED_FLAGS.items()):
        raise ValueError("Research context cannot grant capabilities.")
    if meta["source_age"] != source.source_age.model_dump(mode="json"):
        raise ValueError("Source age was reassigned.")
    for name, data in (("original", source.original_rgb), ("aligned", source.aligned_png),
                       ("glb", source.glb), ("texture", source.texture_png)):
        if _digest(meta[name + "_sha256"]) != _sha(data):
            raise ValueError("Source payload integrity changed.")
    raw = _read_fit(meta["raw"])
    keypoints = _read_array(meta["keypoints"], "<i8", (68, 3))
    _topology(raw, keypoints)
    uv = _read_array(meta["uv"], "<f4", (len(raw.vertices), 2))
    if np.any(uv < 0) or np.any(uv > 1) or _sha(uv.tobytes()) != meta["uv_array_sha256"]:
        raise ValueError("Source UV order or identity changed.")
    if tuple(float(x) for x in raw.shape) != source.shape:
        raise ValueError("Source shape coefficients changed.")
    rgb = _image(source.original_rgb, "RGB", source=True)
    alignment = align_ffhq(rgb, project_vertices(raw, keypoints))
    for name, dtype, shape, actual in (
        ("source_to_aligned", "<f8", (3, 3), alignment.source_to_aligned),
        ("aligned_to_source", "<f8", (3, 3), alignment.aligned_to_source),
        ("source_quad", "<f8", (4, 2), alignment.source_quad),
        ("valid_mask", "|u1", (256, 256), alignment.valid_mask.astype(np.uint8)),
    ):
        if not np.array_equal(_read_array(meta["alignment"][name], dtype, shape), actual):
            raise ValueError("Source alignment geometry changed.")
    if meta["alignment"]["metadata"] != alignment.metadata or not np.array_equal(_image(source.aligned_png, "RGB", (256, 256)), alignment.rgb):
        raise ValueError("Source alignment pixels or semantics changed.")
    texture = project_photo_texture(rgb, raw, uv)
    mesh = build_static_mesh(raw, source.source_age.model_dump(), texture=texture)
    if mesh.glb != source.glb or texture.png != source.texture_png:
        raise ValueError("Original canonical assets no longer match source geometry.")
    return fingerprint, raw, keypoints, uv


@dataclass(frozen=True)
class StagedTarget:
    stage_id: str
    source_fingerprint: str
    target_condition: int
    generated_sha256: str
    fit_sha256: str

    def __post_init__(self):
        if not isinstance(self.stage_id, str) or _STAGE_ID.fullmatch(self.stage_id) is None:
            raise ValueError("Invalid private stage identifier.")
        _condition(self.target_condition)
        for value in (self.source_fingerprint, self.generated_sha256, self.fit_sha256):
            _digest(value)


@dataclass(frozen=True)
class StagedPreview:
    target: StagedTarget
    png: bytes
    fit_bytes: bytes
    landmarks_xy: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class TargetMaskReview:
    source_fingerprint: str
    generated_sha256: str
    fit_sha256: str
    allowed_png: bytes
    occluded_png: bytes
    reviewer: str
    method: str
    version: str
    reviewer_kind: str = "ai"

    def __post_init__(self):
        for value in (self.source_fingerprint, self.generated_sha256, self.fit_sha256):
            _digest(value)
        for value in (self.reviewer, self.method, self.version):
            _text(value)
        if self.reviewer_kind not in {"ai", "human"}:
            raise ValueError("Review provenance must identify AI or human scope.")
        if any(type(data) is not bytes or not 0 < len(data) <= MAX_PNG_BYTES for data in (self.allowed_png, self.occluded_png)):
            raise ValueError("Review masks must be bounded immutable PNG bytes.")


@dataclass(frozen=True)
class RegisteredConditionResult:
    result: SessionResult
    provenance_json: bytes


class ReviewRequired(ApiError):
    def __init__(self, staged: StagedTarget):
        super().__init__(409, "REVIEW_REQUIRED", "生成目标需要匹配图像和拟合指纹的审核遮罩。")
        self.staged = staged


async def _drain(task: asyncio.Task):
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        # Retrieve an abandoned failure before propagating caller cancellation.
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


class ResearchAgingProcessor:
    """Own one SAM worker and opaque bounded stages; reconstruction models are caller-owned.

    A cancelled waiter drains actual native work before returning. The existing
    coordinator's lease consequently remains charged through SAM and CPU work.
    Stage TTL is enforced at acquisition and again after native registration;
    ``sweep_stages`` provides explicit idle purging without another background task.
    """

    def __init__(self, worker, target_refitter: Callable[[np.ndarray], TddfaResult],
                 bindings: ResearchBindings, review_provider=None, *, stage_cache=None,
                 max_stage_entries: int = 4):
        if not callable(target_refitter) or not isinstance(bindings, ResearchBindings):
            raise ValueError("An explicit refitter and model bindings are required.")
        if review_provider is not None and not callable(review_provider):
            raise ValueError("Review provider must be a synchronous local callable.")
        if type(max_stage_entries) is not int or not 1 <= max_stage_entries <= 16:
            raise ValueError("Stage index must have a fixed small entry budget.")
        self.worker, self.bindings = worker, bindings
        self._refitter, self._review_provider = target_refitter, review_provider
        self._cache = stage_cache if stage_cache is not None else AssetCache(
            max_bytes=64 * 1024**2, max_entries=4, max_asset_bytes=MAX_STAGE_BYTES, ttl_seconds=300)
        if not isinstance(self._cache, AssetCache):
            raise ValueError("Staged payloads require the existing bounded lease cache.")
        self._index: OrderedDict[tuple[str, int], StagedTarget] = OrderedDict()
        self._index_limit = max_stage_entries
        self._active: asyncio.Task | None = None
        self._cpu: asyncio.Task | None = None
        self._shutdown: asyncio.Task | None = None
        self._closed = False

    @property
    def snapshot(self) -> dict:
        return {"closed": self._closed, "active": self._active is not None and not self._active.done(),
                "native_cpu_active": self._cpu is not None and not self._cpu.done(),
                "stage_index_entries": len(self._index), **_CLOSED_FLAGS}

    async def _native(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._cpu = task
        try:
            return await _drain(task)
        finally:
            if self._cpu is task:
                self._cpu = None

    async def _admit(self, function, *args):
        if self._closed:
            raise ApiError(503, "MODEL_NOT_READY", "研究处理器正在关闭。")
        if self._active is not None and not self._active.done():
            raise ApiError(429, "BUSY", "研究处理资源正忙。")
        task = asyncio.create_task(function(*args))
        self._active = task
        try:
            return await _drain(task)
        finally:
            if self._active is task and task.done():
                self._active = None

    def _lease(self, target: StagedTarget):
        if self._closed:
            raise ApiError(503, "MODEL_NOT_READY", "研究处理器正在关闭。")
        if not isinstance(target, StagedTarget):
            raise ValueError("An opaque staged target is required.")
        try:
            return self._cache.acquire(target.stage_id)
        except (AssetNotFound, AssetCacheClosed):
            raise ApiError(404, "STAGE_EXPIRED", "研究暂存目标不存在或已过期。") from None

    def sweep_stages(self) -> None:
        for key, handle in list(self._index.items()):
            try:
                with self._cache.acquire(handle.stage_id):
                    pass
            except (AssetNotFound, AssetCacheClosed):
                self._index.pop(key, None)

    def _stage_data(self, data: bytes, target: StagedTarget):
        value = _json(data, MAX_STAGE_BYTES)
        if (
            value.get("version") != STAGE_VERSION
            or value.get("source_fingerprint") != target.source_fingerprint
            or value.get("target_condition") != target.target_condition
            or value.get("generated_sha256") != target.generated_sha256
            or value.get("fit_sha256") != target.fit_sha256
        ):
            raise ReviewRequired(target)
        png, fit = _bytes(value["png"], MAX_PNG_BYTES), _bytes(value["fit"], MAX_CONTEXT_BYTES)
        if _sha(png) != target.generated_sha256 or _sha(fit) != target.fit_sha256:
            raise ReviewRequired(target)
        _image(png, "RGB", (1024, 1024))
        raw = _read_fit(_json(fit, MAX_CONTEXT_BYTES))
        return value, png, fit, raw

    def preview_staged(self, target: StagedTarget) -> StagedPreview:
        try:
            with self._lease(target) as lease:
                value, png, fit, _raw = self._stage_data(lease.data, target)
                points = value["landmarks_xy"]
                array = np.asarray(points, dtype=np.float64)
                if array.shape != (68, 2) or not np.isfinite(array).all():
                    raise ValueError("Target landmark evidence differs.")
                return StagedPreview(target, png, fit, tuple(tuple(p) for p in array.tolist()))
        except (KeyError, TypeError, ValueError, OSError):
            raise ReviewRequired(target) from None

    async def stage_condition(self, source: SessionSource, condition: int) -> StagedTarget:
        """Study an integer condition; unknown API source age remains unknown."""
        _condition(condition)
        return await self._admit(self._stage, source, condition)

    async def _source(self, source):
        try:
            return await self._native(_load_source, source, self.bindings)
        except (ValueError, KeyError, TypeError, OSError, OverflowError):
            raise ApiError(422, "INVALID_CONTEXT", "研究源上下文或模型绑定无效。") from None

    def _fit_target(self, png, source_raw, keypoints):
        rgb = _image(png, "RGB", (1024, 1024))
        raw = self._refitter(rgb)
        _fit_object(raw)
        if raw.topology_sha256 != source_raw.topology_sha256 or not np.array_equal(raw.triangles, source_raw.triangles) or raw.vertices.shape != source_raw.vertices.shape:
            raise ValueError("Target fit changed the source's ordered topology.")
        points = project_vertices(raw, keypoints)[:, :2]
        if points.shape != (68, 2) or not np.isfinite(points).all():
            raise ValueError("Target-own fitted landmarks are unavailable.")
        return _encode(_fit_object(raw), MAX_CONTEXT_BYTES), points.tolist()

    async def _stage(self, source, condition):
        fingerprint, raw, keypoints, _uv = await self._source(source)
        self.sweep_stages()
        key = (fingerprint, condition)
        if key in self._index:
            handle = self._index[key]
            with self._lease(handle) as lease:
                self._stage_data(lease.data, handle)
            self._index.move_to_end(key)
            return handle
        try:
            try:
                generated = await self.worker.generate(source.aligned_png, condition)
            finally:
                await self.worker.wait_idle()
        except SamWorkerError as error:
            code = error.code if error.code in {"BUSY", "TIMEOUT", "WORKER_CLOSED", "WORKER_PROTOCOL"} else "WORKER_FAILED"
            raise ApiError(504 if code == "TIMEOUT" else 429 if code == "BUSY" else 503, code, "研究生成未能完成。") from None
        if (
            not isinstance(generated, SamGeneration)
            or generated.sha256 != _sha(generated.png)
            or generated.input_sha256 != _sha(source.aligned_png)
            or type(generated.target_age) is not int or generated.target_age != condition
            or type(generated.pid) is not int or generated.pid <= 0 or generated.load_count != 1
            or generated.provenance.get("pid") != generated.pid
            or generated.provenance.get("load_count") != 1
            or generated.provenance.get("research_only") is not True
            or generated.provenance.get("service_ready") is not False
            or generated.provenance.get("pins", {}).get("manifest_sha256") != self.bindings.sam_manifest_sha256
        ):
            raise ApiError(502, "WORKER_PROTOCOL", "研究生成来源或图像指纹不匹配。")
        try:
            fit, points = await self._native(self._fit_target, generated.png, raw, keypoints)
        except ApiError:
            raise
        except Exception:
            raise ApiError(500, "RECONSTRUCTION_FAILED", "生成目标的人脸重建失败。") from None
        if self._closed:
            raise ApiError(503, "MODEL_NOT_READY", "研究处理器正在关闭。")
        try:
            data = _encode({"version": STAGE_VERSION, "source_fingerprint": fingerprint,
                "target_condition": condition, "generated_sha256": generated.sha256, "fit_sha256": _sha(fit),
                "png": _b64(generated.png), "fit": _b64(fit), "landmarks_xy": points,
                "generation": _json(_encode(generated.provenance, _META_BYTES), _META_BYTES),
                **_CLOSED_FLAGS}, MAX_STAGE_BYTES)
            stage_id = self._cache.publish(data)
        except (AssetCapacityError, ValueError):
            raise ApiError(429, "BUSY", "研究暂存空间不足。") from None
        handle = StagedTarget(stage_id, fingerprint, condition, generated.sha256, _sha(fit))
        self._index[key] = handle
        while len(self._index) > self._index_limit:
            self._index.popitem(last=False)
        return handle

    def _register(self, source, loaded, data, target, review):
        fingerprint, source_raw, _keypoints, uv = loaded
        value, png, _fit_bytes, target_raw = self._stage_data(data, target)
        if not isinstance(review, TargetMaskReview) or (review.source_fingerprint, review.generated_sha256, review.fit_sha256) != (fingerprint, target.generated_sha256, target.fit_sha256):
            raise ReviewRequired(target)
        try:
            allowed, occluded = (_image(p, "L", (1024, 1024)) for p in (review.allowed_png, review.occluded_png))
            if not np.isin(allowed, (0, 255)).all() or not np.isin(occluded, (0, 255)).all() or np.any((allowed != 0) & (occluded != 0)):
                raise ValueError("Reviewed target masks must be binary and disjoint.")
        except (ValueError, OSError, TypeError):
            raise ReviewRequired(target) from None
        provenance = {"version": "agemorph3d-research-registered-condition-v1",
            "source_fingerprint": fingerprint, "target_condition": target.target_condition,
            "condition_semantics": "SAM integer generation condition; not biological age truth",
            "source_age": source.source_age.model_dump(mode="json"), "shape_route": "static_fallback",
            "generated_sha256": target.generated_sha256, "target_fit_sha256": target.fit_sha256,
            "allowed_png_sha256": _sha(review.allowed_png), "occluded_png_sha256": _sha(review.occluded_png),
            "reviewer": review.reviewer, "reviewer_kind": review.reviewer_kind, "review_method": review.method,
            "review_version": review.version, "model_bindings": asdict(self.bindings),
            "generation": value["generation"], **_CLOSED_FLAGS}
        texture = register_generated_texture(_image(png, "RGB", (1024, 1024)), target_raw, uv, allowed != 0)
        if not np.all(texture.rgba[~texture.coverage] == 0):
            raise ValueError("Unknown texels were filled.")
        metadata = {**texture.metadata, "kind": "sam_generated_registered_uv", "research_pipeline": provenance}
        mesh = build_static_mesh(source_raw, source.source_age.model_dump(), texture=replace(texture, metadata=metadata))
        return RegisteredConditionResult(SessionResult(mesh.glb, texture.png, source.shape, "sam_registered_uv"),
                                         _encode(provenance, _META_BYTES))

    async def register_reviewed(self, source, target, review) -> RegisteredConditionResult:
        return await self._admit(self._reviewed, source, target, review)

    async def _reviewed(self, source, target, review):
        loaded = await self._source(source)
        if loaded[0] != target.source_fingerprint:
            raise ReviewRequired(target)
        lease = self._lease(target)
        try:
            try:
                result = await self._native(self._register, source, loaded, lease.data, target, review)
            except ApiError:
                raise
            except Exception:
                raise ApiError(500, "REGISTRATION_FAILED", "审核目标的UV注册失败。") from None
            # A pinned lease can outlive its TTL; fresh acquisition rejects late results.
            with self._lease(target):
                pass
            return result
        finally:
            lease.close()

    async def __call__(self, source: SessionSource, age: int) -> SessionResult:
        if source.source_age.value is None:
            raise ApiError(422, "SOURCE_AGE_REQUIRED", "绝对年龄需要已知源年龄。")
        if type(age) not in {int, float} or not math.isfinite(age) or not 20 <= age <= 70:
            raise ApiError(422, "BAD_INPUT", "目标年龄必须为20—70的有限数值。")
        if age == source.source_age.value:
            await self._admit(self._source, source)
            return SessionResult(source.glb, source.texture_png, source.shape, "source_reset")
        condition = _condition(int(age)) if float(age).is_integer() else _condition(age)
        target = await self.stage_condition(source, condition)
        review = None if self._review_provider is None else self._review_provider(self.preview_staged(target))
        if not isinstance(review, TargetMaskReview):
            raise ReviewRequired(target)
        return (await self.register_reviewed(source, target, review)).result

    async def close(self) -> dict:
        if self._shutdown is None:
            self._closed = True

            async def shutdown():
                active = self._active
                try:
                    jobs = [self.worker.close()]
                    if active is not None:
                        jobs.append(asyncio.shield(active))
                    results = await asyncio.gather(*jobs, return_exceptions=True)
                    if isinstance(results[0], BaseException):
                        raise ApiError(503, "WORKER_FAILED", "研究生成进程关闭失败。")
                finally:
                    self._cache.close()
                    self._index.clear()

            self._shutdown = asyncio.create_task(shutdown())
        await _drain(self._shutdown)
        return self.snapshot
