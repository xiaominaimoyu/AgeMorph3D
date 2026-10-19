"""B0 CPU probe for the decoded YOLO5Face ONNX export, independent of the API.

Export semantics: deepcam-cn/yolov5-face models/yolo.py (export_cat=True).
Only [1, N, 16] = xywh, objectness, five xy pairs, face probability is accepted.
This module implements no raw-head decoder and grants no service capability.
"""

from dataclasses import dataclass

import cv2
import numpy as np
import onnxruntime as ort

from .model_assets import ModelAssetError, VerifiedModelAssets

LANDMARK_ORDER = (
    "image_left_eye",
    "image_right_eye",
    "nose_tip",
    "image_left_mouth_corner",
    "image_right_mouth_corner",
)


@dataclass(frozen=True)
class Letterbox:
    width: int
    height: int
    resized_width: int
    resized_height: int
    left: int
    top: int

    def restore(self, points: np.ndarray) -> np.ndarray:
        """Undo the actual rounded resize and integer padding, without mirroring."""
        restored = np.asarray(points, dtype=np.float32).copy()
        restored[..., 0] = (restored[..., 0] - self.left) * self.width / self.resized_width
        restored[..., 1] = (restored[..., 1] - self.top) * self.height / self.resized_height
        return restored


@dataclass(frozen=True)
class Detection:
    bbox: tuple[float, float, float, float]
    landmarks: tuple[tuple[float, float], ...]
    confidence: float


def letterbox(rgb: np.ndarray, size: int = 640) -> tuple[np.ndarray, Letterbox]:
    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or min(rgb.shape[:2]) < 1
        or rgb.shape[0] * rgb.shape[1] > 16_000_000
        or type(size) is not int
        or not 1 <= size <= 640
    ):
        raise ValueError("Detector input must be a nonempty uint8 RGB image.")
    height, width = rgb.shape[:2]
    ratio = min(size / width, size / height)
    resized_width, resized_height = max(1, round(width * ratio)), max(1, round(height * ratio))
    left, top = (size - resized_width) // 2, (size - resized_height) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[top : top + resized_height, left : left + resized_width] = cv2.resize(
        rgb, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR
    )
    tensor = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None], dtype=np.float32) / 255
    return tensor, Letterbox(width, height, resized_width, resized_height, left, top)


def decode_detections(
    output: np.ndarray,
    transform: Letterbox,
    *,
    confidence: float = 0.5,
    iou_threshold: float = 0.45,
) -> list[Detection]:
    if not (0 < confidence <= 1 and 0 < iou_threshold < 1):
        raise ValueError("Invalid detector thresholds.")
    if (
        output.ndim != 3
        or output.shape[0] != 1
        or output.shape[2] != 16
        or output.shape[1] > 100_000
        or not np.isfinite(output).all()
        or np.any(np.abs(output[..., :4]) > 1_000_000)
        or np.any(np.abs(output[..., 5:15]) > 1_000_000)
    ):
        raise ValueError("Expected finite, decoded YOLO5Face output [1,N,16].")
    rows = output[0]
    probabilities = rows[:, (4, 15)]
    if np.any((probabilities < 0) | (probabilities > 1)) or np.any(rows[:, 2:4] < 0):
        raise ValueError("Invalid decoded YOLO5Face boxes or probabilities.")
    scores = rows[:, 4] * rows[:, 15]
    selected = np.flatnonzero((scores >= confidence) & np.all(rows[:, 2:4] > 0, axis=1))
    # Stable order preserves the original candidate index when scores tie.
    selected = selected[np.argsort(-scores[selected], kind="stable")]
    if len(selected) > 3000:
        raise ValueError("Too many face candidates for bounded B0 NMS.")
    rows, scores = rows[selected], scores[selected]
    corners = np.stack((rows[:, :2] - rows[:, 2:4] / 2, rows[:, :2] + rows[:, 2:4] / 2), 1)
    corners = transform.restore(corners)
    corners[..., 0] = np.clip(corners[..., 0], 0, transform.width - 1)
    corners[..., 1] = np.clip(corners[..., 1], 0, transform.height - 1)
    landmarks = transform.restore(rows[:, 5:15].reshape(-1, 5, 2))
    if not np.isfinite(corners).all() or not np.isfinite(landmarks).all():
        raise ValueError("Decoded original-image coordinates must be finite.")
    results = []
    remaining = np.arange(len(rows))
    while remaining.size:
        current, others = int(remaining[0]), remaining[1:]
        lo, hi = corners[current]
        size = hi - lo
        if np.all(size > 0):
            results.append(
                Detection(
                    bbox=tuple(float(v) for v in (*lo, *size)),
                    landmarks=tuple(tuple(float(v) for v in point) for point in landmarks[current]),
                    confidence=float(scores[current]),
                )
            )
        if len(results) >= 100:
            raise ValueError("Too many faces for the B0 probe.")
        intersection = np.maximum(
            0, np.minimum(corners[others, 1], hi) - np.maximum(corners[others, 0], lo)
        ).prod(axis=1)
        area = np.maximum(0, size).prod()
        other_area = np.maximum(0, corners[others, 1] - corners[others, 0]).prod(axis=1)
        union = area + other_area - intersection
        overlaps = np.divide(intersection, union, out=np.zeros_like(union), where=union > 0)
        remaining = others[overlaps <= iou_threshold]
    return results


class Yolo5FaceOnnx:
    """A hash-checked, CPU-only research adapter; never a readiness shortcut."""

    provider = "CPUExecutionProvider"

    def __init__(self, assets: VerifiedModelAssets):
        if assets.manifest.backend != "yolov5_face_onnx" or set(assets.paths) != {"detector"}:
            raise ModelAssetError("YOLO5Face requires exactly one detector artifact.")
        path = assets.paths["detector"]
        if path.stat().st_size > 128 * 1024**2:
            raise ModelAssetError("B0 detector exceeds the in-memory model limit.")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        # Loading bytes prevents unlisted ONNX external-data files being read from disk.
        self.session = ort.InferenceSession(
            path.read_bytes(), sess_options=options, providers=[self.provider]
        )
        inputs, outputs = self.session.get_inputs(), self.session.get_outputs()
        if (
            len(inputs) != 1
            or inputs[0].type != "tensor(float)"
            or inputs[0].shape != [1, 3, 640, 640]
            or len(outputs) != 1
            or outputs[0].type != "tensor(float)"
            or len(outputs[0].shape) != 3
            or outputs[0].shape[0] != 1
            or outputs[0].shape[2] != 16
            or self.session.get_providers() != [self.provider]
        ):
            raise ModelAssetError("Unsupported YOLO5Face ONNX input/output or provider.")
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name
        self.license_verified = assets.license_verified

    def detect(self, rgb: np.ndarray) -> list[Detection]:
        tensor, transform = letterbox(rgb)
        output = self.session.run([self.output_name], {self.input_name: tensor})[0]
        return decode_detections(output, transform)
