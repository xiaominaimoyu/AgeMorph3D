"""Synthetic offline calibration/routes; no age or identity accuracy evidence."""

from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")

from agemorph3d.age_routes import (  # noqa: E402
    anchored_bfm,
    anchored_sam,
    direction_observability,
    fit_bfm_scale,
)
from agemorph3d.age_shape import AgeDirection  # noqa: E402
from agemorph3d.tddfa import TddfaResult  # noqa: E402


def sample_data(definitions):
    direction = np.zeros((4, 3))
    direction[:, 0] = 1
    samples, vertices = [], {}
    base = np.array([[0, 0, 0], [2, 0, 0], [0, 4, 0], [1, 1, 2]], dtype=float)
    for subject, ages, slope, offset in definitions:
        for index, age in enumerate(ages):
            name = f"{subject}-{index}"
            samples.append(
                dict(
                    sample_id=name,
                    subject_id=subject,
                    source_age=age,
                    group="calibration_research",
                )
            )
            vertices[name] = base + (slope * age + offset) * direction
    return samples, vertices, direction


def test_centered_linear_recovery_is_invariant_to_identity_offsets():
    samples, vertices, direction = sample_data(
        [("a", [20, 30, 40], 0.5, 700), ("b", [25, 35], 0.5, -250)]
    )
    result = fit_bfm_scale(samples, vertices, direction)
    assert result["strength_per_year"] == pytest.approx(0.5)
    assert result["beta_sign"] == "positive"
    assert result["age_min"] == 20 and result["age_max"] == 40
    assert not result["years_calibrated"] and not result["independent_evaluation"]
    assert all(row["projection_residual_rms"] == pytest.approx(0) for row in result["loio"])


def test_identity_weights_do_not_follow_photograph_counts():
    samples, vertices, direction = sample_data(
        [("many", [20, 30, 40, 50], 2, 0), ("few", [20, 30], 4, 0)]
    )
    result = fit_bfm_scale(samples, vertices, direction)
    assert result["strength_per_year"] == pytest.approx((125 * 2 + 25 * 4) / (125 + 25))
    assert result["strength_per_year"] != pytest.approx((4 * 125 * 2 + 2 * 25 * 4) / 550)


def test_negative_scale_is_retained_without_positive_clamping():
    samples, vertices, direction = sample_data(
        [("a", [20, 30], -0.2, 100), ("b", [25, 35], -0.2, -100)]
    )
    result = fit_bfm_scale(samples, vertices, direction)
    assert result["strength_per_year"] == pytest.approx(-0.2)
    assert result["beta_sign"] == "negative"


def test_same_age_and_singleton_identities_are_disclosed_without_slope_information():
    samples, vertices, direction = sample_data(
        [("a", [20, 30], 1, 0), ("009", [22, 22], 99, 0), ("050", [25], 99, 0)]
    )
    result = fit_bfm_scale(samples, vertices, direction)
    assert result["eligible_identity_ids"] == ["a"]
    assert result["excluded_identity_ids"] == ["009", "050"]
    assert result["strength_per_year"] == pytest.approx(1)
    assert result["loio"] == [
        {
            "held_out_identity": "a",
            "training_identity_ids": [],
            "status": "unavailable",
            "error_code": "INSUFFICIENT_TRAINING_IDENTITIES",
        }
    ]


def test_loio_excludes_held_identity_and_marks_coverage_extrapolation():
    samples, vertices, direction = sample_data(
        [("a", [20, 25], 2, 0), ("b", [30, 35], 4, 0), ("c", [25, 30], 6, 0)]
    )
    result = fit_bfm_scale(samples, vertices, direction)
    folds = {fold["held_out_identity"]: fold for fold in result["loio"]}
    assert folds["a"]["training_identity_ids"] == ["b", "c"]
    assert folds["a"]["strength_per_year"] == pytest.approx(5)
    assert folds["a"]["extrapolation_flag"] and folds["a"]["extrapolation_pairs"] == 2
    assert folds["a"]["projection_residual_rms"] == pytest.approx(15)
    assert folds["a"]["zero_change_projection_rms"] == pytest.approx(10)
    assert not folds["c"]["extrapolation_flag"]


