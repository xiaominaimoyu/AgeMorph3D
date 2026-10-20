"""One CPU face-pose inference, independent of WebSocket and asset ownership.

The submitted RGB image is unmirrored. Boxes and the detector's five landmarks
retain that image's pixels and point order. The model rotation retains canonical
BFM +X right, +Y up, +Z face-front axes. Image-Y inversion and a mirrored preview
are display concerns, not reflections to insert into the proper rotation.

This optional-NumPy worker performs no loading, license override, GLB generation,
cache publication, photo persistence, age prediction or texture generation.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .errors import ApiError
from .schemas import Pose
from .static_mesh import projection_rotation

_MAX_IMAGE_PIXELS = 16_000_000
_MAX_LANDMARK_ABS = 16_384
_FAILURE_MESSAGE = "实时人脸姿态计算失败，请重新打开摄像头后重试。"


def _numbers(value: object, shape: tuple[int, ...]) -> NDArray[np.float64]:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or array.shape != shape or not np.isfinite(array).all():
        raise ValueError("Unexpected numeric result.")
    return np.asarray(array, dtype=np.float64)


def infer_realtime(rgb: object, detector: object, reconstructor: object) -> dict:
    """Return one bounded pose payload; transport supplies type, seq and timestamp.

    Admission, decoded-image ownership and strict model readiness belong to the
    caller. NO_FACE and MULTI_FACE are frame-level recoverable errors. Actual
    library/contract/pose failures are sanitized POSE_FAILED errors. Model output
    cannot smuggle an ApiError containing paths or image details through here.
    """
    try:
        if (
            not isinstance(rgb, np.ndarray)
            or rgb.dtype != np.uint8
            or rgb.ndim != 3
            or rgb.shape[2] != 3
            or min(rgb.shape[:2]) < 1
            or rgb.shape[0] * rgb.shape[1] > _MAX_IMAGE_PIXELS
        ):
            raise ValueError("Expected a bounded uint8 RGB image.")
        faces = detector.detect(rgb)
        if not isinstance(faces, list):
            raise ValueError("Unexpected detection result.")
    except Exception:
        raise ApiError(500, "POSE_FAILED", _FAILURE_MESSAGE) from None

    if not faces:
        raise ApiError(422, "NO_FACE", "未检测到人脸，请正对摄像头并保持光线充足。")
    if len(faces) != 1:
        raise ApiError(422, "MULTI_FACE", "检测到多张人脸，请确保画面中只有一人。")

    try:
        face = faces[0]
        box = _numbers(face.bbox, (4,))
        points = _numbers(face.landmarks, (5, 2))
        confidence = float(_numbers(face.confidence, ()))
        height, width = rgb.shape[:2]
        if (
            np.any(box[:2] < 0)
            or np.any(box[2:] <= 0)
            or box[0] + box[2] > width
            or box[1] + box[3] > height
            or np.any(np.abs(points) > _MAX_LANDMARK_ABS)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Invalid detection coordinates or confidence.")
        raw = reconstructor.reconstruct(rgb, face.bbox)
        if raw.coordinate_system != "bfm_model_raw":
            raise ValueError("Expected raw pre-projection BFM axes.")
        rotation, _ = projection_rotation(raw.projection)
        pose = Pose(R=rotation.reshape(-1).tolist(), t=[0.0, 0.0, 0.0])
        return {
            "bbox": box.tolist(),
            "landmarks": points.tolist(),
            "pose": pose.model_dump(mode="json"),
            "conf": confidence,
        }
    except Exception:
        # Runtime/native messages may contain private paths or frame details.
        raise ApiError(500, "POSE_FAILED", _FAILURE_MESSAGE) from None
