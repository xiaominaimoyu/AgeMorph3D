"""Synthetic calibration counterexamples only; no real scores, images or inference."""

import csv
import hashlib
import importlib.util
import io
import json
import math
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools/identity_calibration_probe.py"
_SPEC = importlib.util.spec_from_file_location("identity_calibration_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def trial(
    score, *, group="development", category="same_identity_cross_age", unit="A", subjects=None
):
    return {
        "group": group,
        "category": category,
        "unit": unit,
        "subjects": subjects or unit.split(":"),
        "score": score,
    }


def negative(score, unit="A:B", group="development"):
    return trial(score, group=group, category="different_identity_cross_age", unit=unit)


def test_pair_decisions_precede_unit_average_and_units_have_equal_weight():
    # A mean cosine below .5 must not turn all its comparisons into false nonmatches.
    rows = [trial(0.8), trial(0.1), *[trial(0.6, unit="B") for _ in range(8)]]
    result = probe.class_summary(probe.unit_metrics(rows, "same_identity_cross_age", 0.5))
    assert result["conditional_error_rate"] == 0.25
    assert result["false_decisions"] == 1
    assert result["scored"] == 10
    assert result["eligible_units"] == result["effective_units"] == 2


def test_equality_accepts_and_negative_age_strata_share_one_identity_pair_unit():
    rows = [
        negative(0.5),
        {**negative(0.8), "category": "different_identity_same_age"},
        negative(0.1, "A:C"),
    ]
    summary = probe.class_summary(probe.unit_metrics(rows, "negative", 0.5))
    assert summary["conditional_error_rate"] == 0.5
    assert summary["eligible_units"] == 2
    assert (
        probe.class_summary(probe.unit_metrics([trial(0.5)], "same_identity_cross_age", 0.5))[
            "false_decisions"
        ]
        == 0
    )


def test_missing_units_have_null_conditional_error_and_unknown_outcome_bounds():
    rows = [trial(0.1), trial(None), trial(None, unit="B")]
    result = probe.class_summary(probe.unit_metrics(rows, "same_identity_cross_age", 0.5))
    assert result["requested"] == 3 and result["scored"] == 1 and result["failed"] == 2
    assert result["conditional_error_rate"] == 1
    assert result["requested_error_lower"] == 0.25
    assert result["requested_error_upper"] == 1
    assert result["eligible_units"] == 2 and result["effective_units"] == 1
    assert result["units"][1]["conditional_error_rate"] is None
    assert result["units"][1]["requested_error_lower"] == 0
    assert result["units"][1]["requested_error_upper"] == 1
    empty = probe.class_summary([])
    assert empty["requested"] == 0 and empty["conditional_error_rate"] is None
    assert empty["requested_error_lower"] is None


def test_discrete_exact_tie_chooses_higher_threshold_and_rejects_development_only():
    curve, selected = probe.development_curve([trial(0.4), negative(0.4)])
    assert len(curve) == 2
    assert selected["threshold"] == math.nextafter(0.4, math.inf)
    assert selected["kind"] == "above_development_max"
    assert selected["selection_key_exact"] == [[1, 1], [1, 2]]
    assert 0.9 >= selected["threshold"]  # The sentinel is not universal reject-all.


def test_calibration_and_generated_same_age_scores_cannot_change_candidates_or_selection():
    base = [trial(0.8), negative(0.2)]
    first = probe.development_curve(base)
    poisoned = [
        *base,
        trial(-1, group="calibration_research"),
        negative(1, group="calibration_research"),
        trial(-0.999, category="same_identity_same_age"),
    ]
    assert probe.development_curve(poisoned) == first
    assert all(p["threshold"] != -0.999 for p in first[0])


@pytest.mark.parametrize("rows", [[], [trial(1)], [negative(0)], [trial(None), negative(0)]])
def test_selection_requires_effective_scores_from_both_development_classes(rows):
    with pytest.raises(ValueError, match="Both development"):
        probe.development_curve(rows)


