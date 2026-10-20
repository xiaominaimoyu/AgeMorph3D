"""Offline age-research geometry in one unchanged source canonical frame.

These fitted BFM diagnostics are not measured 3-D truth, identity scores, or an
age calibration. Camera rotations are compared separately and never applied to
the already pre-projection identity/expression geometry.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .static_mesh import projection_rotation


def _finite(value: object, name: str, shape: tuple[int, ...] | None = None) -> NDArray:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite real numbers.")
    if shape is not None and array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}.")
    result = np.array(array, dtype=np.float64, order="C", copy=True)
    if not np.isfinite(result).all():
        raise ValueError(f"{name} is outside the float64 range.")
    return result


def _vertices(value: object, name: str = "Vertices") -> NDArray:
    vertices = _finite(value, name)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
        raise ValueError(f"{name} must have nonempty shape (N,3), N >= 3.")
    return vertices


def _raw(raw: object) -> tuple[NDArray, NDArray, NDArray, NDArray]:
    if raw.coordinate_system != "bfm_model_raw":
        raise ValueError("Research geometry requires pre-projection bfm_model_raw coordinates.")
    if not isinstance(raw.topology_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", raw.topology_sha256
    ):
        raise ValueError("Topology must have a complete lowercase SHA-256 identifier.")
    vertices = _vertices(raw.vertices)
    faces = np.asarray(raw.triangles)
    if (
        faces.dtype.kind not in "iu"
        or faces.ndim != 2
        or faces.shape[1] != 3
        or not len(faces)
        or np.any(faces < 0)
        or np.any(faces >= len(vertices))
        or np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0)
    ):
        raise ValueError("Faces must contain valid ordered vertex triplets.")
    shape = _finite(raw.shape, "Shape coefficients", (40,))
    expression = _finite(raw.expr, "Expression coefficients", (10,))
    return vertices, faces, shape, expression


def source_frame(vertices: object) -> dict[str, Any]:
    """Freeze the full original source's bbox frame, matching static_mesh.py."""
    vertices = _vertices(vertices)
    minimum, maximum = vertices.min(axis=0), vertices.max(axis=0)
    extent = maximum - minimum
    if not np.isfinite(extent).all() or extent[1] <= 0:
        raise ValueError("Source must have finite positive bounding-box height.")
    center = minimum + extent / 2
    scale = 1.0 / float(extent[1])
    if not np.isfinite(center).all() or not np.isfinite(scale):
        raise ValueError("Source canonical frame must remain finite.")
    return {
        "source_center": center.tolist(),
        "source_to_canonical_uniform_scale": scale,
        "normalization_reference": "unchanged_source_mesh",
    }


def neutral_vertices(raw: object, expression_basis: object) -> NDArray:
    """Remove only the verified model's expression term without fitting again.

    The caller binds the basis file hash to the fit's model provenance. The BFM
    stores interleaved XYZ coordinates; its Fortran reshape must be preserved.
    """
    vertices, _, _, expression = _raw(raw)
    basis = _finite(expression_basis, "Expression basis")
    if basis.ndim != 2 or basis.shape[0] != vertices.size or basis.shape[1] < 10:
        raise ValueError("Expression basis must have shape (3N,K), K >= 10.")
    with np.errstate(over="ignore", invalid="ignore"):
        displacement = basis[:, :10] @ expression[:, None]
        neutral = vertices - displacement.reshape(3, -1, order="F").T
    if not np.isfinite(neutral).all():
        raise ValueError("Neutral geometry must remain finite.")
    return np.ascontiguousarray(neutral)


def in_source_frame(vertices: object, frame: dict[str, Any]) -> NDArray:
    """Apply the supplied source transform; never normalize the target itself."""
    vertices = _vertices(vertices)
    center = _finite(frame["source_center"], "Source center", (3,))
    scale = _finite(frame["source_to_canonical_uniform_scale"], "Source scale", ())
    if scale <= 0 or frame.get("normalization_reference", "unchanged_source_mesh") != (
        "unchanged_source_mesh"
    ):
        raise ValueError("A positive unchanged-source canonical frame is required.")
    with np.errstate(over="ignore", invalid="ignore"):
        canonical = (vertices - center) * scale
    if not np.isfinite(canonical).all():
        raise ValueError("Canonical coordinates must remain finite.")
    return np.ascontiguousarray(canonical)


def vector_difference_metrics(delta: object) -> dict[str, float]:
    """RMS Euclidean vertex displacement and maximum vertex displacement."""
    delta = _vertices(delta, "Vertex differences")
    with np.errstate(over="ignore", invalid="ignore"):
        lengths = np.linalg.norm(delta, axis=1)
        rms = float(np.sqrt(np.mean(lengths * lengths)))
        maximum = float(lengths.max())
    if not np.isfinite(rms) or not np.isfinite(maximum):
        raise ValueError("Vertex displacement metrics must remain finite.")
    return {"rms": rms, "max": maximum}


def compare_fits(
    source_raw: object,
    target_raw: object,
    expression_basis: object,
    frame: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Compare a pair in one source frame; coefficient norms are diagnostics.

    An explicitly supplied frame can belong to an earlier original source when
    comparing aligned or generated fits. No per-target registration is applied.
    """
    source, source_faces, source_shape, source_expression = _raw(source_raw)
    target, target_faces, target_shape, target_expression = _raw(target_raw)
    if (
        source_raw.topology_sha256 != target_raw.topology_sha256
        or source.shape != target.shape
        or not np.array_equal(source_faces, target_faces)
    ):
        raise ValueError("Fits must share the exact topology, vertex count and ordered faces.")
    if frame is None:
        frame = source_frame(source)
    source_neutral = in_source_frame(neutral_vertices(source_raw, expression_basis), frame)
    target_neutral = in_source_frame(neutral_vertices(target_raw, expression_basis), frame)
    source_full, target_full = in_source_frame(source, frame), in_source_frame(target, frame)
    neutral = vector_difference_metrics(target_neutral - source_neutral)
    full = vector_difference_metrics(target_full - source_full)
    expression_delta = vector_difference_metrics(
        (target_full - target_neutral) - (source_full - source_neutral)
    )
    source_rotation, _ = projection_rotation(source_raw.projection)
    target_rotation, _ = projection_rotation(target_raw.projection)
    cosine = np.clip((np.trace(source_rotation.T @ target_rotation) - 1) / 2, -1, 1)
    expression_l2 = float(np.linalg.norm(target_expression - source_expression))
    shape_l2 = float(np.linalg.norm(target_shape - source_shape))
    if not np.isfinite(expression_l2) or not np.isfinite(shape_l2):
        raise ValueError("Coefficient diagnostics must remain finite.")
    return {
        "neutral_rms": neutral["rms"],
        "neutral_max": neutral["max"],
        "full_rms": full["rms"],
        "full_max": full["max"],
        "expression_delta_rms": expression_delta["rms"],
        "expression_coeff_l2": expression_l2,
        "shape_coeff_l2": shape_l2,
        "pose_rotation_delta_degrees": float(np.degrees(np.arccos(cosine))),
    }
