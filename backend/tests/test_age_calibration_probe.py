"""Synthetic arithmetic and closed-input counterexamples; no real age scoring."""

import copy
import hashlib
import importlib.util
import json
import math
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "age_calibration_probe", _ROOT / "tools/age_calibration_probe.py"
)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def row(subject, prediction, *, label=25, group="development"):
    return {
        "subject_id": subject,
        "group": group,
        "source_age_label": label,
        "age_estimate": prediction,
        "status": "NO_FACE" if prediction is None else "ok",
    }


def test_offset_weights_identities_equally_and_never_uses_calibration_labels():
    records = [*[row("A", 35) for _ in range(8)], row("B", 25)]
    records.append(row("C", 1000, group="calibration_research"))
    fitted = probe.fit_offset(records)
    assert fitted["offset_years"] == -5
    assert len(fitted["development_unit_biases"]) == 2
    altered = [dict(r, age_estimate=-1000) if r["group"] != "development" else r for r in records]
    assert probe.fit_offset(altered) == fitted


def test_offset_does_not_clip_predictions_or_turn_unknown_results_into_numbers():
    records = [row("A", 90), row("B", -10), row("C", None)]
    result = probe.summary(records, -5, "negative-unclipped")
    assert result["requested"] == 3 and result["scored"] == 2 and result["failed"] == 1
    assert result["raw"]["mae"] == 50
    assert result["corrected"]["mae"] == 50
    assert result["corrected"]["bias"] == 10


def test_finite_prediction_bound_allows_its_legitimate_full_correction_offset():
    result = probe.calibrate([row("A", -1e6, label=20)])
    assert result["fit"]["offset_years"] == 1000020
    overall = next(summary for summary in result["summaries"] if summary["age_stratum"] == "all")
    assert overall["corrected"]["mae"] == overall["corrected"]["rmse"] == 0


def test_rmse_uses_identity_mean_squared_error_before_square_root():
    result = probe.summary([row("A", 25), row("A", 29), row("B", 35)], -2, "rmse")
    assert result["raw"]["mae"] == 6
    assert result["raw"]["rmse"] == pytest.approx(math.sqrt(54))
    assert result["corrected"]["rmse"] == pytest.approx(math.sqrt(34))
    assert result["reductions"]["rmse"] == pytest.approx(math.sqrt(54) - math.sqrt(34))


def test_failures_remain_denominators_and_fully_failed_identity_is_not_zero_error():
    result = probe.summary([row("A", 35), row("A", None), row("B", None)], -5, "missing")
    assert (result["requested"], result["scored"], result["failed"]) == (3, 1, 2)
    assert result["eligible_units"] == 2 and result["effective_units"] == 1
    assert result["raw"]["mae"] == 10
    assert result["corrected"]["mae"] == 5
    assert result["requested_mae_bounds"]["raw"] == {"lower": 2.5, "upper": None}
    assert result["requested_mae_bounds"]["corrected"] == {"lower": 1.25, "upper": None}


def test_complete_cohort_requested_error_bounds_collapse_but_empty_stratum_is_null():
    complete = probe.summary([row("A", 35), row("B", 25)], -5, "complete")
    assert complete["requested_mae_bounds"]["raw"] == {"lower": 5, "upper": 5}
    assert complete["requested_mae_bounds"]["corrected"] == {"lower": 5, "upper": 5}
    empty = probe.summary([], -5, "empty")
    assert empty["requested"] == empty["effective_units"] == 0
    assert empty["raw"] == {"mae": None, "bias": None, "rmse": None}
    assert empty["requested_mae_bounds"]["raw"] == {"lower": None, "upper": None}
    assert all(metric["low"] is None for metric in empty["bootstrap"]["metrics"].values())


def test_all_failed_development_refuses_to_invent_a_calibration_offset():
    with pytest.raises(ValueError):
        probe.fit_offset([row("A", None), row("C", 27, group="calibration_research")])


def test_huge_json_integer_rejects_before_float_finiteness_conversion():
    enormous = json.loads("1" + "0" * 1000)
    with pytest.raises(ValueError):
        probe.fit_offset([row("A", enormous)])


def test_main_accepts_argparse_path_output_and_publishes_report(study, capsys):
    args = study["args"]
    result = probe.main(
        [
            "--root",
            str(args.root),
            "--study-plan",
            str(args.study_plan),
            "--output-dir",
            "output/research/main-result",
        ]
    )
    assert result == 0
    assert json.loads(capsys.readouterr().out)["offset_years"] == -5
    assert (args.root / "output/research/main-result/report.json").is_file()