def test_cluster_multiplicity_couples_shared_negative_identities():
    rows = [negative(0.9, "A:B"), negative(0.1, "A:C")]
    units = probe.unit_metrics(rows, "negative", 0.5)
    result = probe.weighted_metrics(units, {"A": 2, "B": 1, "C": 3})
    assert result["eligible_units"] == 2 * 1 + 2 * 3
    assert result["conditional_error_rate"] == 0.25
    assert probe.weighted_metrics(units, {"A": 3})["conditional_error_rate"] is None


def test_bootstrap_uses_all_subjects_and_preserves_empty_class_replicates():
    positive = probe.unit_metrics([trial(0.7)], "same_identity_cross_age", 0.5)
    negative_units = probe.unit_metrics([negative(0.1)], "negative", 0.5)
    result = probe.bootstrap(positive, negative_units, ["A", "B", "C"], 7, 30)
    assert result == probe.bootstrap(positive, negative_units, ["A", "B", "C"], 7, 30)
    assert result["subjects"] == ["A", "B", "C"]  # C has no requests, but remains sampled.
    fmr, fnmr = (result["metrics"][k] for k in ("conditional_fmr", "conditional_fnmr"))
    assert 0 < fmr["null_replicates"] < 30
    assert 0 < fnmr["null_replicates"] < 30
    assert fmr["valid_replicates"] + fmr["null_replicates"] == 30
    assert fmr["percentile_025"] == fmr["percentile_975"] == 0
    assert result["fixed_threshold_reselected"] is False
    assert set(result["metrics"]) == set(probe.METRICS)


def test_bootstrap_bounds_include_fully_unscored_units_and_percentiles_are_linear():
    positive = probe.unit_metrics([trial(None)], "same_identity_cross_age", 0.5)
    value = probe.bootstrap(positive, [], ["A"], 5, 4)
    assert value["metrics"]["conditional_fnmr"]["null_replicates"] == 4
    assert value["metrics"]["requested_fnmr_lower"]["percentile_025"] == 0
    assert value["metrics"]["requested_fnmr_upper"]["percentile_975"] == 1
    assert value["metrics"]["requested_fmr_lower"]["null_replicates"] == 4
    assert probe.percentile([0, 10], 0.025) == 0.25
    assert probe.percentile([], 0.975) is None


def _json_bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def _pin(path, data):
    return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _source_pin(name):
    return {
        "path": "private-synthetic-only/" + name + ".jpg",
        "bytes": 64,
        "sha256": hashlib.sha256(name.encode()).hexdigest(),
    }


def _feature(a, b):
    return [a, b, *[0.0] * 126]


def _score(left, right):
    # Independent fixture generation with ordinary dot / norms for small unit-scale values.
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return max(-1, min(1, dot / math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))))


