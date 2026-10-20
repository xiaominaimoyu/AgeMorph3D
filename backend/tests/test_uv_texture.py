"""Numerical UV/projection tests; synthetic geometry is not age/identity evidence."""

from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("onnxruntime")

from agemorph3d import uv_texture  # noqa: E402
from agemorph3d.tddfa import TddfaResult  # noqa: E402
from agemorph3d.uv_texture import project_photo_texture  # noqa: E402


def fixture():
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


def test_asymmetric_rgb_orientation_bilinear_and_png_roundtrip():
    rgb, raw, uv = fixture()
    before = (rgb.copy(), raw.vertices.copy(), uv.copy())
    texture = project_photo_texture(rgb, raw, uv, atlas_size=4)
    np.testing.assert_array_equal(texture.gltf_uv, [[0, 0], [1, 0], [0, 1]])
    # UV texel (.125,.125) maps to source pixel (2,6), independently of implementation.
    np.testing.assert_array_equal(texture.rgba[0, 0], [20, 60, 12, 255])
    np.testing.assert_array_equal(texture.rgba[0, 1], [40, 60, 18, 255])
    np.testing.assert_array_equal(texture.rgba[1, 0], [20, 80, 14, 255])
    np.testing.assert_array_equal(texture.rgba[3, 3], [0, 0, 0, 0])
    np.testing.assert_array_equal(np.asarray(Image.open(BytesIO(texture.png))), texture.rgba)
    np.testing.assert_array_equal(texture.coverage, texture.rgba[:, :, 3] == 255)
    for actual, original in zip((rgb, raw.vertices, uv), before, strict=True):
        np.testing.assert_array_equal(actual, original)
    for array in (texture.gltf_uv, texture.rgba, texture.coverage):
        assert array.flags.writeable is False
    assert texture.metadata["age_generated"] is False
    assert texture.metadata["external_occlusion_detection"] is False
    assert texture.metadata["observed_texels"] == 10


def test_near_larger_z_surface_occludes_far_surface_without_color_filling():
    rgb, raw, _ = fixture()
    vertices = np.concatenate((raw.vertices, raw.vertices + [0, 0, 10])).astype(np.float32)
    raw = replace(raw, vertices=vertices, triangles=np.array([[0, 1, 2], [3, 4, 5]]))
    uv = np.array([[0, 1], [0.5, 1], [0, 0], [0.5, 1], [1, 1], [1, 0]], dtype=np.float32)
    texture = project_photo_texture(rgb, raw, uv, atlas_size=16)
    assert not texture.coverage[:, :8].any()
    assert texture.coverage[:, 8:].any()
    assert texture.metadata["self_occluded_texels"] > 0
    assert np.all(texture.rgba[:, :8] == 0)


def test_shared_uv_edge_has_no_hole_or_color_seam_on_linear_rgb_surface():
    rgb, raw, _ = fixture()
    raw = replace(
        raw,
        vertices=np.array([[2, 115, 0], [10, 115, 0], [10, 107, 0], [2, 107, 0]]),
        triangles=np.array([[0, 1, 2], [0, 2, 3]]),
    )
    uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], dtype=np.float32)
    texture = project_photo_texture(rgb, raw, uv, atlas_size=8)
    yy, xx = np.mgrid[:8, :8]
    expected = np.stack((15 + xx * 10, 55 + yy * 10, 10 + xx * 3 + yy), axis=-1)
    np.testing.assert_array_equal(texture.rgba[:, :, :3], expected)
    assert texture.coverage.all()
    assert texture.metadata["ambiguous_overlap_texels"] == 0


def test_back_faces_and_source_outside_photo_remain_transparent():
    rgb, raw, uv = fixture()
    back = replace(raw, triangles=raw.triangles[:, ::-1])
    texture = project_photo_texture(rgb, back, uv, atlas_size=8)
    assert not texture.coverage.any()
    assert np.all(texture.rgba == 0)
    outside = replace(raw, vertices=raw.vertices + [1000, 0, 0])
    texture = project_photo_texture(rgb, outside, uv, atlas_size=8)
    assert not texture.coverage.any()
    assert np.all(texture.rgba == 0)


def test_disjoint_surface_triangles_overlapping_uv_interiors_are_unknown():
    rgb, raw, uv = fixture()
    raw = replace(
        raw,
        vertices=np.concatenate((raw.vertices, raw.vertices + [1, 0, 1])),
        triangles=np.array([[0, 1, 2], [3, 4, 5]]),
    )
    texture = project_photo_texture(rgb, raw, np.concatenate((uv, uv)), atlas_size=16)
    assert texture.metadata["ambiguous_overlap_texels"] > 0
    yy, xx = np.mgrid[:16, :16]
    assert np.all(texture.rgba[xx + yy < 15] == 0)


@pytest.mark.parametrize("size", [True, 0, 3, 1025, 4.5])
def test_invalid_atlas_size_fails(size):
    rgb, raw, uv = fixture()
    with pytest.raises(ValueError):
        project_photo_texture(rgb, raw, uv, atlas_size=size)


@pytest.mark.parametrize("kind", ["nan", "out_of_range", "wrong_shape", "string"])
def test_invalid_uv_fails(kind):
    rgb, raw, uv = fixture()
    if kind == "nan":
        uv[0, 0] = np.nan
    elif kind == "out_of_range":
        uv[0, 0] = -0.1
    elif kind == "wrong_shape":
        uv = uv[:2]
    else:
        uv = uv.astype(str)
    with pytest.raises(ValueError):
        project_photo_texture(rgb, raw, uv)


@pytest.mark.parametrize("kind", ["projection", "reflection", "roi", "face", "repeated", "space"])
def test_invalid_mesh_or_projection_fails(kind):
    rgb, raw, uv = fixture()
    if kind == "projection":
        raw = replace(raw, projection=np.zeros((3, 4), dtype=np.float32))
    elif kind == "reflection":
        raw.projection[0, 0] = -1
    elif kind == "roi":
        raw = replace(raw, roi=(0, 0, 0, 0))
    elif kind == "face":
        raw = replace(raw, triangles=np.array([[0, 1, 3]]))
    elif kind == "repeated":
        raw = replace(raw, triangles=np.array([[0, 1, 1]]))
    else:
        raw = replace(raw, coordinate_system="already_projected")
    with pytest.raises(ValueError):
        project_photo_texture(rgb, raw, uv)


def test_rgb_shape_and_dtype_are_checked():
    rgb, raw, uv = fixture()
    for bad in (rgb.astype(float), rgb[:, :, :2], rgb[:0], rgb[:, :, 0]):
        with pytest.raises(ValueError):
            project_photo_texture(bad, raw, uv)


@pytest.mark.parametrize(
    "budget", ["_MAX_UV_SAMPLE_WORK", "_MAX_BIN_REFERENCES", "_MAX_DEPTH_PAIRS"]
)
def test_visibility_and_raster_work_are_bounded(monkeypatch, budget):
    rgb, raw, uv = fixture()
    monkeypatch.setattr(uv_texture, budget, 1)
    with pytest.raises(ValueError, match="bounded"):
        project_photo_texture(rgb, raw, uv, atlas_size=16)