@pytest.mark.parametrize("name", ["../escaped-output", "absolute"])
def test_main_path_normalization_still_rejects_parent_and_absolute_output(study, name):
    args = study["args"]
    target = args.root / "output/research/absolute" if name == "absolute" else Path(name)
    assert (
        probe.main(
            [
                "--root",
                str(args.root),
                "--study-plan",
                str(args.study_plan),
                "--output-dir",
                str(target),
            ]
        )
        == 1
    )
    assert not (args.root / target).exists()


def test_entirely_failed_summary_has_null_conditional_metrics_and_unbounded_missing_error():
    result = probe.summary([row("A", None), row("A", None)], -5, "all-failed")
    assert result["requested"] == result["failed"] == 2
    assert result["effective_units"] == 0 and result["eligible_units"] == 1
    assert result["raw"] == {"mae": None, "bias": None, "rmse": None}
    assert result["requested_mae_bounds"]["corrected"] == {"lower": 0, "upper": None}
    assert all(
        metric["valid_replicates"] == 0 for metric in result["bootstrap"]["metrics"].values()
    )


def test_paired_bootstrap_matches_an_independent_subject_draw_sequence():
    records = [row("A", 25), row("B", 35)]
    key = "paired-independent"
    result = probe.summary(records, -5, key)
    rng = random.Random(20261027 + int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    replicates = {"raw_mae": [], "corrected_mae": [], "mae_reduction": []}
    for _ in range(1000):
        indexes = [rng.randrange(2) for _ in range(2)]
        raw_mae = math.fsum([0.0, 10.0][i] for i in indexes) / 2
        replicates["raw_mae"].append(raw_mae)
        replicates["corrected_mae"].append(5.0)
        replicates["mae_reduction"].append(raw_mae - 5)
    for metric, values in replicates.items():
        encoded = json.dumps(values, separators=(",", ":"), allow_nan=False).encode()
        assert (
            result["bootstrap"]["metrics"][metric]["sha256"] == hashlib.sha256(encoded).hexdigest()
        )
    assert probe.summary(list(reversed(records)), -5, key) == result


def test_single_effective_identity_has_a_degenerate_conditional_interval():
    result = probe.summary([row("A", 31), row("B", None)], -2, "singleton")
    metric = result["bootstrap"]["metrics"]["corrected_mae"]
    assert metric["low"] == metric["high"] == 4


def test_calibration_returns_both_groups_and_all_empty_age_strata():
    result = probe.calibrate([row("A", 30), row("C", 42, label=40, group="calibration_research")])
    assert result["fit"]["offset_years"] == -5
    assert len(result["summaries"]) == 14
    assert {(s["group"], s["age_stratum"]) for s in result["summaries"]} == {
        (group, stratum) for group in probe.GROUPS for stratum in ("all", *probe.STRATA)
    }
    calibration = next(
        s
        for s in result["summaries"]
        if s["group"] == "calibration_research" and s["age_stratum"] == "all"
    )
    assert calibration["corrected"]["mae"] == 3


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n").encode()


def pin(name, data):
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def source_pin(name):
    return pin("unread-photographs/" + name + ".JPG", name.encode())


def persist(study, overrides=None):
    """Re-freeze valid provenance after a synthetic content mutation."""
    root, documents, roles = study["args"].root, study["documents"], {}
    overrides = overrides or {}
    for role in ("protocol", "age_protocol", "n0_manifest"):
        raw = json_bytes(documents[role])
        name = "frozen/" + role + ".json"
        (root / name).write_bytes(raw)
        roles[role] = pin(name, raw)
    documents["age_study_plan"]["protocol"] = roles["age_protocol"]
    documents["age_study_plan"]["n0_manifest"] = roles["n0_manifest"]
    raw = json_bytes(documents["age_study_plan"])
    (root / "frozen/age_study_plan.json").write_bytes(raw)
    roles["age_study_plan"] = pin("frozen/age_study_plan.json", raw)
    documents["age_report"]["inputs"] = [
        roles[k] for k in ("age_study_plan", "age_protocol", "n0_manifest")
    ]
    raw = overrides.get("age_report")
    if raw is None:
        raw = json_bytes(documents["age_report"])
    (root / "frozen/age_report.json").write_bytes(raw)
    roles["age_report"] = pin("frozen/age_report.json", raw)
    documents["age_verification"]["evidence"] = [roles[k] for k in ("age_study_plan", "age_report")]
    raw = json_bytes(documents["age_verification"])
    (root / "frozen/age_verification.json").write_bytes(raw)
    roles["age_verification"] = pin("frozen/age_verification.json", raw)
    roles = {role: roles[role] for role in probe.ROLES}
    plan = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL_ID,
        "runtime": probe.integrity.runtime_fingerprint(),
        "roles": roles,
        "inputs": [
            *roles.values(),
            *[pin(name, (root / name).read_bytes()) for name in probe.SOURCES],
        ],
    }
    (root / study["args"].study_plan).write_bytes(json_bytes(plan))
    study["plan"] = plan
    return study