@pytest.mark.parametrize("group", ["development", "evaluation_research_holdout", None])
def test_noncalibration_inputs_are_rejected(group):
    samples, vertices, direction = sample_data([("a", [20, 30], 1, 0)])
    samples[0]["group"] = group
    with pytest.raises(ValueError, match="calibration_research"):
        fit_bfm_scale(samples, vertices, direction)


@pytest.mark.parametrize("age", [None, True, 19, 71, np.nan, np.inf])
def test_invalid_or_unknown_calibration_age_is_not_filled(age):
    samples, vertices, direction = sample_data([("a", [20, 30], 1, 0)])
    samples[0]["source_age"] = age
    with pytest.raises(ValueError):
        fit_bfm_scale(samples, vertices, direction)


def test_calibration_requires_unique_samples_neutral_fits_and_informative_age():
    samples, vertices, direction = sample_data([("a", [20, 30], 1, 0)])
    with pytest.raises(ValueError, match="unique"):
        fit_bfm_scale([*samples, samples[0]], vertices, direction)
    with pytest.raises(ValueError, match="successful neutral"):
        fit_bfm_scale(samples, {}, direction)
    with pytest.raises(ValueError, match="samples"):
        fit_bfm_scale([], {}, direction)
    samples, vertices, direction = sample_data([("a", [20, 20], 1, 0)])
    with pytest.raises(ValueError, match="age variance"):
        fit_bfm_scale(samples, vertices, direction)


@pytest.fixture
def route():
    vertices = np.array([[0, 0, 0], [2, 0, 0], [0, 4, 0], [1, 1, 2]], dtype=np.float32)
    raw = TddfaResult(
        shape=np.zeros(40, dtype=np.float32),
        expr=np.zeros(10, dtype=np.float32),
        vertices=vertices,
        triangles=np.array([[0, 1, 2], [0, 2, 3]]),
        projection=np.eye(3, 4, dtype=np.float32),
        roi=(0.0, 0.0, 120.0, 120.0),
        topology_sha256="a" * 64,
    )
    direction = AgeDirection(
        np.full((4, 3), 0.25, dtype=np.float32),
        np.ones((4, 3), dtype=np.float32),
        np.arange(4),
        "a" * 64,
        "b" * 64,
        "c" * 64,
    )
    return raw, direction, {"strength_per_year": 0.5, "age_min": 20, "age_max": 55}


def test_bfm_anchors_zero_and_roundtrip_at_the_original_source(route):
    raw, direction, calibration = route
    before = raw.vertices.tobytes()
    assert anchored_bfm(raw, direction, calibration, 35, 35) is raw
    first = anchored_bfm(raw, direction, calibration, 35, 45)
    second = anchored_bfm(raw, direction, calibration, 35, 45)
    np.testing.assert_array_equal(first.vertices, raw.vertices + 5 * direction.shape_direction)
    np.testing.assert_array_equal(first.vertices, second.vertices)
    assert anchored_bfm(raw, direction, calibration, 35, 35) is raw
    assert raw.vertices.tobytes() == before
    for field in ("shape", "expr", "projection", "triangles", "roi"):
        assert getattr(first, field) is getattr(raw, field)
    assert not first.vertices.flags.writeable


def test_bfm_zero_reset_works_outside_calibration_range_but_nonzero_does_not(route):
    raw, direction, calibration = route
    assert anchored_bfm(raw, direction, calibration, 60, 60) is raw
    with pytest.raises(ValueError, match="extrapolate"):
        anchored_bfm(raw, direction, calibration, 55, 60)
    with pytest.raises(ValueError, match="extrapolate"):
        anchored_bfm(raw, direction, calibration, 60, 50)
    excessive = dict(calibration, strength_per_year=10)
    with pytest.raises(ValueError, match="between -50 and 50"):
        anchored_bfm(raw, direction, excessive, 20, 55)


