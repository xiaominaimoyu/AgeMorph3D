"""Offline generated-target registration to the existing common BFM UV atlas.

Target pixels use their own fitted expression and camera. An explicit target
mask is eligibility evidence supplied by the caller, never a segmentation or
external-occlusion detector. Generated samples are not original observations.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from .uv_texture import UV_REASON_CODES, UvTexture, project_photo_texture

if TYPE_CHECKING:
    from .tddfa import TddfaResult


def texture_boundary_diagnostics(
    texture: UvTexture, common_uv: np.ndarray, triangles: np.ndarray
) -> dict:
    """Describe indexed UV continuity and alpha boundaries without quality gates.

    A single UV per vertex makes a shared indexed edge continuous by definition.
    This cannot detect coincident vertices with separate IDs or establish visual
    seam/occlusion quality. Neighbor RGB jumps also include legitimate gradients.
    """
    uv = np.asarray(common_uv)
    faces = np.asarray(triangles)
    if (
        uv.dtype.kind not in "iuf"
        or uv.ndim != 2
        or uv.shape[1] != 2
        or len(uv) < 3
        or not np.isfinite(uv).all()
        or np.any(uv < 0)
        or np.any(uv > 1)
    ):
        raise ValueError("Common UV must be finite (N,2) coordinates in [0,1].")
    if (
        faces.dtype.kind not in "iu"
        or faces.ndim != 2
        or faces.shape[1] != 3
        or not len(faces)
        or np.any(faces < 0)
        or np.any(faces >= len(uv))
        or np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0)
    ):
        raise ValueError("Triangles must be ordered distinct vertex triplets in the UV range.")
    expected_uv = np.asarray(uv, dtype=np.float64).copy()
    expected_uv[:, 1] = 1 - expected_uv[:, 1]
    if not np.array_equal(texture.gltf_uv, expected_uv.astype(np.float32)):
        raise ValueError("Texture UV differs from the common atlas and its fixed vertical flip.")
    rgba, covered = np.asarray(texture.rgba), np.asarray(texture.coverage)
    if (
        rgba.dtype != np.uint8
        or rgba.ndim != 3
        or rgba.shape[2] != 4
        or min(rgba.shape[:2]) < 1
        or covered.dtype != np.bool_
        or covered.shape != rgba.shape[:2]
    ):
        raise ValueError("Texture must contain uint8 RGBA and matching boolean coverage.")
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    boundary_pairs = int(np.count_nonzero(covered[:, 1:] != covered[:, :-1]))
    boundary_pairs += int(np.count_nonzero(covered[1:] != covered[:-1]))
    jump_sum, jump_values, jump_max = 0.0, 0, 0
    for first, second, allowed in (
        (rgba[:, 1:, :3], rgba[:, :-1, :3], covered[:, 1:] & covered[:, :-1]),
        (rgba[1:, :, :3], rgba[:-1, :, :3], covered[1:] & covered[:-1]),
    ):
        delta = np.abs(first[allowed].astype(np.int16) - second[allowed].astype(np.int16))
        if delta.size:
            jump_sum += float(delta.sum())
            jump_values += int(delta.size)
            jump_max = max(jump_max, int(delta.max()))
    return {
        "indexed_shared_edges": int(np.count_nonzero(counts == 2)),
        "indexed_boundary_edges": int(np.count_nonzero(counts == 1)),
        "indexed_nonmanifold_edges": int(np.count_nonzero(counts > 2)),
        "shared_indexed_edge_uv_continuous": True,
        "uv_continuity_scope": "one UV per vertex index; coincident separate IDs not assessed",
        "ambiguous_overlap_texels": texture.metadata.get("ambiguous_overlap_texels"),
        "alpha_coverage_matches": bool(np.array_equal(covered, rgba[:, :, 3] == 255)),
        "nonbinary_alpha_texels": int(
            np.count_nonzero((rgba[:, :, 3] != 0) & (rgba[:, :, 3] != 255))
        ),
        "transparent_texels": int(np.count_nonzero(~covered)),
        "unknown_rgba_zero": bool(np.all(rgba[~covered] == 0)),
        "coverage_boundary_neighbor_pairs": boundary_pairs,
        "registered_neighbor_pairs": jump_values // 3,
        "neighbor_rgb_mean_abs_channel_jump": jump_sum / jump_values if jump_values else None,
        "neighbor_rgb_max_abs_channel_jump": jump_max if jump_values else None,
        "rgb_jump_interpretation": "adjacent RGB jumps; includes legitimate image gradients",
        "unknown_filling_or_boundary_blending": False,
        "visual_seam_quality_accepted": False,
    }


def register_generated_texture(
    rgb: np.ndarray,
    target_raw: TddfaResult,
    common_uv: np.ndarray,
    target_allowed_mask: np.ndarray,
    atlas_size: int = 256,
) -> UvTexture:
    """Use the complete target fit and its own image-local allowed-pixel mask.

    The caller binds image/mask hashes, reconstruction model and ordered topology
    to the source's common UV. The resulting texture does not alter source mesh
    geometry, infer an age, or enable any production capability.
    """
    if target_allowed_mask is None:
        raise ValueError("Generated target registration requires an explicit target allowed mask.")
    texture = project_photo_texture(
        rgb,
        target_raw,
        common_uv,
        atlas_size=atlas_size,
        sample_allowed_mask=target_allowed_mask,
    )
    metadata = {
        key: value for key, value in texture.metadata.items() if not key.startswith("observed_")
    }
    metadata.update(
        version="agemorph3d-generated-target-uv-v1",
        input_kind="sam_generated_target_image",
        age_generated=True,
        original_photo_observation=False,
        registered_generated_texels=int(texture.coverage.sum()),
        registered_generated_fraction_of_atlas=float(texture.coverage.mean()),
        registered_generated_fraction_of_face=float(
            texture.coverage.sum() / max(1, metadata["atlas_face_texels"])
        ),
        rgb_sampling="bilinear_generated_target_RGB_with_its_own_fitted_projection_and_expression",
        projection_source="target_raw_projection_and_roi",
        target_allowed_mask_required=True,
        target_allowed_mask_array_sha256=hashlib.sha256(
            target_allowed_mask.astype(np.uint8).tobytes(order="C")
        ).hexdigest(),
        target_allowed_mask_array_encoding="uint8_0_1_row_major",
        target_allowed_mask_shape=list(target_allowed_mask.shape),
        target_allowed_pixels=int(target_allowed_mask.sum()),
        target_excluded_pixels=int(np.count_nonzero(~target_allowed_mask)),
        target_mask_interpretation="caller eligibility; no automatic external-occlusion detection",
        mask_rejection_semantics=(
            "unsupported/conservatively excluded target pixels, possibly including "
            "reviewed external-occluder candidates"
        ),
        mask_rejection_is_external_occlusion_measurement=False,
        external_occlusion_detection=False,
        identity_quality_accepted=False,
        years_calibrated=False,
        age_texture_quality_accepted=False,
        generated_pixels_are_original_observations=False,
    )
    generated = replace(texture, metadata=metadata)
    metadata["boundary_diagnostics"] = texture_boundary_diagnostics(
        generated, common_uv, target_raw.triangles
    )
    assert generated.classification is not None
    if not np.array_equal(
        generated.coverage, generated.classification == UV_REASON_CODES["sampled"]
    ):
        raise ValueError("Generated atlas coverage must match its sampled classification.")
    return generated
