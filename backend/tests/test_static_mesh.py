"""Numerical and GLB format checks; synthetic fixtures are not model/G1 evidence."""

import json
import struct
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from agemorph3d import static_mesh  # noqa: E402
from agemorph3d.static_mesh import build_static_mesh  # noqa: E402

UNKNOWN_AGE = {"value": None, "method": "unknown", "calibration_id": None}


def raw_face():
    # An asymmetric, open pyramidal surface, viewed from the face's +Z front.
    # Its source winding intentionally matches the upstream clockwise topology.
    vertices = np.array(
        [[-2, -1, 0], [1, -1, 0], [1, 2, 0], [-2, 2, 0], [0.2, 0.25, 1]],
        dtype=np.float32,
    )
    vertices = vertices * 7 + np.array([12, -3, 20], dtype=np.float32)
    return SimpleNamespace(
        vertices=vertices,
        triangles=np.array([[0, 4, 1], [1, 4, 2], [2, 4, 3], [3, 4, 0]], dtype=np.int64),
        projection=np.array([[2, 0, 0, 60], [0, 2, 0, 70], [0, 0, 2, -40]], dtype=np.float32),
        roi=(10.0, 20.0, 130.0, 140.0),
        topology_sha256="ab" * 32,
        coordinate_system="bfm_model_raw",
    )


def parse_glb(data):
    magic, version, total = struct.unpack_from("<4sII", data)
    assert magic == b"glTF"
    assert version == 2
    assert total == len(data)
    json_length, json_type = struct.unpack_from("<I4s", data, 12)
    assert json_type == b"JSON"
    assert json_length % 4 == 0
    document = json.loads(data[20 : 20 + json_length])
    bin_length, bin_type = struct.unpack_from("<I4s", data, 20 + json_length)
    assert bin_type == b"BIN\0"
    assert bin_length % 4 == 0
    binary = data[28 + json_length :]
    assert len(binary) == bin_length
    assert document["buffers"] == [{"byteLength": bin_length}]
    return document, binary


def test_canonical_transform_preserves_vertex_face_order_and_shape_proportions():
    source = raw_face()
    vertices_before = source.vertices.copy()
    faces_before = source.triangles.copy()
    result = build_static_mesh(source, UNKNOWN_AGE)
    expected = (source.vertices - np.array([8.5, 0.5, 23.5])) / 21.0
    np.testing.assert_allclose(result.vertices, expected, atol=1e-7)
    np.testing.assert_array_equal(result.triangles, source.triangles[:, [0, 2, 1]])
    np.testing.assert_array_equal(source.vertices, vertices_before)
    np.testing.assert_array_equal(source.triangles, faces_before)
    np.testing.assert_allclose(np.ptp(result.vertices, axis=0)[1], 1.0)
    metadata = result.coordinate_metadata
    restored = (
        result.vertices / metadata["source_to_canonical_uniform_scale"] + metadata["source_center"]
    )
    np.testing.assert_allclose(restored, vertices_before, atol=2e-6)
    before_distances = np.linalg.norm(vertices_before[1:] - vertices_before[0], axis=1)
    after_distances = np.linalg.norm(result.vertices[1:] - result.vertices[0], axis=1)
    np.testing.assert_allclose(after_distances / before_distances, np.full(4, 1 / 21), rtol=1e-6)
    assert metadata["metric_scale_verified"] is False
    assert metadata["canonical_unit"] == "dimensionless"
    assert metadata["source_topology_sha256"] == "ab" * 32
    assert result.topology_id == "tddfa-bfm-canon-v1-" + "ab" * 32
    assert result.vertices.flags.writeable is False
    assert result.normals.flags.writeable is False
    assert result.triangles.flags.writeable is False


def test_polar_rotation_removes_affine_scale_and_shear_without_modifying_geometry():
    source = raw_face()
    angle = np.deg2rad(37)
    rotation = np.array(
        [[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]]
    )
    stretch = np.array([[2, 0.25, 0.1], [0.25, 1.2, -0.1], [0.1, -0.1, 1.7]])
    source.projection[:, :3] = 0.003 * rotation @ stretch
    canonical = build_static_mesh(source, UNKNOWN_AGE)
    actual = np.array(canonical.pose["R"]).reshape(3, 3)
    np.testing.assert_allclose(actual, rotation, atol=2e-8)
    np.testing.assert_allclose(actual.T @ actual, np.eye(3), atol=1e-12)
    np.testing.assert_allclose(np.linalg.det(actual), 1.0, atol=1e-12)
    assert canonical.pose["t"] == [0.0, 0.0, 0.0]
    np.testing.assert_allclose(
        canonical.coordinate_metadata["pose"]["stretch_source_to_crop"],
        (stretch * 0.003).reshape(-1),
        atol=3e-10,
    )
    assert canonical.coordinate_metadata["pose"]["scale_shear_relative_frobenius_residual"] > 0
    reference = build_static_mesh(raw_face(), UNKNOWN_AGE)
    np.testing.assert_array_equal(canonical.vertices, reference.vertices)


@pytest.mark.parametrize("scale", [1e-25, 1.0, 1e25])
def test_rotation_is_invariant_to_arbitrary_positive_camera_scale(scale):
    source = raw_face()
    source.projection = source.projection.astype(np.float64)
    source.projection[:, :3] *= scale
    result = build_static_mesh(source, UNKNOWN_AGE)
    np.testing.assert_allclose(np.array(result.pose["R"]).reshape(3, 3), np.eye(3))


