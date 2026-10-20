"""Bounded original-photo FFHQ geometry for offline SAM bridge experiments.

The eye/mouth crop geometry follows SAM's FFHQ alignment script. Integer source
and destination coordinates denote pixel centers. The source quad corners map
to destination *edges* (-.5,-.5), (-.5,N-.5), (N-.5,N-.5), (N-.5,-.5).
Consequently destination center (u,v) samples quad[0] + (u+.5)/N *
(quad[3]-quad[0]) + (v+.5)/N * (quad[1]-quad[0]). This matches the geometry of
Pillow QUAD with upstream's ``quad + .5``. It deliberately does not reproduce
upstream shrink filtering, padded-image Gaussian/median blending, or rounding.

Reflected samples provide generation context only. ``valid_mask`` excludes
every sample without complete bilinear support in the original photograph;
later UV registration must also reject generated/externally occluded surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

_MAX_PIXELS = 16_000_000
_MAX_POINTS = 1024 * 1024


@dataclass(frozen=True)
class FFHQAlignment:
    rgb: NDArray[np.uint8]
    valid_mask: NDArray[np.bool_]
    source_to_aligned: NDArray[np.float64]
    aligned_to_source: NDArray[np.float64]
    source_quad: NDArray[np.float64]
    metadata: dict[str, Any]


def _numbers(value: object, name: str) -> NDArray[np.float64]:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite real numbers.")
    return np.array(array, dtype=np.float64, copy=True, order="C")


def transform_points(points: object, matrix: object) -> NDArray[np.float64]:
    """Apply a nonsingular homogeneous transform to Nx2 pixel-center coordinates."""
    points = np.asarray(points)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) > _MAX_POINTS:
        raise ValueError("points must have shape Nx2 within the point work budget.")
    points = _numbers(points, "points")
    matrix = _numbers(matrix, "matrix")
    if matrix.shape != (3, 3):
        raise ValueError("matrix must have shape 3x3.")
    if not np.isfinite(np.linalg.det(matrix)) or abs(np.linalg.det(matrix)) < 1e-15:
        raise ValueError("matrix must be nonsingular.")
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        homogeneous = np.column_stack((points, np.ones(len(points)))) @ matrix.T
        result = homogeneous[:, :2] / homogeneous[:, 2:3]
    if not np.isfinite(result).all() or np.any(np.abs(homogeneous[:, 2]) < 1e-15):
        raise ValueError("Transform produces undefined or nonfinite coordinates.")
    return result


def _quad(landmarks: NDArray[np.float64], width: int, height: int) -> NDArray[np.float64]:
    extent = max(width, height)
    if np.max(np.abs(landmarks)) > 8 * extent:
        raise ValueError("FFHQ crop or padding exceeds the original-photo geometry budget.")
    # These iBUG indices and coefficients are shared by FFHQ and SAM upstream.
    eye_left = landmarks[36:42].mean(axis=0)
    eye_right = landmarks[42:48].mean(axis=0)
    eye_average = (eye_left + eye_right) * 0.5
    eyes = eye_right - eye_left
    mouth = (landmarks[48] + landmarks[54]) * 0.5
    eye_to_mouth = mouth - eye_average
    eye_distance = float(np.linalg.norm(eyes))
    if eye_distance < 2 or eyes[0] <= 0:
        raise ValueError("Eye ordering must be forward, non-mirrored and nondegenerate.")
    right = eyes / eye_distance
    down = np.array([-right[1], right[0]])
    mouth_offset = float(eye_to_mouth @ right / eye_distance)
    mouth_height = float(eye_to_mouth @ down / eye_distance)
    mouth_span = landmarks[54] - landmarks[48]
    width_ratio = float(mouth_span @ right / eye_distance)
    if (
        not 0.15 <= mouth_height <= 2.5
        or abs(mouth_offset) > 1.25
        or not 0.2 <= width_ratio <= 2.5
        or abs(float(mouth_span @ down)) > eye_distance
    ):
        raise ValueError("Eye and mouth landmarks have implausible or mirrored geometry.")
    for eye, center in ((landmarks[36:42], eye_left), (landmarks[42:48], eye_right)):
        radius = float(np.linalg.norm(eye - center, axis=1).max())
        if not 0.015 * eye_distance <= radius <= 0.8 * eye_distance:
            raise ValueError("Eye contours are degenerate or incompatible with eye separation.")

    x_axis = eyes - np.flip(eye_to_mouth) * [-1, 1]
    x_axis /= np.linalg.norm(x_axis)
    x_axis *= max(eye_distance * 2, float(np.linalg.norm(eye_to_mouth)) * 1.8)
    y_axis = np.flip(x_axis) * [-1, 1]
    center = eye_average + eye_to_mouth * 0.1
    quad = np.stack(
        (
            center - x_axis - y_axis,
            center - x_axis + y_axis,
            center + x_axis + y_axis,
            center + x_axis - y_axis,
        )
    )
    if (
        2 * np.linalg.norm(x_axis) > 4 * extent
        or np.any(quad.max(axis=0) < 0)
        or np.any(quad.min(axis=0) > [width - 1, height - 1])
    ):
        raise ValueError("FFHQ crop or padding exceeds the original-photo geometry budget.")
    return quad


def _reflect(coordinates: NDArray[np.float64], size: int) -> NDArray[np.float64]:
    # Equivalent to np.pad(..., mode='reflect'), without allocating a padded image.
    period = 2 * (size - 1)
    folded = np.remainder(coordinates, period)
    return np.minimum(folded, period - folded)


def align_ffhq(rgb: object, landmarks: object, *, output_size: int = 256) -> FFHQAlignment:
    """Resample the original RGB photograph with a validated 68-point FFHQ quad.

    The optional third landmark component is validated but ignored. Output RGB
    and geometry arrays are independent, read-only copies; no files are written.
    """
    source = np.asarray(rgb)
    if (
        source.dtype != np.uint8
        or source.ndim != 3
        or source.shape[2] != 3
        or min(source.shape[:2]) < 2
        or source.shape[0] * source.shape[1] > _MAX_PIXELS
    ):
        raise ValueError("RGB must be a uint8 HxWx3 photograph of 2..16,000,000 pixels.")
    if isinstance(output_size, bool) or not isinstance(output_size, (int, np.integer)):
        raise ValueError("output_size must be an integer from 32 to 1024.")
    if not 32 <= output_size <= 1024:
        raise ValueError("output_size must be an integer from 32 to 1024.")
    points = _numbers(landmarks, "landmarks")
    if points.shape not in ((68, 2), (68, 3)):
        raise ValueError("landmarks must have shape 68x2 or 68x3 in iBUG order.")
    points = points[:, :2]
    height, width = source.shape[:2]
    quad = _quad(points, width, height)
    horizontal = (quad[3] - quad[0]) / output_size
    vertical = (quad[1] - quad[0]) / output_size
    aligned_to_source = np.eye(3, dtype=np.float64)
    aligned_to_source[:2, :2] = np.column_stack((horizontal, vertical))
    aligned_to_source[:2, 2] = quad[0] + (horizontal + vertical) * 0.5
    source_to_aligned = np.linalg.inv(aligned_to_source)
    rows, columns = np.mgrid[:output_size, :output_size]
    sample = transform_points(
        np.column_stack((columns.ravel(), rows.ravel())), aligned_to_source
    ).reshape(output_size, output_size, 2)
    valid = (
        (sample[..., 0] >= 0)
        & (sample[..., 0] <= width - 1)
        & (sample[..., 1] >= 0)
        & (sample[..., 1] <= height - 1)
    )
    xx = _reflect(sample[..., 0], width)
    yy = _reflect(sample[..., 1], height)
    left, top = np.floor(xx).astype(np.intp), np.floor(yy).astype(np.intp)
    right, bottom = np.minimum(left + 1, width - 1), np.minimum(top + 1, height - 1)
    fx, fy = (xx - left)[..., None], (yy - top)[..., None]
    colors = (
        source[top, left] * (1 - fx) * (1 - fy)
        + source[top, right] * fx * (1 - fy)
        + source[bottom, left] * (1 - fx) * fy
        + source[bottom, right] * fx * fy
    )
    aligned = np.clip(np.rint(colors), 0, 255).astype(np.uint8)
    metadata = {
        "schema_version": 1,
        "geometry": "SAM/FFHQ iBUG68 eye-mouth quad",
        "geometry_compatible_with_upstream": True,
        "pixel_identical_to_upstream": False,
        "pixel_center_convention": "integer coordinates; quad maps to output edges -0.5..N-0.5",
        "source_size": [width, height],
        "aligned_size": [int(output_size), int(output_size)],
        "resampling": "continuous float64 bilinear, nearest-even uint8 rounding",
        "padding": "reflect without upstream Gaussian/median blending",
        "upstream_shrink_filter_applied": False,
        "valid_pixels": int(valid.sum()),
        "reflected_or_unsupported_pixels": int(valid.size - valid.sum()),
        "valid_fraction": float(valid.mean()),
        "valid_mask_semantics": "complete original-photo bilinear support only",
        "reflected_pixels_eligible_for_uv": False,
        "generated_pixels_eligible_for_uv": False,
        "external_occlusion_detection": False,
    }
    for array in (aligned, valid, source_to_aligned, aligned_to_source, quad):
        array.setflags(write=False)
    return FFHQAlignment(aligned, valid, source_to_aligned, aligned_to_source, quad, metadata)
