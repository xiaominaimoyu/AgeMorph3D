"""Synthetic age diagnostics; no real photos, candidate code or weights are loaded."""

import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import random
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load("age_probe_tests", ROOT / "tools/age_evaluator_probe.py")
identity_tests = load(
    "age_identity_fixture", ROOT / "backend/tests/test_identity_evaluator_probe.py"
)
pin, write = identity_tests.pin, identity_tests.write
ENVIRONMENT = {"python_version": "synthetic", "packages": {"pillow": "synthetic"}}
FACE = identity_tests.FACE


class FakeAgePredictor:
    def __init__(self):
        self.environment = copy.deepcopy(ENVIRONMENT)
        self.calls = []
        self.closed = False
        self.behavior = None

    def predict(self, rgb):
        self.calls.append(rgb)
        if self.behavior:
            return self.behavior(rgb)
        return {"age": 25.0, "raw_age": (25.0 - 61) / 122}

    def close(self):
        self.closed = True


def prepare_identity(case):
    plan = identity_tests.freeze(case)
    report, _ = identity_tests.probe.build_report(case["root"], plan, case["factory"])
    case["identity_report"] = report


@pytest.fixture
def case(tmp_path, monkeypatch):
    value = identity_tests.case.__wrapped__(tmp_path, monkeypatch)
    root = value["root"]
    for name in probe.SOURCES:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    prepare_identity(value)
    value["age_evaluator_protocol"] = json.loads(
        (ROOT / "docs/age-evaluator-v1.json").read_text("utf-8")
    )
    value["age_evaluator_protocol"]["cohort"].update(
        value["identity_protocol"]["cohort"],
        expected_within_identity_pairs=0,
        expected_reused_detection_failures=0,
    )
    base = root / "data/models/evaluation/synthetic-age"
    artifacts, release = [], {}
    for name in probe.RELEASE:
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"Synthetic source artifact: {name}".encode())
        entry = pin(path, root)
        release[name] = {key: entry[key] for key in ("bytes", "sha256")}
        artifacts.append({**entry, "url": f"https://example.org/fixed/{name}"})
    model_path = base / "model.safetensors"
    model_path.write_bytes(b"synthetic model, never imported or loaded")
    model = pin(model_path, root)
    pointer_path = base / "model-lfs-pointer.txt"
    pointer_path.write_text(
        f"version https://git-lfs.github.com/spec/v1\noid sha256:{model['sha256']}\n"
        f"size {model['bytes']}\n",
        encoding="utf-8",
    )
    value["source_acquisition"] = {
        "schema_version": 1,
        "hf_revision": value["age_evaluator_protocol"]["evaluator"]["hf_revision"],
        "repository_revision": value["age_evaluator_protocol"]["evaluator"]["repository_revision"],
        "artifacts": artifacts,
    }
    value["model_acquisition"] = {
        "hf_revision": value["source_acquisition"]["hf_revision"],
        "model": {**model, "url": "https://example.org/fixed/model.safetensors"},
        "official_pointer": {
            **pin(pointer_path, root),
            "url": "https://example.org/fixed/model.safetensors",
        },
    }
    monkeypatch.setattr(probe, "RELEASE", release)
    monkeypatch.setattr(probe, "MODEL", {key: model[key] for key in ("bytes", "sha256")})
    monkeypatch.setattr(probe, "_environment", lambda: copy.deepcopy(ENVIRONMENT))
    value["predictor"] = FakeAgePredictor()
    value["age_factory"] = lambda _: value["predictor"]
    return value