def test_glb_binary_and_accessors_describe_one_complete_static_front_surface():
    result = build_static_mesh(raw_face(), UNKNOWN_AGE)
    document, binary = parse_glb(result.glb)
    assert document["asset"]["version"] == "2.0"
    assert "uri" not in document["buffers"][0]
    assert all(key not in document for key in ("textures", "images", "animations", "extensions"))
    primitive = document["meshes"][0]["primitives"][0]
    assert primitive == {
        "attributes": {"POSITION": 0, "NORMAL": 1},
        "indices": 2,
        "material": 0,
        "mode": 4,
    }
    assert "weights" not in document["meshes"][0]
    expected_types = [(5126, "VEC3", 5), (5126, "VEC3", 5), (5125, "SCALAR", 12)]
    for accessor, expected in zip(document["accessors"], expected_types, strict=True):
        assert (accessor["componentType"], accessor["type"], accessor["count"]) == expected
    arrays = []
    for view, dtype in zip(document["bufferViews"], ("<f4", "<f4", "<u4"), strict=True):
        start, length = view["byteOffset"], view["byteLength"]
        assert start % 4 == 0
        assert start + length <= len(binary)
        arrays.append(np.frombuffer(binary[start : start + length], dtype=dtype).reshape(-1, 3))
    vertices, normals, triangles = arrays
    np.testing.assert_array_equal(vertices, result.vertices)
    np.testing.assert_array_equal(normals, result.normals)
    np.testing.assert_array_equal(triangles, result.triangles)
    np.testing.assert_array_equal(document["accessors"][0]["min"], vertices.min(axis=0))
    np.testing.assert_array_equal(document["accessors"][0]["max"], vertices.max(axis=0))
    np.testing.assert_allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-7)
    face_normals = np.cross(
        vertices[triangles[:, 1]] - vertices[triangles[:, 0]],
        vertices[triangles[:, 2]] - vertices[triangles[:, 0]],
    )
    assert np.all(face_normals[:, 2] > 0)
    assert np.all(normals[:, 2] > 0)
    assert document["materials"][0]["doubleSided"] is False
    extras = document["extras"]
    assert document["scenes"][0]["extras"] == extras
    assert extras["asset_mode"] == "static"
    assert extras["source_age"] == UNKNOWN_AGE
    assert extras["topology_id"] == result.topology_id
    assert "age" not in extras
    assert "ageAnchors" not in extras
    assert "displayAge" not in extras


def test_known_fractional_source_age_is_preserved_as_provenance_only():
    age = {"value": 42.5, "method": "user", "calibration_id": None}
    document, _ = parse_glb(build_static_mesh(raw_face(), age).glb)
    assert document["extras"]["source_age"] == age
    assert "age" not in document["extras"]


@pytest.mark.parametrize(
    "block, message",
    [
        (np.diag([-1, 1, 1]), "reflection"),
        (np.zeros((3, 3)), "nonsingular"),
        (np.diag([1, 1, 0]), "singular"),
        (np.diag([1, 1, 1e-7]), "ill-conditioned"),
        (np.full((3, 3), np.nan), "finite"),
    ],
)
def test_invalid_camera_blocks_cannot_be_published_as_a_rotation(block, message):
    source = raw_face()
    source.projection[:, :3] = block
    with pytest.raises(ValueError, match=message):
        build_static_mesh(source, UNKNOWN_AGE)


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("coordinate_system", "image_pixels", "raw pre-projection"),
        ("topology_sha256", "ab", "SHA-256"),
        ("vertices", [[1, 2]], r"shape \(N,3\)"),
        ("vertices", [[1, 2, np.inf]] * 3, "finite"),
        ("vertices", np.ones((5, 3)), "positive bounding-box height"),
        ("triangles", [[0, 1.0, 2]], "integer"),
        ("triangles", [[0, 1, 5]], "integer"),
        ("triangles", [[0, 1, -1]], "integer"),
        ("triangles", [[0, 1, 1]], "repeat"),
        ("triangles", [[0, 4, 1]], "Every vertex"),
        ("roi", [1, 0, 1, 5], "positive width"),
        ("projection", np.ones((3, 3)), "shape"),
    ],
)
def test_invalid_geometry_and_provenance_are_rejected(field, value, message):
    source = raw_face()
    setattr(source, field, value)
    with pytest.raises(ValueError, match=message):
        build_static_mesh(source, UNKNOWN_AGE)


def test_wrong_winding_is_not_silently_repaired_by_view_dependent_heuristics():
    source = raw_face()
    source.triangles = source.triangles[:, [0, 2, 1]]
    with pytest.raises(ValueError, match="Source winding"):
        build_static_mesh(source, UNKNOWN_AGE)


def test_zero_area_face_is_rejected_even_with_three_distinct_indices():
    source = raw_face()
    source.vertices[4] = (source.vertices[0] + source.vertices[1]) / 2
    with pytest.raises(ValueError, match="nonzero finite area"):
        build_static_mesh(source, UNKNOWN_AGE)


def test_asset_budget_is_checked_before_encoding(monkeypatch):
    monkeypatch.setattr(static_mesh, "MAX_GLB_BYTES", 100)
    monkeypatch.setattr(
        static_mesh, "_encode_glb", lambda *args: pytest.fail("Oversized mesh reached encoder.")
    )
    with pytest.raises(ValueError, match="64 MiB"):
        build_static_mesh(raw_face(), UNKNOWN_AGE)


@pytest.mark.parametrize(
    "age",
    [
        {"value": None, "method": "user", "calibration_id": None},
        {"value": 42.0, "method": "unknown", "calibration_id": None},
        {"value": True, "method": "user", "calibration_id": None},
        {"value": 42.0, "method": "estimated", "calibration_id": None},
    ],
)
def test_source_age_must_obey_the_frozen_contract(age):
    with pytest.raises(ValueError):
        build_static_mesh(raw_face(), age)
