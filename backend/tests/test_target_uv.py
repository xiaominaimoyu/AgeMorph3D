"""Synthetic target-camera/mask/UV checks; not age-texture quality acceptance."""

import hashlib
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("onnxruntime")

from agemorph3d import uv_texture  # noqa: E402
from agemorph3d.target_uv import (  # noqa: E402
    register_generated_texture,
    texture_boundary_diagnostics,
)
from agemorph3d.tddfa import TddfaResult  # noqa: E402
from agemorph3d.uv_texture import UV_REASON_CODES, UvTexture, project_photo_texture  # noqa: E402


@pytest.fixture
def scene():
    yy, xx = np.mgrid[:16, :16]
    rgb = np.stack((xx * 10, yy * 10, xx * 3 + yy), axis=-1).astype(np.uint8)
    raw = TddfaResult(
        shape=np.zeros(40, dtype=np.float32),
        expr=np.zeros(10, dtype=np.float32),
        vertices=np.array([[2, 115, 0], [10, 115, 0], [2, 107, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int64),
        projection=np.eye(3, 4, dtype=np.float32),
        roi=(0.0, 0.0, 120.0, 120.0),
        topology_sha256="ab" * 32,
    )
    uv = np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float32)
    return rgb, raw, uv


def register(scene, **kwargs):
    rgb, raw, uv = scene
    return register_generated_texture(rgb, raw, uv, np.ones(rgb.shape[:2], dtype=bool), **kwargs)


def assert_partition(texture):
    counts = texture.metadata["classification_counts"]
    assert sum(counts.values()) == texture.coverage.size
    assert set(counts) == set(UV_REASON_CODES)
    for name, code in UV_REASON_CODES.items():
        assert counts[name] == np.count_nonzero(texture.classification == code)
    np.testing.assert_array_equal(
        texture.coverage, texture.classification == UV_REASON_CODES["sampled"]
    )
    assert np.all(texture.rgba[~texture.coverage] == 0)


def test_each_target_uses_its_own_projection_with_independent_expected_colors(scene):
    rgb, raw, uv = scene
    original = register(scene, atlas_size=4)
    projection = raw.projection.copy()
    projection[0, 3] += 2
    shifted = register((rgb, replace(raw, projection=projection), uv), atlas_size=4)
    np.testing.assert_array_equal(original.rgba[0, 0], [20, 60, 12, 255])
    np.testing.assert_array_equal(shifted.rgba[0, 0], [40, 60, 18, 255])
    np.testing.assert_array_equal(shifted.gltf_uv, original.gltf_uv)
    assert not np.array_equal(original.rgba, shifted.rgba)


def test_target_expression_geometry_is_not_replaced_by_neutral_vertices(scene):
    rgb, raw, uv = scene
    moved = replace(raw, vertices=raw.vertices + np.array([2, 0, 0], dtype=np.float32))
    output = register((rgb, moved, uv), atlas_size=4)
    np.testing.assert_array_equal(output.rgba[0, 0], [40, 60, 18, 255])


def test_subpixel_mask_uses_every_contributor_before_color_sampling(scene, monkeypatch):
    rgb, raw, uv = scene
    projection = raw.projection.copy()
    projection[0, 3] = 0.25
    raw = replace(raw, projection=projection)
    allowed = np.ones(rgb.shape[:2], dtype=bool)
    allowed[6, 3] = False  # Texel(0,0) samples x=2.25,y=6: masked right pixel contributes.
    calls = []
    original = uv_texture._bilinear

    def sampled(image, xy):
        calls.extend(xy.tolist())
        return original(image, xy)

    monkeypatch.setattr(uv_texture, "_bilinear", sampled)
    texture = register_generated_texture(rgb, raw, uv, allowed, atlas_size=4)
    assert texture.classification[0, 0] == UV_REASON_CODES["mask_rejected"]
    np.testing.assert_array_equal(texture.rgba[0, 0], [0, 0, 0, 0])
    assert [2.25, 6.0] not in calls
    assert_partition(texture)


def test_zero_weight_neighbor_does_not_reject_exact_pixel_center(scene):
    rgb, raw, uv = scene
    allowed = np.ones(rgb.shape[:2], dtype=bool)
    allowed[6, 3] = False
    texture = register_generated_texture(rgb, raw, uv, allowed, atlas_size=4)
    np.testing.assert_array_equal(texture.rgba[0, 0], [20, 60, 12, 255])


def test_all_false_mask_produces_only_unknown_rgba_without_filling(scene):
    rgb, raw, uv = scene
    texture = register_generated_texture(rgb, raw, uv, np.zeros(rgb.shape[:2], dtype=bool), 8)
    assert not texture.coverage.any()
    assert np.all(texture.rgba == 0)
    assert texture.metadata["mask_rejected_texels"] > 0
    assert texture.metadata["boundary_diagnostics"]["neighbor_rgb_mean_abs_channel_jump"] is None
    assert_partition(texture)


@pytest.mark.parametrize("kind", ["missing", "uint8", "float", "shape", "list"])
def test_generated_mask_is_required_boolean_and_target_local(scene, kind):
    rgb, raw, uv = scene
    masks = {
        "missing": None,
        "uint8": np.ones(rgb.shape[:2], dtype=np.uint8),
        "float": np.ones(rgb.shape[:2]),
        "shape": np.ones((8, 8), dtype=bool),
        "list": [[True]],
    }
    with pytest.raises(ValueError, match="mask"):
        register_generated_texture(rgb, raw, uv, masks[kind], 8)


def test_unmasked_photo_behavior_and_old_texture_constructor_remain_compatible(scene):
    rgb, raw, uv = scene
    plain = project_photo_texture(rgb, raw, uv, atlas_size=4)
    allowed = project_photo_texture(
        rgb, raw, uv, atlas_size=4, sample_allowed_mask=np.ones((16, 16), bool)
    )
    np.testing.assert_array_equal(plain.rgba, allowed.rgba)
    assert plain.png == allowed.png
    assert not plain.metadata["sample_allowed_mask_applied"]
    legacy = UvTexture(plain.gltf_uv, plain.rgba, plain.png, plain.coverage, plain.metadata)
    assert legacy.classification is None
    assert plain.metadata["age_generated"] is False


def test_generated_provenance_does_not_claim_original_observations_or_quality(scene):
    texture = register(scene, atlas_size=8)
    metadata = texture.metadata
    assert not any(name.startswith("observed_") for name in metadata)
    assert metadata["input_kind"] == "sam_generated_target_image"
    assert metadata["age_generated"]
    assert metadata["projection_source"] == "target_raw_projection_and_roi"
    assert not metadata["external_occlusion_detection"]
    assert not metadata["identity_quality_accepted"]
    assert not metadata["age_texture_quality_accepted"]
    assert not metadata["generated_pixels_are_original_observations"]
    assert not metadata["mask_rejection_is_external_occlusion_measurement"]
    assert "unsupported/conservatively excluded" in metadata["mask_rejection_semantics"]
    assert metadata["registered_generated_texels"] == texture.coverage.sum()
    assert len(metadata["target_allowed_mask_array_sha256"]) == 64
    assert metadata["target_allowed_mask_array_sha256"] == hashlib.sha256(b"\x01" * 256).hexdigest()
    assert metadata["target_allowed_mask_array_encoding"] == "uint8_0_1_row_major"
    assert "target_allowed_mask_sha256" not in metadata
    assert_partition(texture)


def test_self_occluded_back_facing_outside_and_overlap_have_distinct_reasons(scene):
    rgb, raw, uv = scene
    self_hidden = replace(
        raw,
        vertices=np.concatenate([raw.vertices, raw.vertices + [0, 0, 10]]).astype(np.float32),
        triangles=np.array([[0, 1, 2], [3, 4, 5]]),
    )
    doubled_uv = np.array([[0, 1], [0.5, 1], [0, 0], [0.5, 1], [1, 1], [1, 0]])
    hidden = register((rgb, self_hidden, doubled_uv), atlas_size=16)
    assert hidden.metadata["classification_counts"]["self_occluded"] > 0
    back = register((rgb, replace(raw, triangles=raw.triangles[:, ::-1]), uv), atlas_size=8)
    assert back.metadata["classification_counts"]["back_facing"] > 0
    outside = register((rgb, replace(raw, vertices=raw.vertices + [1000, 0, 0]), uv), atlas_size=8)
    assert outside.metadata["classification_counts"]["outside_image"] > 0
    overlap = register((rgb, self_hidden, np.concatenate([uv, uv])), atlas_size=8)
    assert overlap.metadata["classification_counts"]["ambiguous_uv_overlap"] > 0
    for texture in (hidden, back, outside, overlap):
        assert_partition(texture)


def test_shared_indexed_edge_has_no_hole_and_linear_rgb_jump_is_descriptive(scene):
    rgb, raw, _ = scene
    raw = replace(
        raw,
        vertices=np.array([[2, 115, 0], [10, 115, 0], [10, 107, 0], [2, 107, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2], [0, 2, 3]]),
    )
    uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], dtype=np.float32)
    texture = register((rgb, raw, uv), atlas_size=8)
    yy, xx = np.mgrid[:8, :8]
    expected = np.stack((15 + xx * 10, 55 + yy * 10, 10 + xx * 3 + yy), axis=-1)
    np.testing.assert_array_equal(texture.rgba[:, :, :3], expected)
    assert texture.coverage.all()
    diagnostics = texture.metadata["boundary_diagnostics"]
    assert diagnostics["indexed_shared_edges"] == 1
    assert diagnostics["indexed_boundary_edges"] == 4
    assert diagnostics["indexed_nonmanifold_edges"] == 0
    assert diagnostics["shared_indexed_edge_uv_continuous"]
    assert diagnostics["coverage_boundary_neighbor_pairs"] == 0
    assert diagnostics["neighbor_rgb_mean_abs_channel_jump"] == pytest.approx(4)
    assert diagnostics["neighbor_rgb_max_abs_channel_jump"] == 10
    assert not diagnostics["visual_seam_quality_accepted"]