def make_study(root, *, generated_failed=False, external_subject=None):
    root.mkdir(exist_ok=True)
    files = {}

    def write(path, data):
        path_obj = root / path
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_bytes(data)
        result = _pin(path, data)
        files[path] = result
        return result

    for source in probe.SOURCES:
        write(source, (Path(__file__).resolve().parents[2] / source).read_bytes())
    protocol = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/identity-calibration-v1.json").read_text(
            encoding="utf-8"
        )
    )
    roles = {"protocol": write("docs/calibration.json", _json_bytes(protocol))}
    raw = [
        ("A", "development", 20, _feature(1, 0)),
        ("A", "development", 30, _feature(0.8, 0.6)),
        ("B", "development", 20, _feature(0, 1)),
        ("B", "development", 30, _feature(0.2, 0.98)),
        ("C", "calibration_research", 20, _feature(1, 0)),
        ("C", "calibration_research", 30, _feature(0.9, 0.1)),
        ("C", "calibration_research", 20, _feature(0.95, 0.05)),
        ("D", "calibration_research", 20, _feature(0, 1)),
        ("D", "calibration_research", 30, _feature(0.1, 0.9)),
    ]
    records, adults = [], []
    for index, (subject, group, age, feature) in enumerate(raw):
        pin = _source_pin(f"{subject}-{age}-{index}")
        adults.append({**pin, "subject_id": subject, "group": group, "source_age": age})
        records.append(
            {
                "image_id": index,
                "source": pin,
                "subject_id": subject,
                "roles": ["original", "source"] if index == 0 else ["original"],
                "group": group,
                "source_age_label": age,
                "status": "ok",
                "embedding": feature,
            }
        )
    records.append(
        {
            "image_id": 9,
            "source": _source_pin("generated-A-45"),
            "subject_id": "A",
            "roles": ["generated"],
            "group": "development",
            "source_age_label": 20,
            "source_id": "bridge-A",
            "target_condition": 45,
            "status": "NO_FACE" if generated_failed else "ok",
            "embedding": None if generated_failed else _feature(1, 0),
        }
    )
    if external_subject is not None:
        source_id = external_subject.removeprefix("external:")
        for index, role in ((10, "source"), (11, "generated")):
            records.append(
                {
                    "image_id": index,
                    "source": _source_pin(source_id + "-" + role),
                    "subject_id": external_subject,
                    "roles": [role],
                    "group": "development",
                    "source_age_label": None,
                    "status": "ok",
                    "embedding": _feature(1, 0),
                    **(
                        {"source_id": source_id, "target_condition": 45}
                        if role == "generated"
                        else {}
                    ),
                }
            )
    adults.append(
        {
            **_source_pin("never-opened-holdout"),
            "subject_id": "H",
            "group": "evaluation_research_holdout",
            "source_age": 40,
        }
    )
    identities = [
        {"subject_id": subject, "group": group}
        for subject, group in (
            ("A", "development"),
            ("B", "development"),
            ("C", "calibration_research"),
            ("D", "calibration_research"),
            ("H", "evaluation_research_holdout"),
        )
    ]
    n0 = {
        "protocol_id": "agemorph3d-age-research-v1",
        "research_only": True,
        "training_use": False,
        "service_ready": False,
        "g3_complete": False,
        "identities": identities,
        "adult_images": adults,
    }
    roles["n0_manifest"] = write("frozen/n0.json", _json_bytes(n0))
    old_flags = {
        key: probe.FLAGS[key]
        for key in (
            "research_only",
            "identity_quality_accepted",
            "independent_evaluation",
            "training_overlap_excluded",
            "legal_permission_established",
            "service_ready",
            "production_enabled",
            "g3_complete",
        )
    }
    cohort = {
        "groups": list(probe.GROUPS),
        "expected_originals": 9,
        "expected_generated": 1 + (external_subject is not None),
        "expected_sources": 1 + (external_subject is not None),
        "expected_unique_images": len(records),
        "expected_original_pairs": 16,
        "expected_source_generated_pairs": 1 + (external_subject is not None),
    }
    old = {
        "protocol_id": probe.IDENTITY_ID,
        "quality_threshold": None,
        "flags": old_flags,
        "cohort": cohort,
    }
    roles["identity_protocol"] = write("docs/identity.json", _json_bytes(old))
    old_plan = {
        "protocol_id": probe.IDENTITY_ID,
        "protocol": roles["identity_protocol"],
        "n0_manifest": roles["n0_manifest"],
        "unread_weight_descendant": {
            "path": "absent-model.onnx",
            "bytes": 10**9,
            "sha256": "d" * 64,
        },
    }
    roles["identity_study_plan"] = write("frozen/identity-plan.json", _json_bytes(old_plan))
    rows = []
    for group in probe.GROUPS:
        for left, right in combinations(
            [r["image_id"] for r in records[:9] if r["group"] == group], 2
        ):
            a, b = records[left], records[right]
            same, same_age = (
                a["subject_id"] == b["subject_id"],
                a["source_age_label"] == b["source_age_label"],
            )
            rows.append(
                {
                    "pair_id": len(rows),
                    "type": "original_comparison",
                    "group": group,
                    "category": ("same_identity" if same else "different_identity")
                    + ("_same_age" if same_age else "_cross_age"),
                    "unit": a["subject_id"]
                    if same
                    else ":".join(sorted((a["subject_id"], b["subject_id"]))),
                    "left_id": left,
                    "right_id": right,
                    "left_status": "ok",
                    "right_status": "ok",
                    "status": "scored",
                    "score": format(_score(a["embedding"], b["embedding"]), ".17g"),
                    "label_age_difference": abs(a["source_age_label"] - b["source_age_label"]),
                }
            )
    rows.append(
        {
            "pair_id": len(rows),
            "type": "source_generated_comparison",
            "group": "development",
            "category": "other_condition",
            "unit": "bridge-A",
            "left_id": 0,
            "right_id": 9,
            "left_status": "ok",
            "right_status": records[9]["status"],
            "status": "failed" if generated_failed else "scored",
            "score": "" if generated_failed else "1",
            "label_age_difference": 25,
        }
    )
    if external_subject is not None:
        rows.append(
            {
                "pair_id": len(rows),
                "type": "source_generated_comparison",
                "group": "development",
                "category": "unknown_source_age",
                "unit": external_subject.removeprefix("external:"),
                "left_id": 10,
                "right_id": 11,
                "left_status": "ok",
                "right_status": "ok",
                "status": "scored",
                "score": "1",
                "label_age_difference": "",
            }
        )
    csv_stream = io.StringIO(newline="")
    writer = csv.DictWriter(csv_stream, fieldnames=probe.PAIR_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    roles["identity_pairs"] = write("frozen/pairs.csv", csv_stream.getvalue().encode())
    report = {
        "protocol_id": probe.IDENTITY_ID,
        **old_flags,
        "quality_threshold": None,
        "integrity_status": "passed",
        "models_closed": True,
        "holdout_embeddings_extracted": False,
        "images_or_crops_written": False,
        "pairs_csv": roles["identity_pairs"],
        "inputs": [roles[k] for k in ("identity_study_plan", "identity_protocol", "n0_manifest")],
        "pair_counts": {
            "requested": len(rows),
            "scored": len(rows) - generated_failed,
            "failed": 1 if generated_failed else 0,
        },
        "image_counts": {
            "requested": len(records),
            "successful": len(records) - generated_failed,
            "failed": 1 if generated_failed else 0,
        },
        "records": records,
    }
    roles["identity_report"] = write("frozen/report.json", _json_bytes(report))
    verification = {
        "evidence": [roles[k] for k in ("identity_study_plan", "identity_report", "identity_pairs")]
    }
    roles["identity_verification"] = write("frozen/verification.json", _json_bytes(verification))
    plan = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL_ID,
        "runtime": probe.runtime_fingerprint(),
        "roles": roles,
        "inputs": [*roles.values(), *(files[name] for name in probe.SOURCES)],
    }
    write("frozen/calibration-plan.json", _json_bytes(plan))
    args = SimpleNamespace(
        root=root,
        study_plan="frozen/calibration-plan.json",
        output_dir="output/research/calibration-run",
    )
    return args, plan, report, rows


