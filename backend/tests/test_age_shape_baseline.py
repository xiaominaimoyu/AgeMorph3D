"""Synthetic nested-fold leakage, geometry and source-anchor checks for K2."""

import copy
import importlib.util
from pathlib import Path

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[2] / "preprocessing/age_shape_baseline.py"
_SPEC = importlib.util.spec_from_file_location("age_shape_baseline", _PATH)
baseline = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(baseline)


@pytest.fixture
def samples():
    result = []
    for i in range(5):
        for age in (25, 30, 35):
            c = np.zeros(40)
            c[0] = i * 20 + 0.1 * age
            c[1] = i * 3 - 0.2 * age
            result.append(
                {
                    "sample_id": f"s{i}-{age}",
                    "subject_id": str(i),
                    "group": "calibration_research",
                    "age": age,
                    "status": "ok",
                    "error_code": None,
                    "shape": c.tolist(),
                    "scale": 0.01,
                }
            )
    return result


@pytest.fixture
def metric():
    # A non-orthogonal full BFM direction distinct from the true synthetic direction.
    basis = np.column_stack((np.eye(40), np.r_[1.0, np.zeros(39)]))
    return basis.T @ basis


def test_closed_form_recovers_within_identity_direction_and_relative_ridge(samples):
    model = baseline.fit_direction(samples, 0.0)
    assert np.allclose(model["direction"][:2], [0.1, -0.2], atol=1e-14)
    assert np.allclose(model["direction"][2:], 0.0)
    shrunk = baseline.fit_direction(samples, 1.0)
    assert np.allclose(shrunk["direction"], np.array(model["direction"]) / 2)
    assert model["age_min"] == 25 and model["age_max"] == 35


def test_identity_offsets_and_repeated_photos_do_not_change_total_identity_weight(samples):
    expected = baseline.fit_direction(samples, 0.0)["direction"]
    for row in samples:
        row["shape"] = (np.array(row["shape"]) + int(row["subject_id"]) * 1000).tolist()
    for row in copy.deepcopy(samples[:3]):
        row["sample_id"] += "-repeat"
        samples.append(row)
    assert np.allclose(baseline.fit_direction(samples, 0.0)["direction"], expected, atol=1e-12)


def test_single_age_identity_keeps_record_but_does_not_extend_training_coverage(samples):
    row = copy.deepcopy(samples[0])
    row.update(sample_id="single", subject_id="single", age=70)
    samples.append(row)
    model = baseline.fit_direction(samples, 0.0)
    assert model["single_age_identity_ids"] == ["single"]
    assert model["age_max"] == 35


def test_nested_held_out_identity_cannot_change_training_model_or_inner_choices(samples, metric):
    old = baseline.run_baseline(samples, metric)
    for row in samples:
        if row["subject_id"] == "2":
            row["shape"][0] += row["age"] ** 2
    new = baseline.run_baseline(samples, metric)
    a = next(f for f in old["outer_folds"] if f["held_out_identity"] == "2")
    b = next(f for f in new["outer_folds"] if f["held_out_identity"] == "2")
    assert a == b
    for outer in new["outer_folds"]:
        held = outer["held_out_identity"]
        assert held not in outer["model"]["training_identity_ids"]
        for inner in outer["tuning"]["folds"]:
            assert held not in inner["training_identity_ids"]
            assert inner["validation_identity"] not in inner["training_identity_ids"]


def test_all_failures_and_exact_common_pair_denominator_remain_visible(samples, metric):
    samples[0].update(status="failed", shape=None, scale=None, error_code="NO_FACE")
    result = baseline.run_baseline(samples, metric)
    for route in baseline.ROUTES:
        assert result["summaries"][route]["requested"] == 30
        assert result["summaries"][route]["failures"]["FIT_FAILED"] == 4
    counts = {r["common_valid"]["valid_pairs"] for r in result["summaries"].values()}
    assert len(counts) == 1
    assert result["fit_statuses"] == {"failed": 1, "ok": 14}