def make_study(root):
    root.mkdir(exist_ok=True)
    (root / "frozen").mkdir()
    for name in probe.SOURCES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((_ROOT / name).read_bytes())
    originals = [
        row("A", 35),
        row("A", 45, label=35),
        row("B", 25),
        row("B", None, label=35),
        row("C", 47, label=45, group="calibration_research"),
    ]
    records, adults = [], []
    for index, original in enumerate(originals):
        source = source_pin(f"{original['subject_id']}-{index}")
        check = {**source, "verification": "verified", "matches_declared": True}
        records.append(
            {
                **original,
                "image_id": index,
                "source": source,
                "roles": ["original", "source"] if index == 0 else ["original"],
                "raw_age_estimate": None
                if original["age_estimate"] is None
                else (original["age_estimate"] - 61) / 122,
                "initial_source_check": check,
                "final_source_check": check.copy(),
                "source_changed": False,
            }
        )
        adults.append(
            {
                **source,
                "subject_id": original["subject_id"],
                "group": original["group"],
                "source_age": original["source_age_label"],
            }
        )
    adults.append(
        {
            **source_pin("held-out-H"),
            "subject_id": "H",
            "group": "evaluation_research_holdout",
            "source_age": 40,
        }
    )
    for index, (role, subject, label, predicted) in enumerate(
        (("generated", "A", 25, 45), ("source", "external:synthetic", None, 40)), 5
    ):
        records.append(
            {
                "image_id": index,
                "source": source_pin(f"excluded-{index}"),
                "roles": [role],
                "subject_id": subject,
                "group": "development",
                "source_age_label": label,
                "status": "ok",
                "age_estimate": predicted,
                "raw_age_estimate": (predicted - 61) / 122,
                **(
                    {"source_id": "bridge-A", "target_condition": 45} if role == "generated" else {}
                ),
            }
        )
    old_flags = {
        "research_only": True,
        **dict.fromkeys(
            (
                "age_quality_accepted",
                "years_calibrated",
                "independent_evaluation",
                "training_overlap_excluded",
                "legal_permission_established",
                "service_ready",
                "production_enabled",
                "g3_complete",
            ),
            False,
        ),
    }
    cohort = {
        "groups": list(probe.GROUPS),
        "expected_originals": 5,
        "expected_generated": 1,
        "expected_sources": 2,
        "expected_unique_images": 7,
        "expected_reused_detection_failures": 1,
    }
    n0 = {
        "protocol_id": "agemorph3d-age-research-v1",
        "research_only": True,
        "training_use": False,
        "service_ready": False,
        "g3_complete": False,
        "identities": [
            {"subject_id": subject, "group": group}
            for subject, group in (
                ("A", "development"),
                ("B", "development"),
                ("C", "calibration_research"),
                ("H", "evaluation_research_holdout"),
            )
        ],
        "adult_images": adults,
    }
    report = {
        "protocol_id": "agemorph3d-age-evaluator-v1",
        **old_flags,
        "quality_threshold": None,
        "integrity_status": "passed",
        "execution_status": "completed_with_failures",
        "models_closed": True,
        "holdout_age_predictions_extracted": False,
        "images_or_crops_written": False,
        "image_counts": {"requested": 7, "successful": 6, "failed": 1},
        "records": records,
    }
    study = {
        "args": SimpleNamespace(
            root=root, study_plan="frozen/study-plan.json", output_dir="output/research/result"
        ),
        "documents": {
            "protocol": json.loads((_ROOT / "docs/age-calibration-v1.json").read_bytes()),
            "age_protocol": {
                "protocol_id": "agemorph3d-age-evaluator-v1",
                "flags": old_flags,
                "quality_threshold": None,
                "cohort": cohort,
            },
            "age_study_plan": {
                "protocol_id": "agemorph3d-age-evaluator-v1",
                "unread_model_descendant": {
                    "path": "must-not-open.safetensors",
                    "bytes": 10**9,
                    "sha256": "c" * 64,
                },
            },
            "age_verification": {},
            "age_report": report,
            "n0_manifest": n0,
        },
    }
    return persist(study)