@pytest.fixture
def study(tmp_path):
    return make_study(tmp_path)


def revise(study, role, value):
    args, plan, report, rows = study
    path = args.root / plan["roles"][role]["path"]
    data = value if isinstance(value, bytes) else _json_bytes(value)
    path.write_bytes(data)
    new = _pin(path.relative_to(args.root).as_posix(), data)
    prior = plan["roles"][role]
    plan["roles"][role] = new
    plan["inputs"] = [new if pin["path"] == prior["path"] else pin for pin in plan["inputs"]]
    (args.root / args.study_plan).write_bytes(_json_bytes(plan))


def test_full_synthetic_study_freezes_one_development_threshold_and_reports_all_groups(study):
    args, plan, _, _ = study
    result = probe.run(args)
    assert (args.root / args.output_dir / "report.json").is_file()
    assert result["input_accounting"]["requested_csv_pairs"] == 17
    assert result["input_accounting"]["excluded_generated_pairs"] == 1
    assert result["input_accounting"]["same_identity_same_age_pairs"] == 1
    assert result["calibration_curve_computed"] is False and result["quality_threshold"] is None
    assert (
        result["groups"]["development"]["fixed_threshold"]
        == result["groups"]["calibration_research"]["fixed_threshold"]
    )
    assert result["groups"]["development"]["same_identity_same_age"]["requested"] == 0
    assert result["groups"]["calibration_research"]["same_identity_same_age"]["requested"] == 1
    assert result["roles"] == plan["roles"]
    assert result["inputs"] == plan["inputs"]
    assert not any(name in json.dumps(result) for name in ('"embedding"', '"face"', '"left_id"'))
    assert all(result[key] is value for key, value in probe.FLAGS.items())


