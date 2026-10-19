"""Strict local model loading, CPU operator checks and observable ownership.

Inference dependencies are imported only inside the worker loader. Blank inputs
exercise operators and array contracts; they do not establish face accuracy,
canonical coordinates, photo reconstruction or any HTTP/WS capability.
"""

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal

from .config import Settings
from .model_assets import ModelAssetError, load_verified_manifest
from .schemas import ModelStatus

ModelName = Literal["detector", "reconstructor"]
_BACKENDS = {"detector": "yolov5_face_onnx", "reconstructor": "3ddfa_v2_onnx"}
_CPU_PROVIDER = "CPUExecutionProvider"


class ModelLoadError(ValueError):
    """An already-sanitized readiness failure, containing no underlying inputs."""


def _dispose(instance: object) -> None:
    # The existing ONNX adapters release their sessions when references are dropped.
    # Adapters with an explicit close hook get the same deterministic ownership.
    close = getattr(instance, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            # A cleanup error must not retain an instance or hide other cleanup.
            pass


@dataclass
class LoadedModel:
    backend: str
    provider: str
    instance: object | None

    def close(self) -> None:
        instance, self.instance = self.instance, None
        if instance is not None:
            _dispose(instance)


def detector_selftest(model: object) -> None:
    """Run real blank-image inference, checking only the output contract."""
    import numpy as np

    results = model.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    if not isinstance(results, list) or len(results) > 100:
        raise ValueError("Unexpected detector result structure.")
    for result in results:
        bbox = np.asarray(result.bbox)
        points = np.asarray(result.landmarks)
        confidence = np.asarray(result.confidence)
        if (
            bbox.shape != (4,)
            or points.shape != (5, 2)
            or confidence.shape != ()
            or not np.isfinite(bbox).all()
            or not np.isfinite(points).all()
            or not np.isfinite(confidence).all()
            or np.any(bbox[2:] <= 0)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Invalid detector selftest output.")


def reconstructor_selftest(model: object) -> None:
    """Run real 62-parameter regression, mesh construction and image projection."""
    import numpy as np

    from .tddfa import project_vertices

    result = model.reconstruct(np.zeros((120, 120, 3), dtype=np.uint8), (20, 20, 80, 80))
    vertices, triangles = np.asarray(result.vertices), np.asarray(result.triangles)
    shape, expr = np.asarray(result.shape), np.asarray(result.expr)
    projection, roi = np.asarray(result.projection), np.asarray(result.roi)
    if (
        shape.shape != (40,)
        or expr.shape != (10,)
        or vertices.ndim != 2
        or vertices.shape[1] != 3
        or not 3 <= len(vertices) <= 1_500_000
        or triangles.ndim != 2
        or triangles.shape[1] != 3
        or not len(triangles)
        or triangles.dtype.kind not in "iu"
        or projection.shape != (3, 4)
        or roi.shape != (4,)
        or not all(np.isfinite(value).all() for value in (shape, expr, vertices, projection, roi))
        or np.any(triangles < 0)
        or np.any(triangles >= len(vertices))
        or np.any(np.diff(np.sort(triangles, axis=1), axis=1) == 0)
        or roi[2] <= roi[0]
        or roi[3] <= roi[1]
        or result.coordinate_system != "bfm_model_raw"
        or result.topology_sha256 != model.topology_sha256
    ):
        raise ValueError("Invalid reconstruction selftest output.")
    for projected, expected in (
        (project_vertices(result), (len(vertices), 3)),
        (project_vertices(result, model.keypoint_coordinates), (68, 3)),
    ):
        if projected.shape != expected or not np.isfinite(projected).all():
            raise ValueError("Invalid image projection selftest output.")


def load_model(name: ModelName, path: Path) -> LoadedModel:
    """Verify strictly, instantiate once and run CPU operators before readiness."""
    try:
        assets = load_verified_manifest(path)
    except ModelAssetError as error:
        detail = (
            "模型权重许可尚未完成核验。"
            if "license is unresolved" in str(error)
            else "模型清单或资产完整性校验失败。"
        )
        raise ModelLoadError(detail) from None
    if assets.manifest.backend != _BACKENDS[name] or not assets.license_verified:
        raise ModelLoadError("模型后端或许可状态与配置角色不匹配。")
    try:
        if name == "detector":
            from .detector import Yolo5FaceOnnx

            factory, selftest = Yolo5FaceOnnx, detector_selftest
        else:
            from .tddfa import TddfaOnnx

            factory, selftest = TddfaOnnx, reconstructor_selftest
    except ImportError:
        raise ModelLoadError("推理依赖不可用，请安装后端 inference 依赖。") from None
    try:
        instance = factory(assets)
    except Exception:
        raise ModelLoadError("模型实例加载失败。") from None
    try:
        if instance.provider != _CPU_PROVIDER or not instance.license_verified:
            raise ValueError("Expected a strictly verified CPU model.")
        selftest(instance)
    except Exception:
        _dispose(instance)
        raise ModelLoadError("模型 CPU 算子自检失败。") from None
    return LoadedModel(assets.manifest.backend, _CPU_PROVIDER, instance)


class ModelLifecycle:
    """One worker writes actual model state; health reads isolated snapshots."""

    def __init__(self, settings: Settings):
        self._paths: dict[ModelName, Path | None] = {
            "detector": settings.detector_manifest,
            "reconstructor": settings.reconstructor_manifest,
        }
        self._lock = Lock()
        self._stopping = False
        self._models: dict[ModelName, LoadedModel] = {}
        self._status = {
            name: ModelStatus(state="missing", detail="尚未配置已核验的模型清单。")
            for name in self._paths
        }
        self._status.update(
            {
                "age_shape": ModelStatus(
                    state="missing", detail="尚未接入可追溯且经过校准的年龄形状资产。"
                ),
                "age_texture": ModelStatus(
                    state="missing", detail="尚未接入年龄纹理模型及 UV 投影。"
                ),
            }
        )

    def begin(self) -> bool:
        with self._lock:
            if self._stopping:
                return False
            for name, path in self._paths.items():
                if path is not None:
                    self._status[name] = ModelStatus(
                        state="loading", detail="正在核验清单、加载模型并执行 CPU 算子自检。"
                    )
            return any(path is not None for path in self._paths.values())

    def snapshot(self) -> dict[str, ModelStatus]:
        with self._lock:
            return {name: status.model_copy() for name, status in self._status.items()}

    def initialize(self) -> None:
        # All filesystem IO, imports, hashing, inference and disposal run here.
        for name, path in self._paths.items():
            with self._lock:
                if self._stopping:
                    return
            if path is None:
                continue
            try:
                if not path.is_file():
                    status = ModelStatus(state="missing", detail="配置的模型清单文件不存在。")
                    loaded = None
                else:
                    loaded = load_model(name, path)
                    status = ModelStatus(
                        state="ready",
                        backend=loaded.backend,
                        provider=loaded.provider,
                        detail="已完成严格资产核验、实例加载及 CPU 算子自检。",
                    )
            except Exception as error:
                loaded = None
                status = ModelStatus(
                    state="error",
                    detail=(
                        str(error) if isinstance(error, ModelLoadError) else "模型初始化失败。"
                    ),
                )
            with self._lock:
                stopping = self._stopping
                if not stopping:
                    self._status[name] = status
                    if loaded is not None:
                        self._models[name] = loaded
            if stopping and loaded is not None:
                loaded.close()

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            for name in self._paths:
                self._status[name] = ModelStatus(state="missing", detail="本地模型服务已停止。")

    def close(self) -> None:
        self.stop()
        with self._lock:
            models, self._models = self._models, {}
        for loaded in models.values():
            loaded.close()