@pytest.fixture
def study(tmp_path):
    return make_study(tmp_path)


def test_full_synthetic_run_excludes_generated_and_source_only_without_opening_images(
    study, monkeypatch
):
    native_open = Path.open
    allowed = {str((study["args"].root / p["path"]).resolve()) for p in study["plan"]["inputs"]}
    allowed.add(str((study["args"].root / study["args"].study_plan).resolve()))
    read_paths = []

    def guarded_open(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if "r" in mode and str(path.resolve()).startswith(str(study["args"].root.resolve())):
            read_paths.append(str(path.resolve()))
            assert str(path.resolve()) in allowed
        return native_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = probe.run(study["args"])
    assert result["fit"]["offset_years"] == -5
    assert len(result["summaries"]) == 14
    assert (study["args"].root / study["args"].output_dir / "report.json").is_file()
    assert result["quality_threshold"] is None
    assert all(result[key] is value for key, value in probe.FLAGS.items())
    assert result["accounting"]["original_requested"] == 5
    assert result["accounting"]["original_failed"] == 1
    assert result["accounting"]["excluded_generated"] == 1
    assert result["accounting"]["excluded_source_only"] == 1
    assert not any("unread-photographs" in path for path in read_paths)


@pytest.mark.parametrize(
    "mutation",
    [
        "holdout",
        "duplicate",
        "initial-check",
        "final-check",
        "formula",
        "failure-value",
        "flag",
        "policy",
        "group-leak",
        "generated-as-original",
    ],
)
def test_rebound_metadata_still_rejects_invalid_scoring_or_provenance(study, mutation):
    docs = study["documents"]
    record = docs["age_report"]["records"][0]
    if mutation == "holdout":
        record["source"] = {
            k: docs["n0_manifest"]["adult_images"][-1][k] for k in ("path", "bytes", "sha256")
        }
        record["subject_id"] = "H"
        record["group"] = "evaluation_research_holdout"
    elif mutation == "duplicate":
        docs["age_report"]["records"][1] = copy.deepcopy(record)
    elif mutation == "initial-check":
        record["initial_source_check"]["matches_declared"] = False
    elif mutation == "final-check":
        record["source_changed"] = True
    elif mutation == "formula":
        record["raw_age_estimate"] = 0
    elif mutation == "failure-value":
        docs["age_report"]["records"][3]["age_estimate"] = 30
    elif mutation == "flag":
        docs["age_report"]["years_calibrated"] = True
    elif mutation == "policy":
        docs["protocol"]["selection"]["policy_id"] = "fit-on-calibration-instead"
    elif mutation == "generated-as-original":
        docs["age_report"]["records"][5]["roles"] = ["original"]
        docs["age_protocol"]["cohort"]["expected_originals"] = 6
        docs["age_protocol"]["cohort"]["expected_generated"] = 0
    else:
        docs["n0_manifest"]["identities"][0]["group"] = "calibration_research"
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])
    assert not (study["args"].root / study["args"].output_dir).exists()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1e200, True])
def test_invalid_prediction_magnitudes_and_boolean_values_are_rejected(study, value):
    record = study["documents"]["age_report"]["records"][0]
    if math.isfinite(value):
        record["age_estimate"] = value
        persist(study)
    else:
        raw = json_bytes(study["documents"]["age_report"]).replace(
            b'"age_estimate": 35', b'"age_estimate": 1e999', 1
        )
        persist(study, {"age_report": raw})
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_identical_original_hash_cannot_cross_development_and_calibration(study):
    docs = study["documents"]
    first = docs["n0_manifest"]["adult_images"][0]
    calibration = docs["n0_manifest"]["adult_images"][4]
    calibration["sha256"] = first["sha256"]
    record = docs["age_report"]["records"][4]
    record["source"]["sha256"] = first["sha256"]
    record["initial_source_check"]["sha256"] = first["sha256"]
    record["final_source_check"]["sha256"] = first["sha256"]
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_same_subject_cannot_appear_in_multiple_original_groups(study):
    docs = study["documents"]
    docs["n0_manifest"]["adult_images"][4]["subject_id"] = "A"
    docs["age_report"]["records"][4]["subject_id"] = "A"
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])


@pytest.mark.parametrize("alias", [False, True])
def test_heldout_image_cannot_be_smuggled_into_an_excluded_role(study, alias):
    docs = study["documents"]
    heldout = docs["n0_manifest"]["adult_images"][-1]
    source = {key: heldout[key] for key in ("path", "bytes", "sha256")}
    if alias:
        source["path"] = "unread-photographs/held-out-alias.JPG"
    docs["age_report"]["records"][6]["source"] = source
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])