def freeze(case):
    root = case["root"]
    plan = {
        "protocol_id": probe.PROTOCOL,
        "protocol": write(root, "docs/age-evaluator.json", case["age_evaluator_protocol"]),
        "age_protocol": case["plan"]["age_protocol"],
        "n0_manifest": case["plan"]["n0_manifest"],
        "registration_report": case["plan"]["registration_report"],
        "identity_protocol": case["plan"]["protocol"],
        "identity_report": write(
            root, "output/research/identity/report.json", case["identity_report"]
        ),
        "source_acquisition": write(
            root, "output/research/acquisition/sources.json", case["source_acquisition"]
        ),
        "model_acquisition": write(
            root, "output/research/acquisition/model.json", case["model_acquisition"]
        ),
        "environment": write(
            root, "output/research/age-input/environment.json", copy.deepcopy(ENVIRONMENT)
        ),
        "source_files": [pin(root / name, root) for name in probe.SOURCES],
    }
    case["age_plan"] = plan
    return root / write(root, "output/research/age-input/study-plan.json", plan)["path"]


def run(case):
    return probe.build_report(case["root"], freeze(case), case["age_factory"])


def original(subject, label, estimate, *, group="development", roles=None):
    return {
        "subject_id": subject,
        "group": group,
        "roles": ["original"] if roles is None else roles,
        "source_age_label": label,
        "status": "ok" if estimate is not None else "NO_FACE",
        "age_estimate": estimate,
    }


def policy():
    return json.loads((ROOT / "docs/age-evaluator-v1.json").read_text("utf-8"))


def select_original(rows, group="development", age_stratum="all"):
    return next(row for row in rows if row["group"] == group and row["age_stratum"] == age_stratum)


def percentile(values, quantile):
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = math.floor(position)
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[min(low + 1, len(ordered) - 1)] * fraction


