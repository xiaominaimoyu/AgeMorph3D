"""Observed original-photo UV texture; no aging or unseen-surface completion.

Input UV is the official BFM ``UV[indices]`` in bottom-left coordinates. PNG rows
and returned glTF UV are top-left. Samples use exact triangle barycentrics and
bilinear source RGB. A spatially binned, continuous-coordinate max-Z depth test
rejects self-occluded samples instead of painting hidden facial surfaces. This
cannot detect an external occluder (hair, glasses, hand) absent from the mesh.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from .tddfa import project_vertices

if TYPE_CHECKING:
    from .tddfa import TddfaResult

_MAX_VERTICES = 200_000
_MAX_TRIANGLES = 300_000
_MAX_BIN_REFERENCES = 4_000_000
_MAX_DEPTH_PAIRS = 128_000_000
_MAX_UV_SAMPLE_WORK = 16_000_000
_BIN_SIZE = 4


@dataclass(frozen=True)
class UvTexture:
    gltf_uv: NDArray[np.float32]
    rgba: NDArray[np.uint8]
    png: bytes
    coverage: NDArray[np.bool_]
    metadata: dict[str, Any]


def _array(value: object, name: str, shape: tuple[int, ...] | None = None) -> NDArray:
    result = np.asarray(value)
    if result.dtype.kind not in "iuf" or not np.isfinite(result).all():
        raise ValueError(f"{name} must contain finite real numbers.")
    if shape is not None and result.shape != shape:
        raise ValueError(f"{name} has an incompatible shape.")
    return np.array(result, dtype=np.float64, copy=True, order="C")


def _area(points: NDArray) -> NDArray:
    first, second = points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]
    return first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]


def _weights(points: NDArray, triangle: NDArray, area: NDArray) -> NDArray:
    """Broadcast points and triangle arrays, keeping the three barycentric weights."""
    delta = points - triangle[..., 0, :2]
    edge1 = triangle[..., 1, :2] - triangle[..., 0, :2]
    edge2 = triangle[..., 2, :2] - triangle[..., 0, :2]
    second = (delta[..., 0] * edge2[..., 1] - delta[..., 1] * edge2[..., 0]) / area
    third = (edge1[..., 0] * delta[..., 1] - edge1[..., 1] * delta[..., 0]) / area
    return np.stack((1 - second - third, second, third), axis=-1)


def _uv_samples(uv: NDArray, faces: NDArray, size: int) -> tuple[NDArray, NDArray, NDArray]:
    """Rasterize UV texel centers; ambiguous overlapping interiors remain unknown."""
    coordinates = uv * size
    mapped = coordinates[faces]
    areas = _area(mapped)
    owner = np.full((size, size), -1, dtype=np.int32)
    weights = np.zeros((size, size, 3), dtype=np.float64)
    ambiguous = np.zeros((size, size), dtype=bool)
    work = 0
    for index, (triangle, area) in enumerate(zip(mapped, areas, strict=True)):
        if abs(area) < 1e-12:
            continue
        lower = np.maximum(0, np.ceil(triangle.min(axis=0) - 0.5)).astype(int)
        upper = np.minimum(size - 1, np.floor(triangle.max(axis=0) - 0.5)).astype(int)
        if np.any(upper < lower):
            continue
        work += int(np.prod(upper - lower + 1))
        if work > _MAX_UV_SAMPLE_WORK:
            raise ValueError("UV overlap exceeds the bounded rasterization work budget.")
        xx, yy = np.meshgrid(np.arange(lower[0], upper[0] + 1), np.arange(lower[1], upper[1] + 1))
        bary = _weights(np.stack((xx + 0.5, yy + 0.5), axis=-1), triangle, area)
        inside = np.all(bary >= -1e-10, axis=-1)
        interior = np.all(bary > 1e-9, axis=-1)
        old = owner[yy, xx]
        # Shared triangle edges are harmless. Two distinct interiors indicate a
        # folded/overlapping atlas, for which a single texel is not unambiguous.
        overlap = inside & interior & (old >= 0) & np.all(weights[yy, xx] > 1e-9, axis=-1)
        ambiguous[yy[overlap], xx[overlap]] = True
        take = inside & (old < 0)
        owner[yy[take], xx[take]] = index
        weights[yy[take], xx[take]] = bary[take]
    return owner, weights, ambiguous


def _visible(projected: NDArray, faces: NDArray, queries: NDArray, width: int, height: int):
    """Exact max-Z z buffer evaluated at the UV samples' continuous source XY."""
    if not len(queries):
        return np.zeros(0, dtype=bool), 0
    triangles = projected[faces]
    areas = _area(triangles)
    bins: dict[tuple[int, int], list[int]] = {}
    references = 0
    for index, (triangle, area) in enumerate(zip(triangles, areas, strict=True)):
        if abs(area) < 1e-12:
            continue
        lower = np.maximum([0, 0], np.floor(triangle[:, :2].min(axis=0)))
        upper = np.minimum([width - 1, height - 1], np.ceil(triangle[:, :2].max(axis=0)))
        if np.any(upper < lower):
            continue
        # Convert only after intersection: huge but finite off-image projections
        # must not overflow integer coordinates or construct enormous bin ranges.
        lower, upper = lower.astype(int), upper.astype(int)
        first, last = lower // _BIN_SIZE, upper // _BIN_SIZE
        references += int(np.prod(last - first + 1))
        if references > _MAX_BIN_REFERENCES:
            raise ValueError("Projection exceeds the bounded visibility work budget.")
        for y in range(first[1], last[1] + 1):
            for x in range(first[0], last[0] + 1):
                bins.setdefault((x, y), []).append(index)
    answer = np.zeros(len(queries), dtype=bool)
    groups: dict[tuple[int, int], list[int]] = {}
    for index, query in enumerate(queries):
        groups.setdefault((int(query[0]) // _BIN_SIZE, int(query[1]) // _BIN_SIZE), []).append(
            index
        )
    pairs = 0
    epsilon = max(1e-6, float(np.ptp(projected[:, 2])) * 1e-6)
    for key, indices in groups.items():
        candidates = np.asarray(bins.get(key, ()), dtype=np.int64)
        pairs += len(indices) * len(candidates)
        if pairs > _MAX_DEPTH_PAIRS:
            raise ValueError("Projection exceeds the bounded visibility work budget.")
        if not len(candidates):
            continue
        for offset in range(0, len(indices), 64):
            batch = np.asarray(indices[offset : offset + 64], dtype=np.int64)
            depths = np.full(len(batch), -np.inf)
            for start in range(0, len(candidates), 1024):
                chosen = candidates[start : start + 1024]
                bary = _weights(
                    queries[batch, None, :2], triangles[chosen][None], areas[None, chosen]
                )
                inside = np.all(bary >= -1e-8, axis=-1)
                values = np.sum(bary * triangles[chosen][None, :, :, 2], axis=-1)
                values[~inside] = -np.inf
                depths = np.maximum(depths, values.max(axis=1))
            answer[batch] = np.isfinite(depths) & (queries[batch, 2] >= depths - epsilon)
    return answer, pairs


def _bilinear(rgb: NDArray, xy: NDArray) -> NDArray:
    x0, y0 = np.floor(xy[:, 0]).astype(int), np.floor(xy[:, 1]).astype(int)
    x1, y1 = np.minimum(x0 + 1, rgb.shape[1] - 1), np.minimum(y0 + 1, rgb.shape[0] - 1)
    dx, dy = (xy[:, 0] - x0)[:, None], (xy[:, 1] - y0)[:, None]
    result = (
        rgb[y0, x0] * (1 - dx) * (1 - dy)
        + rgb[y0, x1] * dx * (1 - dy)
        + rgb[y1, x0] * (1 - dx) * dy
        + rgb[y1, x1] * dx * dy
    )
    return np.clip(np.rint(result), 0, 255).astype(np.uint8)


def project_photo_texture(
    rgb: NDArray[np.uint8], result: TddfaResult, uv: NDArray, *, atlas_size: int = 256
) -> UvTexture:
    """Project only observed source-photo surface, keeping unknown texels transparent.

    UV preserves original vertex order. Visibility is based on native winding
    (image-space positive signed area) and greatest projected Z. This applies to
    the verified raw BFM / upstream 3DDFA affine projection, not arbitrary cameras.
    No photos, textures, assets or reports are written by this function.
    """
    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or min(rgb.shape[:2]) < 1
        or rgb.shape[0] * rgb.shape[1] > 16_000_000
    ):
        raise ValueError("Photo must be a bounded nonempty uint8 RGB image.")
    if type(atlas_size) is not int or not 4 <= atlas_size <= 1024:
        raise ValueError("UV atlas size must be an integer from 4 to 1024.")
    if result.coordinate_system != "bfm_model_raw":
        raise ValueError("Photo projection requires raw pre-projection BFM coordinates.")
    vertices = _array(result.vertices, "Vertices")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not 3 <= len(vertices) <= _MAX_VERTICES:
        raise ValueError("Vertices must have bounded shape (N,3).")
    input_uv = _array(uv, "UV", (len(vertices), 2))
    if np.any(input_uv < 0) or np.any(input_uv > 1):
        raise ValueError("UV must stay within the single [0,1] atlas.")
    faces = np.asarray(result.triangles)
    if (
        faces.dtype.kind not in "iu"
        or faces.ndim != 2
        or faces.shape[1] != 3
        or not 1 <= len(faces) <= _MAX_TRIANGLES
        or np.any(faces < 0)
        or np.any(faces >= len(vertices))
        or np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0)
    ):
        raise ValueError("Faces must be bounded zero-based distinct vertex triplets.")
    projection = _array(result.projection, "Projection", (3, 4))
    block = projection[:, :3]
    magnitude = float(np.max(np.abs(block)))
    if magnitude == 0:
        raise ValueError("Projection must have a nonsingular proper affine block.")
    singular = np.linalg.svd(block / magnitude, compute_uv=False)
    if singular[-1] <= singular[0] * 1e-6 or np.linalg.det(block / magnitude) <= 0:
        raise ValueError("Projection must have a nonsingular proper affine block.")
    roi = _array(result.roi, "ROI", (4,))
    if roi[2] <= roi[0] or roi[3] <= roi[1]:
        raise ValueError("ROI must have positive width and height.")
    projected = project_vertices(result).astype(np.float64)
    gltf_uv = input_uv.copy()
    gltf_uv[:, 1] = 1 - gltf_uv[:, 1]
    owner, bary, ambiguous = _uv_samples(gltf_uv, faces, atlas_size)
    atlas_mask = owner >= 0
    sample_mask = atlas_mask & ~ambiguous
    yy, xx = np.where(sample_mask)
    face_ids = owner[yy, xx]
    screen_triangles = projected[faces]
    samples = np.sum(bary[yy, xx, :, None] * screen_triangles[face_ids], axis=1)
    front = _area(screen_triangles)[face_ids] > 1e-10
    in_image = (
        (samples[:, 0] >= 0)
        & (samples[:, 0] <= rgb.shape[1] - 1)
        & (samples[:, 1] >= 0)
        & (samples[:, 1] <= rgb.shape[0] - 1)
    )
    candidates = front & in_image
    visible = np.zeros(len(samples), dtype=bool)
    visible[candidates], depth_pairs = _visible(
        projected, faces, samples[candidates], rgb.shape[1], rgb.shape[0]
    )
    coverage = np.zeros((atlas_size, atlas_size), dtype=bool)
    coverage[yy[visible], xx[visible]] = True
    rgba = np.zeros((atlas_size, atlas_size, 4), dtype=np.uint8)
    rgba[yy[visible], xx[visible], :3] = _bilinear(rgb, samples[visible, :2])
    rgba[coverage, 3] = 255
    output = BytesIO()
    Image.fromarray(rgba).save(output, format="PNG")
    gltf_uv = np.array(gltf_uv, dtype="<f4", order="C")
    metadata = {
        "version": "agemorph3d-observed-photo-uv-v1",
        "input_uv_origin": "bottom_left_BFM_UV_indices",
        "gltf_uv_origin": "top_left",
        "uv_transform": "gltf_uv=(u,1-v); original_vertex_order",
        "uv_array_sha256": hashlib.sha256(input_uv.astype("<f4").tobytes()).hexdigest(),
        "atlas_size": atlas_size,
        "atlas_texel_sample": "center=(column+0.5,row+0.5)/size",
        "atlas_face_texels": int(atlas_mask.sum()),
        "ambiguous_overlap_texels": int(ambiguous.sum()),
        "observed_texels": int(coverage.sum()),
        "observed_fraction_of_atlas": float(coverage.mean()),
        "observed_fraction_of_face": float(coverage.sum() / max(1, atlas_mask.sum())),
        "front_facing_in_image_texels": int(candidates.sum()),
        "self_occluded_texels": int(candidates.sum() - visible.sum()),
        "depth_test_pairs": depth_pairs,
        "visibility": "native_front_faces_and_continuous_max_projected_z",
        "rgb_sampling": "bilinear_original_EXIF_corrected_unmirrored_RGB",
        "unknown_surface": "RGBA_zero_no_fill_no_symmetry_no_inpainting",
        "external_occlusion_detection": False,
        "lighting_removed": False,
        "age_generated": False,
        "identity_evaluation": "not_established_by_photo_projection",
    }
    for array in (gltf_uv, rgba, coverage):
        array.setflags(write=False)
    return UvTexture(gltf_uv, rgba, output.getvalue(), coverage, metadata)