@pytest.mark.parametrize("location", ["plan", "role"])
def test_non_json_metadata_paths_are_rejected_before_any_binary_read(study, monkeypatch, location):
    binary_name = "frozen/not-json-do-not-open.bin"
    if location == "plan":
        study["args"].study_plan = binary_name
    else:
        previous = study["plan"]["roles"]["age_report"]
        replacement = {**previous, "path": binary_name}
        study["plan"]["roles"]["age_report"] = replacement
        study["plan"]["inputs"] = [
            replacement if item == previous else item for item in study["plan"]["inputs"]
        ]
        (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    native_open = Path.open

    def forbid_binary_read(path, *args, **kwargs):
        assert path.suffix != ".bin", "Metadata rejection must happen before reading the target"
        return native_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbid_binary_read)
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_loaded_integrity_helper_pin_cannot_be_replaced_after_import(study):
    name = "tools/identity_calibration_probe.py"
    raw = (study["args"].root / name).read_bytes() + b"\n# helper substituted after load\n"
    (study["args"].root / name).write_bytes(raw)
    study["plan"]["inputs"] = [
        pin(name, raw) if p["path"] == name else p for p in study["plan"]["inputs"]
    ]
    (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_frozen_input_drift_is_rejected_before_any_output(study):
    name = study["plan"]["roles"]["age_report"]["path"]
    with (study["args"].root / name).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError):
        probe.run(study["args"])
    assert not (study["args"].root / study["args"].output_dir).exists()


def test_existing_output_and_runtime_mismatch_are_rejected(study):
    output = study["args"].root / study["args"].output_dir
    output.mkdir(parents=True)
    (output / "keep.txt").write_text("preserve")
    with pytest.raises(ValueError):
        probe.run(study["args"])
    assert (output / "keep.txt").read_text() == "preserve"
    study["args"].output_dir = "output/research/another"
    study["plan"]["runtime"]["python"] = "different interpreter"
    (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_extra_input_cannot_expand_the_closed_read_set(study):
    study["plan"]["inputs"].append(pin("holdout-do-not-open.json", b"never opened"))
    (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_loaded_cli_pin_cannot_be_replaced_after_import(study):
    name = probe.SOURCES[0]
    raw = (study["args"].root / name).read_bytes() + b"\n# substituted after load\n"
    (study["args"].root / name).write_bytes(raw)
    study["plan"]["inputs"] = [
        pin(name, raw) if p["path"] == name else p for p in study["plan"]["inputs"]
    ]
    (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_late_input_mutation_after_statistics_prevents_report_publication(study, monkeypatch):
    calculate = probe.calibrate

    def mutate_after_calculation(rows):
        result = calculate(rows)
        path = study["args"].root / study["plan"]["roles"]["age_report"]["path"]
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(probe, "calibrate", mutate_after_calculation)
    with pytest.raises(ValueError):
        probe.run(study["args"])
    assert not (study["args"].root / study["args"].output_dir / "report.json").exists()


def test_input_mutation_during_report_serialization_is_rechecked(study, monkeypatch):
    serialize = probe.json.dumps
    mutated = False

    def mutate_after_serialization(value, *args, **kwargs):
        nonlocal mutated
        result = serialize(value, *args, **kwargs)
        if isinstance(value, dict) and "summaries" in value and not mutated:
            mutated = True
            path = study["args"].root / study["plan"]["roles"]["age_report"]["path"]
            path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(probe.json, "dumps", mutate_after_serialization)
    with pytest.raises(ValueError):
        probe.run(study["args"])
    assert mutated
    assert not (study["args"].root / study["args"].output_dir / "report.json").exists()


def test_mutated_frozen_plan_after_calculation_is_rejected(study, monkeypatch):
    calculate = probe.calibrate

    def mutate_plan(rows):
        result = calculate(rows)
        path = study["args"].root / study["args"].study_plan
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(probe, "calibrate", mutate_plan)
    with pytest.raises(ValueError):
        probe.run(study["args"])
    assert not (study["args"].root / study["args"].output_dir / "report.json").exists()


def test_workspace_escape_and_duplicate_json_keys_are_rejected(study):
    study["args"].output_dir = "../escaped-output"
    with pytest.raises(ValueError):
        probe.run(study["args"])
    study["args"].output_dir = "output/research/result"
    path = study["args"].root / study["args"].study_plan
    path.write_bytes(b'{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError):
        probe.run(study["args"])