def reference_bootstrap(vectors, stratum_key):
    """Independent protocol arithmetic, rather than calling producer helpers."""
    seed = 20261023 + int(hashlib.sha256(stratum_key.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    metrics = list(vectors[0])
    draws = {metric: [] for metric in metrics}
    for _ in range(1000):
        indices = [rng.randrange(len(vectors)) for _ in vectors]
        for metric in metrics:
            value = sum(vectors[index][metric] for index in indices) / len(indices)
            draws[metric].append(math.sqrt(value) if metric == "rmse" else value)
    return {
        metric: [percentile(values, 0.025), percentile(values, 0.975)]
        for metric, values in draws.items()
    }


def test_crop_uses_floor_ceil_and_clipping_without_padding():
    assert probe.crop_bounds([-1.2, 2.7, 11.1, 30.2, *FACE[4:]], 16, 20) == [0, 2, 10, 20]
    assert probe.crop_bounds([1.1, 2.1, 0.1, 0.1, *FACE[4:]], 16, 20) == [1, 2, 2, 3]


@pytest.mark.parametrize(
    "box", [[18, 0, 2, 2], [1, 1, 0, 2], [1, 1, -1, 2], [float("nan"), 1, 2, 2]]
)
def test_empty_or_nonfinite_crop_is_rejected(box):
    with pytest.raises(ValueError):
        probe.crop_bounds([*box, *FACE[4:]], 16, 16)


def test_age_scalar_retains_fraction_and_out_of_range_values_without_clamping():
    for age in (-12.375, 142.625):
        result = probe.prediction({"age": age, "raw_age": (age - 61) / 122})
        assert result["age_estimate"] == age
    with pytest.raises(ValueError, match="INVALID_AGE_FORMULA"):
        probe.prediction({"age": 25, "raw_age": 25})
    with pytest.raises(ValueError):
        probe.prediction({"age": True, "raw_age": 0.0})


def test_percentile_interval_interpolates_between_adjacent_order_statistics():
    assert probe._percentile([30.0, 0.0, 20.0, 10.0], 0.25) == 7.5
    assert probe._percentile([30.0, 0.0, 20.0, 10.0], 0.975) == pytest.approx(29.25)


def test_fake_run_closes_crops_preserves_every_request_and_false_flags(case):
    report = run(case)
    assert report["image_counts"] == {"requested": 5, "successful": 5, "failed": 0}
    assert report["execution_status"] == "complete"
    assert len(report["records"]) == 5
    assert len(report["generated_pairs"]) == 3
    assert report["quality_threshold"] is None
    assert all(report[key] is False for key in probe.FALSE_FLAGS)
    assert case["predictor"].closed
    for image in case["predictor"].calls:
        with pytest.raises(ValueError, match="closed"):
            image.getpixel((0, 0))


def test_cached_detection_failure_skips_predict_without_losing_any_request(case):
    record = case["identity_report"]["records"][0]
    record.update(status="NO_FACE", embedding=None)
    case["identity_report"]["image_counts"].update(successful=4, failed=1)
    case["identity_report"]["execution_status"] = "completed_with_failures"
    case["age_evaluator_protocol"]["cohort"]["expected_reused_detection_failures"] = 1
    report = run(case)
    assert len(report["records"]) == 5 and len(case["predictor"].calls) == 4
    assert report["records"][0]["age_estimate"] is None
    assert report["records"][0]["status"] == "NO_FACE"
    assert len(report["generated_pairs"]) == 3
    assert all(pair["status"] == "failed" for pair in report["generated_pairs"])


def test_cached_dimensions_must_match_exif_corrected_decoding(case):
    case["identity_report"]["records"][0]["width"] = 100
    report = run(case)
    assert report["records"][0]["age_estimate"] is None
    assert len(case["predictor"].calls) == 4


def test_decoded_pixel_resource_limit_fails_before_predictor(case, monkeypatch):
    settings = probe.Settings(max_image_bytes=10485760, max_image_pixels=100)
    monkeypatch.setattr(probe, "Settings", lambda **_: settings)
    report = run(case)
    assert not case["predictor"].calls and case["predictor"].closed
    assert {row["status"] for row in report["records"]} == {"INPUT_TOO_LARGE"}
    assert len(report["records"]) == 5 and len(report["generated_pairs"]) == 3


def test_source_hash_is_checked_before_decode_and_full_denominator_survives(case, monkeypatch):
    plan = freeze(case)
    source = case["manifest"]["bridge_cases"][0]["source"]
    (case["root"] / source["path"]).write_bytes(b"changed")
    decoded, decoder = [], probe.decode_image

    def decode(data, *args):
        decoded.append(data)
        return decoder(data, *args)

    monkeypatch.setattr(probe, "decode_image", decode)
    report = probe.build_report(case["root"], plan, case["age_factory"])
    assert len(decoded) == 4 and b"changed" not in decoded
    assert report["integrity_status"] == "failed"
    assert report["image_counts"]["requested"] == 5
    assert all(pair["status"] == "failed" for pair in report["generated_pairs"])


def test_environment_mismatch_closes_predictor_without_predicting(case):
    case["predictor"].environment["python_version"] = "different"
    with pytest.raises(ValueError, match="environment"):
        run(case)
    assert case["predictor"].closed and not case["predictor"].calls


def test_environment_ignores_sys_path_metadata_but_keeps_installed_dependencies(
    tmp_path, monkeypatch
):
    before = probe._environment()
    distribution = tmp_path / "age_evaluator_path_poison-999.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: age-evaluator-path-poison\nVersion: 999\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    # Prove the ordinary sys.path lookup sees the foreign metadata; the
    # installation snapshot must still describe the same actual environment.
    assert importlib.metadata.version("age-evaluator-path-poison") == "999"
    after = probe._environment()
    assert after == before
    assert "age-evaluator-path-poison" not in after["packages"]
    assert after["packages"]["pydantic"] == importlib.metadata.version("pydantic")


def test_original_macro_and_rmse_weight_subjects_instead_of_images():
    records = [original("a", 20, 20)] * 3 + [original("b", 20, 30)]
    summary = select_original(probe.aggregate_originals(records, policy()))
    assert summary["requested"] == summary["scored"] == 4
    assert summary["eligible_units"] == summary["effective_units"] == 2
    assert summary["macro"]["mae"] == 5.0  # An image-pooled MAE would be 2.5.
    assert summary["macro"]["bias"] == 5.0
    assert summary["macro"]["rmse"] == pytest.approx(math.sqrt(50))
    assert summary["macro"]["rmse"] != 5.0  # Averaging subject RMSE is a different estimand.


def test_generated_source_labels_are_not_original_age_truth_and_unknown_stays_null():
    records = [
        original("a", 20, 25),
        original("a", 20, 90, roles=["generated"]),
        original("external:unknown", None, 40, roles=["source"]),
    ]
    summary = select_original(probe.aggregate_originals(records, policy()))
    assert summary["requested"] == summary["scored"] == 1
    assert summary["macro"]["mae"] == 5
    assert records[2]["source_age_label"] is None


def test_original_failure_retains_null_units_and_empty_strata():
    summary = select_original(probe.aggregate_originals([original("a", 20, None)], policy()))
    assert summary["requested"] == summary["null"] == 1 and summary["scored"] == 0
    assert summary["eligible_units"] == 1 and summary["effective_units"] == 0
    assert all(value is None for value in summary["macro"].values())
    assert all(value is None for value in summary["bootstrap"]["intervals"].values())
    empty = select_original(probe.aggregate_originals([], policy()), age_stratum="70")
    assert empty["requested"] == empty["eligible_units"] == empty["effective_units"] == 0
    assert all(value is None for value in empty["macro"].values())


def test_bootstrap_resamples_effective_subject_vectors_with_shared_metric_draws():
    records = [
        original("a", 20, 20),
        original("a", 20, 24),
        original("b", 20, 13),
        original("c", 20, 35),
        original("d", 20, 50),
        original("failed", 20, None),
    ]
    summary = select_original(probe.aggregate_originals(records, policy()))
    expected = reference_bootstrap(
        [
            {"mae": 2.0, "bias": 2.0, "rmse": 8.0},
            {"mae": 7.0, "bias": -7.0, "rmse": 49.0},
            {"mae": 15.0, "bias": 15.0, "rmse": 225.0},
            {"mae": 30.0, "bias": 30.0, "rmse": 900.0},
        ],
        "original/development/all",
    )
    assert summary["effective_units"] == 4 and summary["eligible_units"] == 5
    for metric, interval in expected.items():
        assert summary["bootstrap"]["intervals"][metric] == pytest.approx(interval)
    reordered = select_original(probe.aggregate_originals(list(reversed(records)), policy()))
    assert reordered["bootstrap"] == summary["bootstrap"]


def test_single_subject_interval_is_degenerate_and_stratum_seed_is_distinct():
    summaries = probe.aggregate_originals([original("a", 20, 23)], policy())
    overall, stratum = select_original(summaries), select_original(summaries, age_stratum="20-29")
    assert overall["bootstrap"]["intervals"]["mae"] == [3.0, 3.0]
    assert overall["effective_units"] == 1
    assert overall["bootstrap"]["seed"] != stratum["bootstrap"]["seed"]


def test_within_subject_delta_uses_signed_label_order_and_keeps_same_age_pair():
    records = [original("a", 45, 40), original("a", 20, 30), original("a", 45, 43)]
    requests = [
        {
            "pair_id": index,
            "type": "original_comparison",
            "group": "development",
            "category": category,
            "unit": "a",
            "left_id": 0,
            "right_id": right,
            "label_age_difference": difference,
        }
        for index, right, category, difference in [
            (0, 1, "same_identity_cross_age", 25),
            (1, 2, "same_identity_same_age", 0),
        ]
    ]
    pairs = probe.score_within(requests, records)
    assert len(pairs) == 2
    assert pairs[0]["prediction_delta_error"] == 15.0
    assert pairs[1]["prediction_delta_error"] == 3.0


def test_generated_condition_static_baseline_and_reduction_are_paired_not_age_accuracy():
    records = [
        {**original("a", 30, 40, roles=["source"]), "target_condition": None},
        {**original("a", 30, 60, roles=["generated"]), "target_condition": 70},
        {**original("a", 30, None, roles=["generated"]), "target_condition": 45},
    ]
    requests = [
        {
            "pair_id": index,
            "type": "source_generated_comparison",
            "group": "development",
            "category": "other_condition",
            "unit": "source-a",
            "left_id": 0,
            "right_id": index + 1,
            "label_age_difference": 40 if index == 0 else 15,
        }
        for index in range(2)
    ]
    pairs = probe.score_generated(requests, records)
    assert pairs[0]["prediction_shift"] == 20
    assert pairs[0]["condition_deviation"] == -10
    assert pairs[0]["static_condition_deviation"] == -30
    assert pairs[0]["absolute_condition_reduction"] == 20
    # Complete-case pairing keeps a source prediction in image output, but does
    # not count its baseline alone when its generated companion failed.
    assert pairs[1]["status"] == "failed"
    assert all(
        pairs[1][metric] is None
        for metric in (
            "prediction_shift",
            "condition_deviation",
            "static_condition_deviation",
            "absolute_condition_reduction",
        )
    )
    summary = next(
        row
        for row in probe.aggregate_generated(pairs, policy())
        if row["category"] == "other_condition"
    )
    assert summary["requested"] == 2 and summary["scored"] == summary["null"] == 1
    assert summary["macro"]["absolute_condition_reduction"] == 20


def test_unknown_source_age_stays_null_while_requested_condition_is_descriptive(case):
    source = case["manifest"]["bridge_cases"][0]
    source["subject_id"] = "external:synthetic"
    source["source"] = identity_tests.photo(case["root"], "data/external/source.png", (22, 77, 88))
    source["source_age"] = {"value": None, "method": "unknown", "independently_verified": False}
    source["same_age_control"] = {"status": "not_applicable_unknown_source_age", "target_age": None}
    case["protocol"]["expected_known_controls"] = 0
    case["manifest"]["summary"]["control_statuses"] = {"not_applicable_unknown_source_age": 1}
    case["manifest"]["summary"]["same_age_controls_complete"] = True
    for row in case["registration"]["records"]:
        row["source_age_label"] = None
        row["subject_id"] = "external:synthetic"
    case["identity_protocol"]["cohort"]["expected_unique_images"] = 6
    case["age_evaluator_protocol"]["cohort"]["expected_unique_images"] = 6
    prepare_identity(case)
    report = run(case)
    source_record = next(row for row in report["records"] if row["roles"] == ["source"])
    assert source_record["source_age_label"] is None
    assert {pair["category"] for pair in report["generated_pairs"]} == {"unknown_source_age"}
    assert (
        sum(
            row["requested"] for row in report["original_aggregates"] if row["age_stratum"] == "all"
        )
        == 2
    )


def test_nonfinite_estimate_is_explicit_failure_and_does_not_enter_statistics(case):
    case["predictor"].behavior = lambda _: {"age": float("nan"), "raw_age": float("nan")}
    report = run(case)
    assert report["image_counts"] == {"requested": 5, "successful": 0, "failed": 5}
    assert all(row["age_estimate"] is None for row in report["records"])
    assert all(pair["status"] == "failed" for pair in report["generated_pairs"])


def test_image_drift_after_aggregation_and_bootstrap_clears_predictions_and_recomputes(
    case, monkeypatch
):
    source = case["manifest"]["bridge_cases"][0]["source"]
    aggregate, calls = probe.aggregate_generated, []

    def mutate(pairs, protocol):
        summary = aggregate(pairs, protocol)
        calls.append(summary)
        if len(calls) == 1:
            (case["root"] / source["path"]).write_bytes(b"late source drift")
        return summary

    monkeypatch.setattr(probe, "aggregate_generated", mutate)
    report = run(case)
    assert len(calls) == 2
    assert report["records"][0]["status"] == "source_changed"
    assert report["records"][0]["age_estimate"] is None
    assert report["records"][0]["raw_age_estimate"] is None
    assert all(pair["status"] == "failed" for pair in report["generated_pairs"])
    assert report["integrity_status"] == "failed"
    for summary in report["generated_aggregates"]:
        assert all(value is None for value in summary["macro"].values())
        assert all(value is None for value in summary["bootstrap"]["intervals"].values())


def test_new_drift_during_recomputation_triggers_another_full_statistics_pass(case, monkeypatch):
    sources = [row["source"] for row in case["identity_report"]["records"][:2]]
    aggregate, calls = probe.aggregate_generated, []

    def mutate(pairs, protocol):
        result = aggregate(pairs, protocol)
        calls.append(result)
        if len(calls) <= 2:
            (case["root"] / sources[len(calls) - 1]["path"]).write_bytes(b"late drift")
        return result

    monkeypatch.setattr(probe, "aggregate_generated", mutate)
    report = run(case)
    assert len(calls) == 3
    assert [row["status"] for row in report["records"][:2]] == ["source_changed"] * 2
    assert all(row["age_estimate"] is None for row in report["records"][:2])
    assert report["image_counts"] == {"requested": 5, "successful": 3, "failed": 2}


def test_metadata_drift_after_scoring_rejects_report_and_closes_predictor(case, monkeypatch):
    aggregate = probe.aggregate_generated

    def mutate(pairs, protocol):
        (case["root"] / "docs/age-evaluator.json").write_text("{}", encoding="utf-8")
        return aggregate(pairs, protocol)

    monkeypatch.setattr(probe, "aggregate_generated", mutate)
    with pytest.raises(ValueError, match="Metadata pin mismatch"):
        run(case)
    assert case["predictor"].closed


def test_exif_corrected_frame_and_predictor_crop_are_both_closed(case, monkeypatch):
    source = case["manifest"]["bridge_cases"][0]["source"]
    path = case["root"] / source["path"]
    with Image.new("RGB", (32, 16), (21, 41, 61)) as image:
        exif = Image.Exif()
        exif[274] = 6
        image.save(path, format="JPEG", exif=exif)
    source.update(pin(path, case["root"]))
    case["manifest"]["adult_images"][0].update(source)
    prepare_identity(case)
    assert case["identity_report"]["records"][0]["width"] == 16
    assert case["identity_report"]["records"][0]["height"] == 32
    decoder, decoded = probe.decode_image, []

    def decode(*args):
        image = decoder(*args)
        decoded.append(image)
        return image

    monkeypatch.setattr(probe, "decode_image", decode)
    report = run(case)
    assert report["records"][0]["status"] == "ok"
    assert len(decoded) == 5
    for image in [*decoded, *case["predictor"].calls]:
        with pytest.raises(ValueError, match="closed"):
            image.getpixel((0, 0))


@pytest.mark.parametrize("role", ["model", "source"])
def test_fixed_artifact_drift_prevents_factory_creation(case, role):
    plan = freeze(case)
    artifact = (
        case["model_acquisition"]["model"]
        if role == "model"
        else case["source_acquisition"]["artifacts"][0]
    )
    (case["root"] / artifact["path"]).write_bytes(b"changed")
    created = []
    with pytest.raises(ValueError):
        probe.build_report(case["root"], plan, lambda _: created.append(True))
    assert not created


@pytest.mark.parametrize("role", ["model", "source"])
def test_late_fixed_artifact_drift_rejects_publication_and_closes_predictor(case, role):
    artifact = (
        case["model_acquisition"]["model"]
        if role == "model"
        else case["source_acquisition"]["artifacts"][0]
    )

    def mutate(_):
        (case["root"] / artifact["path"]).write_bytes(b"late drift")
        return {"age": 25.0, "raw_age": (25.0 - 61) / 122}

    case["predictor"].behavior = mutate
    with pytest.raises(ValueError):
        run(case)
    assert case["predictor"].closed


def test_output_refuses_existing_evidence_before_any_evaluation(case, monkeypatch):
    output = case["root"] / "output/research/existing"
    output.mkdir(parents=True)
    sentinel = output / "report.json"
    sentinel.write_text("preserved", encoding="utf-8")
    calls = []
    monkeypatch.setattr(probe, "build_report", lambda *args: calls.append(True))
    assert (
        probe.main(
            [
                "--root",
                str(case["root"]),
                "--study-plan",
                "missing.json",
                "--output-dir",
                "output/research/existing",
            ]
        )
        == 1
    )
    assert sentinel.read_text("utf-8") == "preserved" and not calls
