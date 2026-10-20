"""Synthetic coordinate checks; no real age, identity or camera acceptance."""

from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")

from agemorph3d.age_geometry import (  # noqa: E402
    compare_fits,
    in_source_frame,
    neutral_vertices,
    source_frame,
    vector_difference_metrics,
)
from agemorph3d.tddfa import TddfaResult  # noqa: E402


@pytest.fixture
def fit():
    return TddfaResult(
        shape=np.zeros(40),
        expr=np.zeros(10),
        vertices=np.array([[0, 0, 0], [2, 0, 0], [0, 4, 0], [1, 1, 2]], dtype=float),
        triangles=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64),
        projection=np.eye(3, 4),
        roi=(0.0, 0.0, 120.0, 120.0),
        topology_sha256="a" * 64,
    )


@pytest.fixture
def basis():
    result = np.zeros((12, 12))
    result[4, 0] = 3
    result[8, 1] = 2
    # Extra dimensions are intentionally outside the regressor's 10 coefficients.
    result[:, 10:] = 99
    return result


def test_frame_matches_original_bbox_and_is_reversible(fit):
    frame = source_frame(fit.vertices)
    assert frame == {
        "source_center": [1.0, 2.0, 1.0],
        "source_to_canonical_uniform_scale": 0.25,
        "normalization_reference": "unchanged_source_mesh",
    }
    canonical = in_source_frame(fit.vertices, frame)
    np.testing.assert_allclose(canonical / 0.25 + [1, 2, 1], fit.vertices)


def test_expression_only_change_disappears_from_neutral_geometry(fit, basis):
    expression = fit.expr.copy()
    expression[:2] = [2, -1]
    offset = (basis[:, :10] @ expression[:, None]).reshape(3, -1, order="F").T
    target = replace(fit, vertices=fit.vertices + offset, expr=expression)
    np.testing.assert_allclose(neutral_vertices(target, basis), fit.vertices)
    metrics = compare_fits(fit, target, basis)
    assert metrics["neutral_rms"] == pytest.approx(0)
    assert metrics["full_rms"] > 0
    assert metrics["expression_delta_rms"] == pytest.approx(metrics["full_rms"])
    assert metrics["expression_coeff_l2"] == pytest.approx(np.sqrt(5))


def test_camera_only_change_is_reported_separately(fit, basis):
    angle = np.radians(30)
    rotation = np.array(
        [[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]]
    )
    projection = fit.projection.copy()
    projection[:, :3] = 0.003 * rotation
    projection[:, 3] = [100, 200, 300]
    metrics = compare_fits(fit, replace(fit, projection=projection), basis)
    assert metrics["neutral_rms"] == 0
    assert metrics["full_rms"] == 0
    assert metrics["pose_rotation_delta_degrees"] == pytest.approx(30)


def test_target_translation_and_scale_are_not_normalized_away(fit, basis):
    target = replace(fit, vertices=fit.vertices * 2 + [4, 8, -2])
    metrics = compare_fits(fit, target, basis)
    expected = (target.vertices - fit.vertices) * 0.25
    assert metrics["neutral_rms"] == pytest.approx(np.sqrt(np.mean(np.sum(expected**2, axis=1))))
    assert metrics["neutral_max"] == pytest.approx(np.linalg.norm(expected, axis=1).max())
    assert metrics["neutral_rms"] > 0


def test_explicit_original_frame_remains_fixed_for_generated_pair(fit, basis):
    earlier_original = fit.vertices * 2 + [10, 20, 30]
    fixed_frame = source_frame(earlier_original)
    target = replace(fit, vertices=fit.vertices + [2, 0, 0])
    metrics = compare_fits(fit, target, basis, fixed_frame)
    assert metrics["neutral_rms"] == pytest.approx(2 / 8)
    assert compare_fits(fit, target, basis)["neutral_rms"] == pytest.approx(2 / 4)