def test_zero_signal_ties_choose_more_regularization_and_keep_static(samples, metric):
    for row in samples:
        row["shape"] = [float(row["subject_id"])] * 40
    result = baseline.run_baseline(samples, metric)
    assert result["full_tuning"]["selected_alpha"] == 10.0
    assert result["exploratory_preference"] == "static_fallback"
    assert result["production_route_selected"] is None and result["quality_accepted"] is False


def test_gram_residual_equals_explicit_edited_geometry():
    rng = np.random.default_rng(4)
    basis = rng.normal(size=(90, 41))
    v = rng.normal(size=41)
    gram = basis.T @ basis / 30
    explicit = np.sqrt(np.sum((basis @ v).reshape(30, 3) ** 2) / 30) * 0.003
    assert baseline.metric_rms(v, gram, 0.003) == pytest.approx(explicit, rel=1e-13)


def test_exact_reset_fractional_continuity_and_original_based_roundtrip(samples, metric):
    model = baseline._model(samples, 0.0, metric)
    source = np.r_[samples[0]["shape"], 0.0]
    before = source.tobytes()
    assert baseline.anchored_coefficients(source, 25.0, 25.0, model, metric) is source
    a = baseline.anchored_coefficients(source, 25.0, 30.0, model, metric, scale=0.01)
    b = baseline.anchored_coefficients(source, 25.0, 30.5, model, metric, scale=0.01)
    assert np.allclose((b - a)[:40], 0.5 * np.array(model["direction"]))
    assert source.tobytes() == before and not a.flags.writeable
    reset = baseline.anchored_coefficients(source, 25.0, 25.0, model, metric)
    assert reset is source and reset.tobytes() == before
    assert np.array_equal(
        a, baseline.anchored_coefficients(source, 25.0, 30.0, model, metric, scale=0.01)
    )


@pytest.mark.parametrize(
    "source_age,target_age", [(None, 30), (True, 30), (25, float("nan")), (19, 30), (25, 71)]
)
def test_unknown_invalid_age_is_never_imputed(samples, metric, source_age, target_age):
    with pytest.raises(ValueError):
        baseline.anchored_coefficients(
            np.zeros(41), source_age, target_age, baseline._model(samples, 0.0, metric), metric
        )


def test_coverage_and_displacement_bounds_reject_without_clipping(samples, metric):
    model = baseline._model(samples, 0.0, metric)
    v = np.zeros(41)
    with pytest.raises(ValueError, match="OUTSIDE_FOLD_COVERAGE"):
        baseline.anchored_coefficients(v, 25, 40, model, metric, scale=0.01)
    model["training_displacement_rms_bound"] = 0.00001
    with pytest.raises(ValueError, match="TRAINING_DISPLACEMENT_BOUND"):
        baseline.anchored_coefficients(v, 25, 35, model, metric, scale=0.01)
    model["bfm_strength_per_year"] = 100
    with pytest.raises(ValueError, match="BFM_STRENGTH_BOUND"):
        baseline.anchored_coefficients(v, 25, 35, model, metric, route="bfm_direction_refit")


def test_direction_stability_uses_geometry_cosines_not_all_positive_components(samples, metric):
    result = baseline.run_baseline(samples, metric)
    assert result["direction_agreement_diagnostic"] is True
    assert result["full_model"]["direction"][1] < 0
    assert all(f["geometry_cosine_to_full"] > 0.999 for f in result["stability"])
    for row in result["outer_pair_outcomes"]:
        if row["status"] == "ok":
            assert row["identity_reference_count"] > 0
            assert row["nearest_impostor_id"] is not None