def test_failed_generated_comparison_remains_excluded_without_breaking_original_selection(tmp_path):
    success = probe.run(make_study(tmp_path / "success")[0])
    failed = probe.run(make_study(tmp_path / "failed", generated_failed=True)[0])
    assert failed["development_selection"] == success["development_selection"]
    assert failed["development_curve"] == success["development_curve"]
    assert failed["input_accounting"]["excluded_generated_failed"] == 1
    assert failed["input_accounting"]["failed_original_pairs"] == 0


@pytest.mark.parametrize("subject", ["external:official-866", "external:astronaut"])
def test_historical_external_source_and_generated_ids_are_valid_exclusions(tmp_path, subject):
    baseline = probe.run(make_study(tmp_path / "baseline")[0])
    args, plan, _, _ = make_study(tmp_path / "external", external_subject=subject)
    result = probe.run(args)
    assert result["development_selection"] == baseline["development_selection"]
    assert result["development_curve"] == baseline["development_curve"]
    assert result["input_accounting"]["excluded_generated_pairs"] == 2
    assert result["input_accounting"]["original_pairs"] == 16
    assert result["groups"]["development"]["bootstrap"]["subjects"] == ["A", "B"]
    assert result["groups"]["calibration_research"]["bootstrap"]["subjects"] == ["C", "D"]
    assert all(
        subject not in unit["subjects"]
        for group in result["groups"].values()
        for metric in ("positive_cross_age", "negative_all_ages", "same_identity_same_age")
        for unit in group[metric]["units"]
    )
    metadata = {
        key: json.loads((args.root / pin["path"]).read_text())
        for key, pin in plan["roles"].items()
        if key != "identity_pairs"
    }
    for record in metadata["identity_report"]["records"]:
        if record["subject_id"] == subject:
            record["embedding"] = ["excluded feature must never be normalized"]
    trials, subjects, _ = probe.parse_trials(
        (args.root / plan["roles"]["identity_pairs"]["path"]).read_bytes(), metadata, plan["roles"]
    )
    assert subjects == {"development": ["A", "B"], "calibration_research": ["C", "D"]}
    assert all(subject not in row["subjects"] for row in trials)


@pytest.mark.parametrize("subject", ["external:official-866", "external:astronaut", "A:B"])
def test_external_bookkeeping_ids_cannot_be_disguised_as_original_subjects(study, subject):
    args, plan, _, _ = study
    metadata = {
        key: json.loads((args.root / pin["path"]).read_text())
        for key, pin in plan["roles"].items()
        if key != "identity_pairs"
    }
    metadata["identity_report"]["records"][0]["subject_id"] = subject
    with pytest.raises(ValueError, match="Invalid subject identifier"):
        probe.parse_trials(
            (args.root / plan["roles"]["identity_pairs"]["path"]).read_bytes(),
            metadata,
            plan["roles"],
        )
    assert not (args.root / args.output_dir).exists()


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing", "score", "group", "type", "status", "header", "hugefield"]
)
def test_csv_malformed_relabelled_or_incomplete_requests_are_rejected(study, mutation):
    args, plan, report, rows = study
    metadata = {
        key: json.loads((args.root / pin["path"]).read_text())
        for key, pin in plan["roles"].items()
        if key != "identity_pairs"
    }
    if mutation == "duplicate":
        rows[-1] = rows[0]
    elif mutation == "missing":
        rows.pop()
    elif mutation == "score":
        rows[0]["score"] = "0.12"
    elif mutation == "group":
        rows[0]["group"] = "evaluation_research_holdout"
    elif mutation == "type":
        rows[0]["type"] = "source_generated_comparison"
    elif mutation == "status":
        rows[0]["status"] = "failed"
    elif mutation == "hugefield":
        rows[0]["unit"] = "x" * 257
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=probe.PAIR_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    data = stream.getvalue().encode()
    if mutation == "header":
        data = data.replace(b"pair_id,type", b"type,pair_id", 1)
    with pytest.raises(ValueError):
        probe.parse_trials(data, metadata, plan["roles"])
    assert not (args.root / args.output_dir).exists()


