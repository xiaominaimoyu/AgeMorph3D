"""Research aggregation/pairing invariants, not model quality acceptance."""

import json

import pytest
from agemorph3d.age_statistics import aggregate_identity_metrics, longitudinal_pairs


def test_identity_macro_average_gives_many_photo_identity_equal_weight():
    records = [{"subject_id": "many", "status": "ok", "drift": value} for value in (1, 2, 3)] + [
        {"subject_id": "one", "status": "ok", "drift": 10}
    ]
    result = aggregate_identity_metrics(records, ["drift"])
    assert result["per_identity"]["many"]["metrics"]["drift"] == {"count": 3, "mean": 2}
    assert result["macro"]["drift"]["mean"] == 6
    assert result["macro"]["drift"]["median"] == 6
    assert result["macro"]["drift"]["observations"] == 4
    assert result["macro"]["drift"]["identities"] == 2
    assert result["macro"]["drift"]["mean"] != 4  # Photograph-weighted mean.


def test_failures_keep_request_denominator_but_never_contribute_quality_values():
    records = [
        {"subject_id": "a", "status": "ok", "drift": 2},
        {"subject_id": "a", "status": "failed", "drift": 100},
        {"subject_id": "b", "status": "failed"},
    ]
    result = aggregate_identity_metrics(records, ["drift"])
    assert (result["requests"], result["successes"], result["failures"]) == (3, 1, 2)
    assert result["per_identity"]["b"]["failures"] == 1
    assert result["per_identity"]["b"]["metrics"]["drift"] == {"count": 0, "mean": None}
    assert result["macro"]["drift"]["mean"] == 2
    assert result["macro"]["drift"]["ci95"] is None


def test_missing_metrics_get_separate_identity_and_observation_counts():
    records = [
        {"subject_id": "a", "status": "ok", "geometry": 0, "pose": 8},
        {"subject_id": "a", "status": "ok", "geometry": 2, "pose": None},
        {"subject_id": "b", "status": "ok", "geometry": 3},
        {"subject_id": "c", "status": "ok"},
    ]
    result = aggregate_identity_metrics(records, ["geometry", "pose"])
    assert result["macro"]["geometry"]["identities"] == 2
    assert result["macro"]["geometry"]["observations"] == 3
    assert result["macro"]["geometry"]["mean"] == 2
    assert result["macro"]["pose"]["identities"] == 1
    assert result["macro"]["pose"]["observations"] == 1
    assert result["macro"]["pose"]["mean"] == 8
    assert result["macro"]["pose"]["ci95"] is None
    assert result["successes"] == 4


def test_bootstrap_resamples_identity_means_and_is_order_independent_and_deterministic():
    records = [{"subject_id": str(i), "status": "ok", "x": i} for i in range(8)]
    result = aggregate_identity_metrics(records, ["x"], bootstrap_seed=4, bootstrap_samples=800)
    repeat = aggregate_identity_metrics(
        list(reversed(records)), ["x"], bootstrap_seed=4, bootstrap_samples=800
    )
    assert result == repeat
    low, high = result["macro"]["x"]["ci95"]
    assert 0 <= low < 3.5 < high <= 7
    assert result["bootstrap"] == {"seed": 4, "samples": 800, "unit": "identity"}


def test_empty_or_absent_metrics_produce_json_null_instead_of_nan_or_zero():
    result = aggregate_identity_metrics([], ["x"])
    assert result["requests"] == result["successes"] == result["failures"] == 0
    assert result["macro"]["x"] == {
        "identities": 0,
        "observations": 0,
        "mean": None,
        "median": None,
        "ci95": None,
    }
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf"), "2"])
@pytest.mark.parametrize("status", ["ok", "failed"])
def test_invalid_provided_metric_is_rejected_even_for_a_failed_record(value, status):
    with pytest.raises(ValueError, match="finite numeric"):
        aggregate_identity_metrics([{"subject_id": "a", "status": status, "x": value}], ["x"])


@pytest.mark.parametrize(
    "options",
    [
        {"bootstrap_seed": True},
        {"bootstrap_samples": 0},
        {"bootstrap_samples": True},
        {"bootstrap_samples": 1.5},
    ],
)
def test_bootstrap_arguments_require_explicit_integer_values(options):
    with pytest.raises(ValueError, match="Bootstrap"):
        aggregate_identity_metrics([], [], **options)


@pytest.mark.parametrize("keys", [["x", "x"], [""], [None]])
def test_metric_keys_are_unambiguous(keys):
    with pytest.raises(ValueError, match="Metric keys"):
        aggregate_identity_metrics([], keys)


def test_unknown_status_and_missing_identity_do_not_disappear_from_statistics():
    with pytest.raises(ValueError, match="status"):
        aggregate_identity_metrics([{"subject_id": "a", "status": "NO_FACE"}], [])
    with pytest.raises(ValueError, match="Subject ID"):
        aggregate_identity_metrics([{"status": "failed"}], [])


def test_longitudinal_pairs_are_all_ordered_within_identity_distinct_age_pairs():
    samples = [
        {"sample_id": "a20", "subject_id": "a", "source_age": 20},
        {"sample_id": "a30", "subject_id": "a", "source_age": 30},
        {"sample_id": "a40", "subject_id": "a", "source_age": 40},
        {"sample_id": "b20", "subject_id": "b", "source_age": 20},
    ]
    pairs = longitudinal_pairs(samples)
    assert len(pairs) == 6
    assert all(pair["subject_id"] == "a" for pair in pairs)
    assert {(p["source_id"], p["target_id"]) for p in pairs} == {
        (a, b) for a in ("a20", "a30", "a40") for b in ("a20", "a30", "a40") if a != b
    }
    assert pairs == longitudinal_pairs(list(reversed(samples)))


def test_two_photos_at_one_age_do_not_make_a_longitudinal_identity():
    samples = [
        {"sample_id": "009a22", "subject_id": "009", "source_age": 22},
        {"sample_id": "009a22b", "subject_id": "009", "source_age": 22},
        {"sample_id": "other20", "subject_id": "other", "source_age": 20},
        {"sample_id": "other30", "subject_id": "other", "source_age": 30},
    ]
    assert len({s["subject_id"] for s in samples}) == 2
    assert len({p["subject_id"] for p in longitudinal_pairs(samples)}) == 1
    assert len(longitudinal_pairs(samples)) == 2


def test_fractional_age_labels_are_preserved_without_rounding():
    samples = [
        {"sample_id": "early", "subject_id": "a", "source_age": 42.25},
        {"sample_id": "late", "subject_id": "a", "source_age": 42.75},
    ]
    pairs = longitudinal_pairs(samples)
    assert pairs[0]["source_age"] == 42.25 and pairs[0]["target_age"] == 42.75
    assert len(pairs) == 2


@pytest.mark.parametrize("age", [None, True, float("nan"), float("inf"), 19, 71, "25"])
def test_invalid_or_unknown_age_cannot_enter_absolute_age_pairs(age):
    with pytest.raises(ValueError):
        longitudinal_pairs([{"sample_id": "a", "subject_id": "a", "source_age": age}])


def test_repeated_sample_identifiers_across_subjects_are_rejected():
    samples = [
        {"sample_id": "same", "subject_id": "a", "source_age": 20},
        {"sample_id": "same", "subject_id": "b", "source_age": 30},
    ]
    with pytest.raises(ValueError, match="unique"):
        longitudinal_pairs(samples)