def test_missing_exact_age_identity_references_stay_null(samples, metric):
    for row in samples:
        row["age"] += int(row["subject_id"]) * 0.1
    result = baseline.run_baseline(samples, metric)
    valid = [r for r in result["outer_pair_outcomes"] if r["status"] == "ok"]
    assert valid and all(
        r["identity_reference_count"] == 0 and r["identity_margin"] is None for r in valid
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows[0].update(group="evaluation_research_holdout"),
        lambda rows: rows.append(copy.deepcopy(rows[0])),
        lambda rows: rows[0].update(shape=[0] * 39),
        lambda rows: rows[0]["shape"].__setitem__(0, float("inf")),
        lambda rows: rows[0].update(scale=-1),
        lambda rows: rows[0].update(status="failed", error_code="NO_FACE"),
    ],
)
def test_unusable_or_cross_group_samples_are_rejected(samples, metric, mutation):
    mutation(samples)
    with pytest.raises(ValueError):
        baseline.run_baseline(samples, metric)


@pytest.mark.parametrize("grid", [[], [1.0, 1.0], [-1.0], [True], [float("inf")]])
def test_invalid_parameter_grid_rejected(samples, metric, grid):
    with pytest.raises(ValueError):
        baseline.run_baseline(samples, metric, grid)


def test_invalid_geometry_metric_rejected(samples):
    metric = np.eye(41)
    metric[0, 1] = 1
    with pytest.raises(ValueError, match="symmetric"):
        baseline.run_baseline(samples, metric)
    metric = np.eye(41)
    metric[0, 0] = -1
    with pytest.raises(ValueError, match="semidefinite"):
        baseline.run_baseline(samples, metric)


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def packet_evidence(tmp_path):
    root = Path(__file__).resolve().parents[2]
    fixtures = _module(root / "backend/tests/test_age_features.py", "k1_test_helpers")
    report_pin = fixtures.persist(tmp_path, fixtures.study.__wrapped__())
    exported = fixtures.features.export_dataset(
        tmp_path, report_pin["path"], report_pin["sha256"], "output/k1"
    )
    tool = _module(root / "tools/age_shape_baseline.py", "k2_tool")
    return tool, fixtures, exported


def test_k1_packet_is_rebuilt_from_original_metadata(tmp_path, packet_evidence):
    tool, _, exported = packet_evidence
    reader = tool._JsonInputs(tmp_path)
    packet = tool.load_packet(reader, exported)
    samples = tool.samples_from_packet(packet)
    assert len(reader.pins) == 8 and len(samples) == 4
    assert samples[1]["status"] == "failed" and samples[1]["shape"] is None


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["features"]["shape"][0].__setitem__(0, 123456),
        lambda p: p["records"][0].update(group="development"),
        lambda p: p.update(training_use=True),
        lambda p: p["verified_json_inputs"].pop(),
    ],
)
def test_rehashed_derived_packet_tampering_still_rejected(tmp_path, packet_evidence, change):
    import json

    tool, fixture, exported = packet_evidence
    path = tmp_path / exported["path"]
    packet = json.loads(path.read_bytes())
    change(packet)
    payload = fixture.json_bytes(packet)
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        tool.load_packet(tool._JsonInputs(tmp_path), fixture.pin(exported["path"], payload))


@pytest.mark.parametrize("output", ["../escape", "preprocessing/new", "data/new", "output"])
def test_runner_rejects_outputs_outside_fresh_research_directory(tmp_path, packet_evidence, output):
    tool, _, _ = packet_evidence
    with pytest.raises(ValueError):
        tool.run(tmp_path, "does-not-exist.json", "a" * 64, output)


def test_bound_binary_read_rejects_mismatch_and_unsafe_extension(tmp_path, packet_evidence):
    tool, fixture, _ = packet_evidence
    path = tmp_path / "data/fake.npz"
    path.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="fingerprint"):
        tool.verify_binary(tmp_path, fixture.pin("data/fake.npz", b"different"), 100)
    with pytest.raises(ValueError, match="safe NPZ"):
        tool.verify_binary(tmp_path, fixture.pin("data/fake.pkl"), 100)