@pytest.mark.parametrize("mutation", ["holdout", "split", "feature", "flag", "policy", "crosslink"])
def test_metadata_provenance_or_saved_feature_errors_fail_closed(study, mutation):
    args, plan, report, _ = study
    metadata = {
        key: json.loads((args.root / pin["path"]).read_text())
        for key, pin in plan["roles"].items()
        if key != "identity_pairs"
    }
    if mutation == "holdout":
        metadata["identity_report"]["records"][0]["source"] = {
            k: metadata["n0_manifest"]["adult_images"][-1][k] for k in ("path", "bytes", "sha256")
        }
    elif mutation == "split":
        metadata["n0_manifest"]["adult_images"][0]["group"] = "calibration_research"
    elif mutation == "feature":
        metadata["identity_report"]["records"][0]["embedding"] = [0] * 128
    elif mutation == "flag":
        metadata["identity_protocol"]["flags"]["service_ready"] = True
    elif mutation == "policy":
        metadata["protocol"]["selection"]["policy_id"] = "different-policy"
    else:
        metadata["identity_study_plan"]["n0_manifest"] = plan["roles"]["identity_protocol"]
    with pytest.raises(ValueError):
        probe.parse_trials(
            (args.root / plan["roles"]["identity_pairs"]["path"]).read_bytes(),
            metadata,
            plan["roles"],
        )
    assert not (args.root / args.output_dir).exists()


def test_extra_input_is_rejected_before_it_can_be_read(study, monkeypatch):
    args, plan, _, _ = study
    extra = _pin("holdout-do-not-open.json", b"unread")
    plan["inputs"].append(extra)
    (args.root / args.study_plan).write_bytes(_json_bytes(plan))
    with pytest.raises(ValueError, match="bounded metadata list"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


def test_loaded_code_pin_cannot_silently_be_replaced_after_import(study):
    args, plan, _, _ = study
    path = args.root / probe.SOURCES[0]
    data = path.read_bytes() + b"\n# replaced loaded module\n"
    path.write_bytes(data)
    plan["inputs"] = [
        _pin(probe.SOURCES[0], data) if row["path"] == probe.SOURCES[0] else row
        for row in plan["inputs"]
    ]
    (args.root / args.study_plan).write_bytes(_json_bytes(plan))
    with pytest.raises(ValueError, match="Loaded CLI differs"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


def test_existing_output_is_preserved(study):
    args, _, _, _ = study
    target = args.root / args.output_dir
    target.mkdir(parents=True)
    sentinel = target / "user.txt"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match="fresh directory"):
        probe.run(args)
    assert sentinel.read_text() == "keep"


def test_output_symlink_cannot_escape_workspace(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "output").mkdir(parents=True)
    outside.mkdir()
    try:
        (root / "output/research").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink creation unavailable on this Windows token.")
    with pytest.raises(ValueError, match="inside ignored"):
        probe._output(root.resolve(), "output/research/escape")
    assert not (outside / "escape").exists()


def test_initial_pin_drift_and_late_serialization_drift_publish_nothing(study, monkeypatch):
    args, plan, _, _ = study
    original = probe.Inputs.recheck
    calls = 0

    def changed(inputs):
        nonlocal calls
        calls += 1
        if calls == 2:
            (args.root / plan["roles"]["identity_pairs"]["path"]).write_bytes(b"late drift")
        return original(inputs)

    monkeypatch.setattr(probe.Inputs, "recheck", changed)
    with pytest.raises(ValueError, match="Frozen input changed"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


def test_recheck_reads_at_most_declared_size_plus_one(tmp_path, monkeypatch):
    data = b"tiny"
    pin = _pin("input.json", data)
    owner = probe.Inputs(tmp_path, [pin])
    observed = []

    class Growing(io.BytesIO):
        def read(self, size=-1):
            observed.append(size)
            assert size == len(data) + 1
            return b"x" * size

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: Growing())
    with pytest.raises(ValueError, match="Frozen input changed"):
        owner.recheck()
    assert observed == [5]


@pytest.mark.parametrize("payload", [b'{"x":1,"x":2}', b'{"x":NaN}', b"[]"])
def test_json_metadata_rejects_duplicate_nonfinite_or_nonobject(payload):
    with pytest.raises(ValueError):
        probe._json(payload)