@pytest.mark.parametrize("age", [None, True, np.nan, 19, 71])
def test_routes_reject_unknown_or_invalid_source_ages_even_for_reset(route, age):
    raw, direction, calibration = route
    with pytest.raises(ValueError):
        anchored_bfm(raw, direction, calibration, age, 35)
    with pytest.raises(ValueError):
        anchored_sam(raw, None, None, np.zeros((12, 10)), age, 35)


def test_bfm_topology_is_validated_even_on_source_reset(route):
    raw, direction, calibration = route
    with pytest.raises(ValueError, match="topology"):
        anchored_bfm(replace(raw, topology_sha256="d" * 64), direction, calibration, 35, 35)


def test_sam_exact_reset_needs_no_generated_fit_and_preserves_fractional_age(route):
    raw, _, _ = route
    assert anchored_sam(raw, None, None, np.zeros((12, 10)), 35, 35) is raw
    assert anchored_sam(raw, None, None, np.zeros((12, 10)), 35.5, 35.5) is raw
    with pytest.raises(ValueError, match="integer"):
        anchored_sam(raw, raw, raw, np.zeros((12, 10)), 35.5, 45)
    with pytest.raises(ValueError, match="both exact-condition"):
        anchored_sam(raw, None, raw, np.zeros((12, 10)), 35, 45)


def test_sam_adds_neutral_increment_and_retains_original_expression_pose(route):
    raw, _, _ = route
    basis = np.zeros((12, 10))
    basis[4, 0] = 3
    expression = raw.expr.copy()
    expression[0] = 2
    offset = (basis @ expression[:, None]).reshape(3, -1, order="F").T
    same = replace(raw, vertices=raw.vertices + np.float32(0.3))
    target = replace(
        raw,
        vertices=np.asarray(same.vertices + offset + [1, 0, 0], dtype=np.float32),
        expr=expression,
    )
    result = anchored_sam(raw, same, target, basis, 35, 45)
    np.testing.assert_allclose(result.vertices, raw.vertices + [1, 0, 0], atol=1e-6)
    assert result.expr is raw.expr and result.projection is raw.projection
    assert result.shape is raw.shape and result.roi is raw.roi
    assert not result.vertices.flags.writeable
    np.testing.assert_array_equal(
        result.vertices, anchored_sam(raw, same, target, basis, 35, 45).vertices
    )


def test_sam_topology_order_and_nonfinite_basis_are_rejected(route):
    raw, _, _ = route
    with pytest.raises(ValueError, match="ordered topology"):
        anchored_sam(
            raw, raw, replace(raw, triangles=raw.triangles[::-1]), np.zeros((12, 10)), 35, 45
        )
    with pytest.raises(ValueError, match="finite real"):
        anchored_sam(raw, raw, raw, np.full((12, 10), np.nan), 35, 45)


def test_direction_observability_keeps_out_of_basis_energy_explicit():
    direction = np.zeros((4, 3))
    direction[0, :2] = [3, 4]
    basis = np.zeros((12, 40))
    basis[0, 0] = 1
    result = direction_observability(direction, basis)
    assert result["basis_rank"] == 1
    assert result["observable_norm_fraction"] == pytest.approx(3 / 5)
    assert result["unobservable_norm_fraction"] == pytest.approx(4 / 5)
    assert result["observable_energy_fraction"] == pytest.approx(9 / 25)
    assert result["orthogonal_residual_rms"] == pytest.approx(2)
    assert not result["direction_replaced_by_projection"]


@pytest.mark.parametrize("direction", [np.zeros((4, 3)), np.full((4, 3), np.nan)])
def test_invalid_directions_do_not_produce_a_fake_scale(direction):
    samples, vertices, _ = sample_data([("a", [20, 30], 1, 0)])
    with pytest.raises(ValueError):
        fit_bfm_scale(samples, vertices, direction)
