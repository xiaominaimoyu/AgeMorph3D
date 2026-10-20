"""Canonical, nonmetric BFM face geometry and a bounded standalone glTF 2 GLB.

3DDFA's vertices are already identity/expression geometry, before its affine
camera projection. Its upstream ``similar_transform`` flips projected Y for
image pixels; it is not a transform for the canonical mesh:
https://github.com/cleardusk/3DDFA_V2/blob/1b6c67601abffc1e9f248b291708aef0e43b55ae/utils/tddfa_util.py

The verified local BFM landmark coordinates have Y up and the nose toward +Z.
Consequently the canonical axis rotation is identity (determinant +1), not a
reflection of image coordinates. The upstream ordered faces point inward when
viewed from +Z, so each face changes (a,b,c) to (a,c,b). Vertex and face order and
every vertex identifier remain intact. The topology version records this change.

No source proves a metric scale for this modified/cropped BFM. Coordinates are
explicitly dimensionless, uniformly divided by source bounding-box height after
centering at its midpoint. glTF numbers therefore describe a normalized display
object, not measured human metres. The original center/scale make this transform
reversible; identity/expression proportions are preserved.

The regressed projection contains scale and shear. Its closest proper rotation
is obtained through polar/SVD decomposition; reflections and numerically singular
blocks fail explicitly. The image-affine translation cannot establish a metric
camera translation, so the public pose uses zero translation and retains the raw
projection only in the coordinate metadata.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from .schemas import SourceAge

if TYPE_CHECKING:
    from .tddfa import TddfaResult

MAX_GLB_BYTES = 64 * 1024**2
_MAX_VERTICES = 1_500_000
_MAX_FACES = 3_000_000
_MAX_METADATA_BYTES = 16 * 1024
_TOPOLOGY_PREFIX = "tddfa-bfm-canon-v1-"


@dataclass(frozen=True)
class StaticMesh:
    glb: bytes
    topology_id: str
    pose: dict[str, list[float]]
    coordinate_metadata: dict[str, Any]
    vertices: NDArray[np.float32]
    normals: NDArray[np.float32]
    triangles: NDArray[np.uint32]


def _finite(value: object, name: str, shape: tuple[int, ...] | None = None) -> NDArray:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite real numbers.")
    if shape is not None and array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}.")
    return np.array(array, dtype=np.float64, order="C", copy=True)


def projection_rotation(projection: NDArray) -> tuple[NDArray, dict[str, Any]]:
    """Extract the proper source-to-crop rotation without image-Y or mirror flips.

    Shared by static reconstruction and realtime pose. The affine translation is
    deliberately unused; neither this rotation nor a zero API translation proves
    a calibrated, metric camera pose.
    """
    projection = _finite(projection, "Projection", (3, 4))
    block = projection[:, :3]
    # Normalizing before SVD prevents the camera's arbitrary common scale from
    # determining numerical thresholds or overflowing determinant calculations.
    amplitude = float(np.max(np.abs(block)))
    if amplitude == 0:
        raise ValueError("Projection rotation block must be nonsingular.")
    normalized = block / amplitude
    left, singular, right = np.linalg.svd(normalized)
    if singular[-1] <= singular[0] * 1e-6:
        raise ValueError("Projection rotation block is singular or ill-conditioned.")
    rotation = left @ right
    if float(np.linalg.det(rotation)) <= 0:
        raise ValueError("Projection contains a reflection; a proper pose cannot be inferred.")
    stretch = rotation.T @ block
    uniform_scale = float(np.mean(singular) * amplitude)
    relative_residual = float(np.linalg.norm(block / uniform_scale - rotation, ord="fro"))
    return rotation, {
        "decomposition": "right_polar_svd",
        "uniform_scale_source_to_crop": uniform_scale,
        "stretch_source_to_crop": stretch.reshape(-1).tolist(),
        "singular_values_source_to_crop": (singular * amplitude).tolist(),
        "scale_shear_relative_frobenius_residual": relative_residual,
        "rotation_applied_to_mesh": False,
        "translation_semantics": "zero_unestimated_metric_translation",
    }


def _encode_glb(
    vertices: NDArray, normals: NDArray, triangles: NDArray, extras: dict[str, Any]
) -> bytes:
    positions_bytes = vertices.astype("<f4", copy=False).tobytes(order="C")
    normals_bytes = normals.astype("<f4", copy=False).tobytes(order="C")
    indices_bytes = triangles.astype("<u4", copy=False).tobytes(order="C")
    binary = positions_bytes + normals_bytes + indices_bytes
    document = {
        "asset": {"version": "2.0", "generator": "AgeMorph3D static canonical v1"},
        "scene": 0,
        "scenes": [{"nodes": [0], "extras": extras}],
        "nodes": [{"mesh": 0, "name": "Canonical_Static_Face"}],
        "meshes": [
            {
                "name": "Canonical_Static_Face",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "Neutral_Surface",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.64, 0.67, 0.70, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.85,
                },
                "doubleSided": False,
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions_bytes), "target": 34962},
            {
                "buffer": 0,
                "byteOffset": len(positions_bytes),
                "byteLength": len(normals_bytes),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": len(positions_bytes) + len(normals_bytes),
                "byteLength": len(indices_bytes),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": vertices.min(axis=0).tolist(),
                "max": vertices.max(axis=0).tolist(),
            },
            {"bufferView": 1, "componentType": 5126, "count": len(normals), "type": "VEC3"},
            {
                "bufferView": 2,
                "componentType": 5125,
                "count": triangles.size,
                "type": "SCALAR",
            },
        ],
        "extras": extras,
    }
    encoded = json.dumps(document, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_METADATA_BYTES:
        raise ValueError("GLB metadata exceeds its bounded JSON budget.")
    encoded += b" " * (-len(encoded) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(encoded) + 8 + len(binary)
    if total > MAX_GLB_BYTES:
        raise ValueError("Static GLB exceeds the 64 MiB asset budget.")
    return b"".join(
        (
            struct.pack("<4sII", b"glTF", 2, total),
            struct.pack("<I4s", len(encoded), b"JSON"),
            encoded,
            struct.pack("<I4s", len(binary), b"BIN\0"),
            binary,
        )
    )


def build_static_mesh(result: TddfaResult, source_age: dict[str, Any]) -> StaticMesh:
    """Validate a raw BFM result and encode its canonical static surface in memory.

    The caller owns model/license readiness, image decoding and request admission.
    This function performs no model loading, filesystem writes or license override.
    Import this optional-NumPy module only on the inference worker path.
    """
    age = SourceAge.model_validate(source_age).model_dump(mode="json")
    if result.coordinate_system != "bfm_model_raw":
        raise ValueError("Static canonicalization requires raw pre-projection BFM coordinates.")
    if not isinstance(result.topology_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", result.topology_sha256
    ):
        raise ValueError("Source topology must have a complete lowercase SHA-256 identifier.")
    source = _finite(result.vertices, "Vertices")
    if source.ndim != 2 or source.shape[1] != 3 or not 3 <= len(source) <= _MAX_VERTICES:
        raise ValueError("Vertices must have bounded nonempty shape (N,3).")
    faces = np.asarray(result.triangles)
    if (
        faces.dtype.kind not in "iu"
        or faces.ndim != 2
        or faces.shape[1] != 3
        or not 1 <= len(faces) <= _MAX_FACES
        or np.any(faces < 0)
        or np.any(faces >= len(source))
    ):
        raise ValueError("Faces must contain bounded zero-based integer vertex triplets.")
    if np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0):
        raise ValueError("A face cannot repeat a vertex identifier.")
    if len(source) * 24 + faces.size * 4 + _MAX_METADATA_BYTES + 32 > MAX_GLB_BYTES:
        raise ValueError("Static GLB exceeds the 64 MiB asset budget.")
    projection = _finite(result.projection, "Projection", (3, 4))
    roi = _finite(result.roi, "Source ROI", (4,))
    if roi[2] <= roi[0] or roi[3] <= roi[1]:
        raise ValueError("Source ROI must have positive width and height.")
    rotation, projection_metadata = projection_rotation(projection)
    minimum, maximum = source.min(axis=0), source.max(axis=0)
    extent = maximum - minimum
    if not np.isfinite(extent).all() or extent[1] <= 0:
        raise ValueError("Source mesh must have finite positive bounding-box height.")
    center = minimum + extent / 2
    scale = 1.0 / float(extent[1])
    with np.errstate(over="ignore", invalid="ignore"):
        vertices = np.array((source - center) * scale, dtype="<f4", order="C")
    if not np.isfinite(vertices).all():
        raise ValueError("Canonical vertices must fit finite float32 coordinates.")
    # Fixed reversal established against the source topology; never reorder faces
    # or vertices and never choose winding per request by a view-dependent guess.
    triangles = np.array(faces[:, [0, 2, 1]], dtype="<u4", order="C")
    precise = vertices.astype(np.float64)
    face_normals = np.cross(
        precise[triangles[:, 1]] - precise[triangles[:, 0]],
        precise[triangles[:, 2]] - precise[triangles[:, 0]],
    )
    lengths = np.linalg.norm(face_normals, axis=1)
    if not np.isfinite(lengths).all() or np.any(lengths <= 1e-15):
        raise ValueError("Canonical faces must have nonzero finite area after float32 encoding.")
    if float(face_normals[:, 2].sum()) <= 0:
        raise ValueError("Source winding is inconsistent with the supported +Z-front BFM topology.")
    accumulated = np.zeros_like(precise)
    for corner in range(3):
        np.add.at(accumulated, triangles[:, corner], face_normals)
    lengths = np.linalg.norm(accumulated, axis=1)
    if not np.isfinite(lengths).all() or np.any(lengths <= 1e-15):
        raise ValueError("Every vertex must have a nonzero area-weighted normal.")
    normals = np.array(accumulated / lengths[:, None], dtype="<f4", order="C")
    topology_id = _TOPOLOGY_PREFIX + result.topology_sha256
    pose = {"R": rotation.reshape(-1).tolist(), "t": [0.0, 0.0, 0.0]}
    coordinates = {
        "version": "agemorph3d-static-canonical-v1",
        "source_coordinate_system": "bfm_model_raw",
        "canonical_axes": {"x": "frontal_image_right", "y": "up", "z": "face_front"},
        "axis_rotation_row_major": np.eye(3).reshape(-1).tolist(),
        "canonical_unit": "dimensionless",
        "source_units": "unverified",
        "metric_scale_verified": False,
        "normalization": "source_bbox_height_to_one",
        "source_center": center.tolist(),
        "source_bbox_height": float(extent[1]),
        "source_to_canonical_uniform_scale": scale,
        "transform": "canonical=(source-source_center)*source_to_canonical_uniform_scale",
        "glTF_unit_semantics": "normalized_display_object_not_measured_human_metres",
        "source_topology_sha256": result.topology_sha256,
        "winding": "source_face_a_b_c_to_a_c_b",
        "vertex_order_preserved": True,
        "face_order_preserved": True,
        "source_projection_row_major": projection.reshape(-1).tolist(),
        "source_roi": roi.tolist(),
        "pose": projection_metadata,
    }
    extras = {
        "asset_mode": "static",
        "source_age": age,
        "topology_id": topology_id,
        "coordinate_metadata": coordinates,
    }
    glb = _encode_glb(vertices, normals, triangles, extras)
    for array in (vertices, normals, triangles):
        array.setflags(write=False)
    return StaticMesh(glb, topology_id, pose, coordinates, vertices, normals, triangles)