def test_alpha_boundaries_stay_transparent_black_without_blending(scene):
    rgb, raw, uv = scene
    allowed = np.ones(rgb.shape[:2], dtype=bool)
    allowed[:, 5:] = False
    texture = register_generated_texture(rgb, raw, uv, allowed, atlas_size=8)
    diagnostics = texture.metadata["boundary_diagnostics"]
    assert diagnostics["coverage_boundary_neighbor_pairs"] > 0
    assert diagnostics["unknown_rgba_zero"]
    assert diagnostics["alpha_coverage_matches"]
    assert diagnostics["nonbinary_alpha_texels"] == 0
    assert not diagnostics["unknown_filling_or_boundary_blending"]
    np.testing.assert_array_equal(np.asarray(Image.open(BytesIO(texture.png))), texture.rgba)


def test_common_uv_tampering_is_rejected_by_boundary_diagnostics(scene):
    texture = register(scene, atlas_size=8)
    _, raw, uv = scene
    changed = uv.copy()
    changed[0, 0] = 0.1
    with pytest.raises(ValueError, match="common atlas"):
        texture_boundary_diagnostics(texture, changed, raw.triangles)


def test_inputs_and_all_returned_maps_remain_immutable(scene):
    rgb, raw, uv = scene
    mask = np.ones(rgb.shape[:2], dtype=bool)
    before = [array.copy() for array in (rgb, raw.vertices, raw.projection, uv, mask)]
    texture = register_generated_texture(rgb, raw, uv, mask, atlas_size=8)
    for array, previous in zip((rgb, raw.vertices, raw.projection, uv, mask), before, strict=True):
        np.testing.assert_array_equal(array, previous)
    for array in (texture.gltf_uv, texture.rgba, texture.coverage, texture.classification):
        assert not array.flags.writeable


@pytest.mark.parametrize("size", [True, 3, 1025, 4.5])
def test_generated_registration_keeps_existing_atlas_budget_checks(scene, size):
    with pytest.raises(ValueError, match="atlas size"):
        register(scene, atlas_size=size)


def test_generated_registration_keeps_visibility_work_budget(scene, monkeypatch):
    monkeypatch.setattr(uv_texture, "_MAX_DEPTH_PAIRS", 0)
    with pytest.raises(ValueError, match="visibility work budget"):
        register(scene, atlas_size=8)
