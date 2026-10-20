"""Offline B6 CPU pose measurements; never grants service readiness or G2.

Camera frames remain in memory. This tool opens no network listener, displays no
window and writes only one aggregate JSON report, without photos or per-frame
pose parameters. The 15 second capture budget is checked between native camera
operations; a blocking camera driver cannot be interrupted by that check.
"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .config import Settings
from .errors import ApiError
from .images import decode_image
from .model_assets import ModelAssetError, load_verified_manifest
from .model_lifecycle import detector_selftest, reconstructor_selftest
from .schemas import Pose

_BACKENDS = {"detector": "yolov5_face_onnx", "reconstructor": "3ddfa_v2_onnx"}
_MAX_SECONDS = 15.0
_SAFE_DETAILS = {
    "BAD_INPUT": "图片内容无效或无法解码。",
    "INPUT_TOO_LARGE": "输入文件、像素或帧数超过限制。",
    "UNSUPPORTED_MEDIA_TYPE": "仅支持内容与声明一致的 JPEG、PNG 或 WebP 图片。",
    "CAMERA_OPEN_FAILED": "无法打开指定的本机摄像头。",
    "CAMERA_READ_FAILED": "摄像头未返回有效画面。",
    "CAMERA_RELEASE_FAILED": "摄像头释放失败，请检查本机设备状态。",
    "FRAME_BUDGET_EXCEEDED": "离线帧采集超过时间预算。",
    "POSE_FAILED": "离线人脸姿态计算失败，请检查本机模型及输入。",
}


def _frame_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= 120:
        raise argparse.ArgumentTypeError("frame-count must be between 1 and 120")
    return count


def _camera_index(value: str) -> int:
    index = int(value)
    if not 0 <= index <= 15:
        raise argparse.ArgumentTypeError("camera-index must be between 0 and 15")
    return index


def _construct_model(role: str, assets: object) -> object:
    if role == "detector":
        from .detector import Yolo5FaceOnnx

        return Yolo5FaceOnnx(assets)
    from .tddfa import TddfaOnnx

    return TddfaOnnx(assets)


def _open_camera(index: int) -> object:
    import cv2

    return cv2.VideoCapture(index, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY)


def _resize_rgb(rgb: object) -> object:
    import cv2
    import numpy as np

    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or min(rgb.shape[:2]) < 1
        or rgb.shape[0] * rgb.shape[1] > 16_000_000
    ):
        raise ApiError(400, "BAD_INPUT", _SAFE_DETAILS["BAD_INPUT"])
    height, width = rgb.shape[:2]
    scale = min(1.0, 640 / max(height, width))
    if scale < 1:
        rgb = cv2.resize(
            rgb,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return np.ascontiguousarray(rgb)


def _summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "p50": None, "p95": None}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        offset = (len(ordered) - 1) * fraction
        left = int(offset)
        right = min(left + 1, len(ordered) - 1)
        return ordered[left] + (ordered[right] - ordered[left]) * (offset - left)

    return {"count": len(values), "p50": percentile(0.5), "p95": percentile(0.95)}


class _TimedModel:
    def __init__(self, model: object, samples: list[float]) -> None:
        self.model = model
        self.samples = samples

    def _call(self, method: str, *args: object) -> object:
        started = perf_counter()
        try:
            return getattr(self.model, method)(*args)
        finally:
            self.samples.append((perf_counter() - started) * 1000)

    def detect(self, rgb: object) -> object:
        return self._call("detect", rgb)

    def reconstruct(self, rgb: object, bbox: object) -> object:
        return self._call("reconstruct", rgb, bbox)


def _check_payload(result: dict, rgb: object, report: dict) -> None:
    import numpy as np

    box = np.asarray(result["bbox"], dtype=np.float64)
    points = np.asarray(result["landmarks"], dtype=np.float64)
    confidence = result["conf"]
    height, width = rgb.shape[:2]
    if (
        box.shape != (4,)
        or points.shape != (5, 2)
        or not np.isfinite(box).all()
        or not np.isfinite(points).all()
        or np.any(box[:2] < 0)
        or np.any(box[2:] <= 0)
        or box[0] + box[2] > width
        or box[1] + box[3] > height
        or np.any(np.abs(points) > 16_384)
        or not np.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ApiError(500, "POSE_FAILED", _SAFE_DETAILS["POSE_FAILED"])
    pose = Pose.model_validate(result["pose"])
    rotation = np.asarray(pose.R).reshape(3, 3)
    checks = report["numerical_checks"]
    checks["valid_payloads"] += 1
    checks["max_rotation_orthogonality_error"] = max(
        checks["max_rotation_orthogonality_error"],
        float(np.max(np.abs(rotation.T @ rotation - np.eye(3)))),
    )
    checks["max_rotation_determinant_error"] = max(
        checks["max_rotation_determinant_error"], abs(float(np.linalg.det(rotation)) - 1)
    )
    if pose.t != [0.0, 0.0, 0.0]:
        raise ApiError(500, "POSE_FAILED", _SAFE_DETAILS["POSE_FAILED"])


def probe(args: argparse.Namespace, report: dict) -> None:
    """Own actual models and optional camera; always release them on every exit."""
    models = {}
    capture = None
    samples = {name: [] for name in ("capture", "resize", "detector", "regressor", "frame_total")}
    source_dimensions = set()
    submitted_dimensions = set()
    try:
        for role, path in (
            ("detector", args.detector_manifest),
            ("reconstructor", args.reconstructor_manifest),
        ):
            started = perf_counter()
            assets = load_verified_manifest(
                path, research_allow_unresolved=args.research_allow_unresolved
            )
            if assets.manifest.backend != _BACKENDS[role]:
                raise ModelAssetError("Model backend does not match its configured role.")
            metadata = {
                "model_id": assets.manifest.model_id,
                "backend": assets.manifest.backend,
                "revision": assets.manifest.revision,
                "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "license_verified": assets.license_verified,
                "manifest_verification_ms": (perf_counter() - started) * 1000,
            }
            report["models"][role] = metadata
            started = perf_counter()
            model = _construct_model(role, assets)
            models[role] = model
            metadata["load_ms"] = (perf_counter() - started) * 1000
            if (
                model.provider != "CPUExecutionProvider"
                or model.license_verified != assets.license_verified
            ):
                raise ValueError("Unexpected provider or license state.")
            metadata["provider"] = model.provider
            started = perf_counter()
            (detector_selftest if role == "detector" else reconstructor_selftest)(model)
            metadata["selftest_ms"] = (perf_counter() - started) * 1000
            metadata["operator_selftest"] = "passed"
        report["license_verified"] = all(
            item["license_verified"] for item in report["models"].values()
        )
        import numpy as np

        from .realtime import infer_realtime

        detector = _TimedModel(models["detector"], samples["detector"])
        reconstructor = _TimedModel(models["reconstructor"], samples["regressor"])
        image_rgb = None
        if args.image is not None:
            settings = Settings()
            if args.image.stat().st_size > settings.max_image_bytes:
                raise ApiError(413, "INPUT_TOO_LARGE", _SAFE_DETAILS["INPUT_TOO_LARGE"])
            data = args.image.read_bytes()
            report["input"] = {
                "type": "image",
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "exif_orientation_applied": True,
            }
            media_type = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }.get(args.image.suffix.lower(), "")
            started = perf_counter()
            with decode_image(data, media_type, settings) as image:
                image_rgb = np.asarray(image).copy()
            report["timings_ms"]["image_decode"] = _summary([(perf_counter() - started) * 1000])
        else:
            report["input"] = {
                "type": "physical_camera",
                "camera_index": args.camera_index,
                "backend": "CAP_DSHOW" if sys.platform == "win32" else "CAP_ANY",
                "saved_frames": False,
            }
            capture = _open_camera(args.camera_index)
            if not capture.isOpened():
                raise ApiError(500, "CAMERA_OPEN_FAILED", _SAFE_DETAILS["CAMERA_OPEN_FAILED"])
        started_loop = perf_counter()
        for _ in range(args.frame_count):
            if perf_counter() - started_loop >= _MAX_SECONDS:
                raise ApiError(504, "FRAME_BUDGET_EXCEEDED", _SAFE_DETAILS["FRAME_BUDGET_EXCEEDED"])
            started_frame = perf_counter()
            started = perf_counter()
            if capture is None:
                rgb = image_rgb
            else:
                okay, bgr = capture.read()
                if not okay or bgr is None:
                    raise ApiError(500, "CAMERA_READ_FAILED", _SAFE_DETAILS["CAMERA_READ_FAILED"])
                if (
                    not isinstance(bgr, np.ndarray)
                    or bgr.dtype != np.uint8
                    or bgr.ndim != 3
                    or bgr.shape[2] != 3
                ):
                    raise ApiError(500, "CAMERA_READ_FAILED", _SAFE_DETAILS["CAMERA_READ_FAILED"])
                # Channel conversion only: neither pixels nor pose are mirrored.
                rgb = bgr[..., ::-1]
            samples["capture"].append((perf_counter() - started) * 1000)
            started = perf_counter()
            source_dimensions.add((int(rgb.shape[1]), int(rgb.shape[0])))
            rgb = _resize_rgb(rgb)
            submitted_dimensions.add((int(rgb.shape[1]), int(rgb.shape[0])))
            samples["resize"].append((perf_counter() - started) * 1000)
            report["frames_attempted"] += 1
            try:
                result = infer_realtime(rgb, detector, reconstructor)
            except ApiError as error:
                if error.code not in {"NO_FACE", "MULTI_FACE"}:
                    raise
                report["counts"][error.code] += 1
            else:
                _check_payload(result, rgb, report)
                report["counts"]["FACE_STATE"] += 1
            samples["frame_total"].append((perf_counter() - started_frame) * 1000)
            if perf_counter() - started_loop > _MAX_SECONDS:
                raise ApiError(504, "FRAME_BUDGET_EXCEEDED", _SAFE_DETAILS["FRAME_BUDGET_EXCEEDED"])
        report["capture_loop_seconds"] = perf_counter() - started_loop
    finally:
        release_failed = False
        if capture is not None:
            try:
                capture.release()
            except Exception:
                report["camera_release"] = "failed"
                release_failed = True
            else:
                report["camera_release"] = "completed"
        for model in models.values():
            close = getattr(model, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        report["timings_ms"].update({name: _summary(values) for name, values in samples.items()})
        report["source_dimensions"] = [list(value) for value in sorted(source_dimensions)]
        report["submitted_dimensions"] = [list(value) for value in sorted(submitted_dimensions)]
        if release_failed:
            raise ApiError(500, "CAMERA_RELEASE_FAILED", _SAFE_DETAILS["CAMERA_RELEASE_FAILED"])


def _failure(report: dict, error: Exception) -> None:
    if isinstance(error, ModelAssetError):
        code, detail = "MODEL_ASSET_ERROR", "模型资产、哈希或许可核验失败。"
    elif isinstance(error, ApiError) and error.code in _SAFE_DETAILS:
        code, detail = error.code, _SAFE_DETAILS[error.code]
    else:
        code, detail = "PROBE_FAILED", "离线实时姿态检查失败，请检查本机资产、依赖及输入。"
    report.update(technical_execution="failed", error_code=code, detail=detail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detector-manifest", type=Path, required=True)
    parser.add_argument("--reconstructor-manifest", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path)
    source.add_argument("--camera-index", type=_camera_index)
    parser.add_argument("--frame-count", type=_frame_count, default=30)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--research-allow-unresolved", action="store_true")
    args = parser.parse_args(argv)
    report = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "B6 offline CPU pose research; not service readiness or G2 acceptance",
        "research_allow_unresolved": args.research_allow_unresolved,
        "service_ready": False,
        "g2_complete": False,
        "license_verified": False,
        "models": {},
        "timings_ms": {},
        "technical_execution": "failed",
        "frames_requested": args.frame_count,
        "frames_attempted": 0,
        "counts": {"FACE_STATE": 0, "NO_FACE": 0, "MULTI_FACE": 0},
        "numerical_checks": {
            "valid_payloads": 0,
            "max_rotation_orthogonality_error": 0.0,
            "max_rotation_determinant_error": 0.0,
        },
        "coordinates": "unmirrored resized RGB pixels; x right, y down; detector five-point order",
        "pose_axes": "+X frontal-image-right, +Y up, +Z face-front; proper right-handed rotation",
        "translation_semantics": "zero_unestimated_metric_translation",
        "camera_budget_seconds": _MAX_SECONDS,
        "camera_deadline_semantics": (
            "checked between native calls; blocking driver read not interruptible"
        ),
        "saved_frames": False,
        "saved_per_frame_parameters": False,
    }
    created = False
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            created = True
            try:
                probe(args, report)
            except Exception as error:
                _failure(report, error)
                exit_code = 1
            else:
                report["technical_execution"] = "passed"
                exit_code = 0
            stream.write(
                (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
                    "utf-8"
                )
            )
    except FileExistsError:
        report.update(error_code="OUTPUT_EXISTS", detail="输出文件已存在，请使用新的报告路径。")
        exit_code = 1
    except (OSError, ValueError):
        if created:
            args.output.unlink(missing_ok=True)
        report.update(
            technical_execution="failed",
            error_code="OUTPUT_WRITE_FAILED",
            detail="无法独占写入输出文件，请检查新的报告路径。",
        )
        exit_code = 1
    print(
        json.dumps(
            {
                "technical_execution": report["technical_execution"],
                "service_ready": False,
                "g2_complete": False,
                "license_verified": report["license_verified"],
                "error_code": report.get("error_code"),
            },
            ensure_ascii=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
