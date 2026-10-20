"""Native-strength continuity and topology binding; these do not validate aging accuracy."""

import hashlib
from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")

from agemorph3d.age_shape import apply_age_strength, load_age_direction  # noqa: E402
from agemorph3d.prepare_bfm_age import FORMAT  # noqa: E402
from agemorph3d.tddfa import TddfaResult  # noqa: E402


@pytest.fixture
def payload():
    return {
        "shape_direction": np.arange(12, dtype=np.float32).reshape(4, 3) / 1024,
        "texture_direction": np.ones((4, 3), dtype=np.float32) / 512,
        "source_vertex_indices": np.array([7, 1, 6, 3], dtype=np.int32),
        "format": np.array(FORMAT),
        "source_sha256": np.array("a" * 64),
        "target_bfm_sha256": np.array("b" * 64),
        "topology_sha256": np.array("c" * 64),
        "unit": np.array("bfm_attribute_strength"),
        "years_calibrated": np.array(False),
    }


def write_payload(tmp_path, payload):
    path = tmp_path / "age.npz"
    np.savez_compressed(path, **payload)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def direction(tmp_path, payload):
    path, sha = write_payload(tmp_path, payload)
    return load_age_direction(path, sha, target_bfm_sha256="b" * 64)


@pytest.fixture
def result():
    return TddfaResult(
        np.zeros(40, dtype=np.float32),
        np.zeros(10, dtype=np.float32),
        np.arange(12, dtype=np.float32).reshape(4, 3) / 8,
        np.array([[0, 1, 2], [1, 3, 2]]),
        np.eye(3, 4, dtype=np.float32),
        (0, 0, 120, 120),
        "c" * 64,
    )


def test_loader_binds_hashes_and_returns_readonly_finite_arrays(direction):
    assert direction.unit == "bfm_attribute_strength" and direction.years_calibrated is False
    assert not direction.shape_direction.flags.writeable
    assert not direction.texture_direction.flags.writeable
    assert not direction.source_vertex_indices.flags.writeable


def test_zero_is_exact_noop_and_other_strengths_preserve_coefficients_and_inputs(direction, result):
    original = result.vertices.copy()
    assert apply_age_strength(result, direction, 0) is result
    changed = apply_age_strength(result, direction, 50)
    assert changed.shape is result.shape and changed.expr is result.expr
    assert changed.projection is result.projection and changed.triangles is result.triangles
    assert not changed.vertices.flags.writeable
    np.testing.assert_array_equal(result.vertices, original)
    assert np.any(changed.vertices != original)


def test_decimal_continuity_linear_interpolation_and_roundtrip(direction, result):
    low = apply_age_strength(result, direction, -25.5).vertices
    high = apply_age_strength(result, direction, 37.25).vertices
    fraction = 0.4
    middle = apply_age_strength(result, direction, -25.5 + fraction * (37.25 + 25.5)).vertices
    np.testing.assert_allclose(middle, (1 - fraction) * low + fraction * high, atol=2e-7)
    older = apply_age_strength(result, direction, 49.125)
    restored = apply_age_strength(older, direction, -49.125)
    np.testing.assert_allclose(restored.vertices, result.vertices, atol=2e-7)


def test_fractional_strength_multiplication_accumulates_before_float32_encoding(direction, result):
    delta = np.linspace(0.0031, 0.314159, 12, dtype=np.float32).reshape(4, 3)
    changed_direction = replace(direction, shape_direction=delta)
    expected = (result.vertices.astype(np.float64) + 37.125 * delta.astype(np.float64)).astype(
        np.float32
    )
    np.testing.assert_array_equal(
        apply_age_strength(result, changed_direction, 37.125).vertices, expected
    )


@pytest.mark.parametrize("strength", [-50.01, 50.01, float("nan"), float("inf"), True, "20"])
def test_invalid_strengths_never_become_calendar_ages(direction, result, strength):
    with pytest.raises(ValueError, match="strength"):
        apply_age_strength(result, direction, strength)


def test_topology_coordinate_or_calibration_mismatch_is_rejected(direction, result):
    for candidate in (
        replace(result, topology_sha256="d" * 64),
        replace(result, coordinate_system="canonical"),
        replace(result, vertices=result.vertices[:-1]),
    ):
        with pytest.raises(ValueError):
            apply_age_strength(candidate, direction, 0)
    with pytest.raises(ValueError):
        apply_age_strength(result, replace(direction, years_calibrated=True), 0)


@pytest.mark.parametrize(
    "key,value",
    [
        ("years_calibrated", np.array(True)),
        ("years_calibrated", np.array(0)),
        ("unit", np.array("years")),
        ("source_sha256", np.array("bad provenance")),
        ("shape_direction", np.full((4, 3), np.nan, dtype=np.float32)),
        ("texture_direction", np.zeros((4, 3), dtype=np.float32)),
        ("source_vertex_indices", np.array([1, 1, 2, 3], dtype=np.int32)),
    ],
)
def test_invalid_or_misrepresented_direction_assets_are_rejected(tmp_path, payload, key, value):
    payload[key] = value
    path, sha = write_payload(tmp_path, payload)
    with pytest.raises(ValueError):
        load_age_direction(path, sha, target_bfm_sha256="b" * 64)


def test_different_target_hash_cannot_use_same_topology_asset(tmp_path, payload):
    path, sha = write_payload(tmp_path, payload)
    with pytest.raises(ValueError, match="different target"):
        load_age_direction(path, sha, target_bfm_sha256="f" * 64)


def test_hash_mismatch_prevents_array_parsing(tmp_path, payload, monkeypatch):
    path, _ = write_payload(tmp_path, payload)
    monkeypatch.setattr(
        np, "load", lambda *args, **kwargs: pytest.fail("Hash mismatch must prevent parsing")
    )
    with pytest.raises(ValueError, match="SHA-256"):
        load_age_direction(path, "0" * 64, target_bfm_sha256="b" * 64)