def test_coefficient_norms_are_independent_diagnostics(fit, basis):
    shape = fit.shape.copy()
    shape[0] = 4
    metrics = compare_fits(fit, replace(fit, shape=shape), basis)
    assert metrics["shape_coeff_l2"] == 4
    assert metrics["neutral_rms"] == 0


@pytest.mark.parametrize("attribute", ["topology_sha256", "triangles", "vertices"])
def test_topology_and_order_mismatches_are_rejected(fit, basis, attribute):
    changes = {
        "topology_sha256": "b" * 64,
        "triangles": fit.triangles[::-1],
        "vertices": np.vstack([fit.vertices, [[0, 0, 0]]]),
    }
    with pytest.raises(ValueError, match="exact topology"):
        compare_fits(fit, replace(fit, **{attribute: changes[attribute]}), basis)


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_basis_or_vertices_are_rejected(fit, basis, value):
    broken_basis = basis.copy()
    broken_basis[0, 0] = value
    with pytest.raises(ValueError, match="finite real"):
        neutral_vertices(fit, broken_basis)
    vertices = fit.vertices.copy()
    vertices[0, 0] = value
    with pytest.raises(ValueError, match="finite real"):
        compare_fits(fit, replace(fit, vertices=vertices), basis)


@pytest.mark.parametrize("shape", [(12, 9), (11, 10), (12,), (4, 3, 10)])
def test_expression_basis_dimensions_are_checked(fit, shape):
    with pytest.raises(ValueError, match="Expression basis"):
        neutral_vertices(fit, np.zeros(shape))


@pytest.mark.parametrize("attribute,size", [("shape", 39), ("expr", 9)])
def test_coefficient_dimensions_are_checked(fit, basis, attribute, size):
    with pytest.raises(ValueError, match="coefficients"):
        compare_fits(fit, replace(fit, **{attribute: np.zeros(size)}), basis)


def test_source_requires_positive_height(fit):
    vertices = fit.vertices.copy()
    vertices[:, 1] = 0
    with pytest.raises(ValueError, match="positive bounding-box height"):
        source_frame(vertices)


@pytest.mark.parametrize(
    "change",
    [
        {"source_center": [0, np.nan, 0]},
        {"source_center": [0, 0]},
        {"source_to_canonical_uniform_scale": 0},
        {"source_to_canonical_uniform_scale": -1},
        {"source_to_canonical_uniform_scale": np.inf},
        {"normalization_reference": "independent_target_mesh"},
    ],
)
def test_invalid_fixed_frames_are_rejected(fit, change):
    frame = source_frame(fit.vertices)
    frame.update(change)
    with pytest.raises(ValueError):
        in_source_frame(fit.vertices, frame)


@pytest.mark.parametrize("block", [np.diag([-1, 1, 1]), np.diag([0, 1, 1])])
def test_reflected_or_singular_camera_is_rejected(fit, basis, block):
    projection = fit.projection.copy()
    projection[:, :3] = block
    with pytest.raises(ValueError, match="reflection|singular"):
        compare_fits(fit, replace(fit, projection=projection), basis)


def test_image_coordinate_geometry_is_not_accepted(fit, basis):
    with pytest.raises(ValueError, match="pre-projection"):
        neutral_vertices(replace(fit, coordinate_system="image_pixels"), basis)


def test_vector_metrics_use_euclidean_distance_per_vertex():
    metrics = vector_difference_metrics([[3, 4, 0], [0, 0, 0], [0, 0, 12]])
    assert metrics == {"rms": pytest.approx(np.sqrt(169 / 3)), "max": 12}


def test_helpers_do_not_modify_inputs(fit, basis):
    vertices = fit.vertices.copy()
    basis_before = basis.copy()
    compare_fits(fit, fit, basis)
    np.testing.assert_array_equal(fit.vertices, vertices)
    np.testing.assert_array_equal(basis, basis_before)
