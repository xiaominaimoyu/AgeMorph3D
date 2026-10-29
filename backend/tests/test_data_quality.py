"""P06 precision-aware counts, full denominators, stable saved observations and null budgets."""

import copy
import hashlib
import importlib
import importlib.util
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
data = importlib.import_module("preprocessing.data_quality")


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


raw = module("_quality_k5_fixtures", "test_dataset_manifest.py")
features = module("_quality_p05_fixtures", "test_feature_join.py")
OUTPUT = "output/research/quality-v1"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def pin(root, path):
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def make_case(root, manifest=None, *, with_features=False, all_ok=False):
    if with_features:
        source_case = features.make_case(root, all_ok=all_ok)
        source_report = features.run(source_case)
        packet = source_case["prepared"]
        manifest_pin = source_case["plan"]["prepared_manifest"]
        feature_pin = pin(root, root / source_report["receipt"])
    else:
        source_case = source_report = None
        packet = raw.manifest.__wrapped__() if manifest is None else manifest
        path = root / "output/research/input/quality-manifest.json"
        save(path, packet)
        manifest_pin, feature_pin = pin(root, path), None
    return {
        "root": root,
        "manifest": packet,
        "source_case": source_case,
        "source_report": source_report,
        "plan": {
            "schema_id": data.SCHEMA,
            "plan_id": "synthetic-quality-v1",
            "manifest": manifest_pin,
            "feature_join_report": feature_pin,
            "reserve_bytes": 0,
        },
    }


def freeze(case):
    path = case["root"] / "output/research/input/quality-plan.json"
    save(path, case["plan"])
    return path.relative_to(case["root"]).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def run(case, output=OUTPUT):
    name, digest = freeze(case)
    return data.export_report(case["root"], name, digest, output)


@pytest.fixture(autouse=True)
def clean_readonly(tmp_path):
    yield
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_manifest_only_counts_are_declarations_and_feature_observation_is_unknown(tmp_path):
    case = make_case(tmp_path)
    report = run(case)
    s = report["statistics"]
    assert report["status"] == "reported" and report["input_mode"] == "manifest_only"
    assert s["records"] == 3 and s["identity_declarations"]["local_subjects"] == 3
    assert s["formal_split_records"] == {"train": 1, "validation": 1, "test": 1}
    assert s["saved_features"] is None
    assert s["age"]["kinds"] == {"exact": 3, "interval": 0, "unknown": 0}
    assert s["age"]["exact_bins_20_70"]["30-39"] == 3
    assert s["historical_processing"] == {"not_checked": 0, "ok": 3, "failed": 0, "excluded": 0}
    assert all(v is None for v in s["unmeasured"].values())
    assert all(report[k] is False for k in data.FLAGS)
    assert [r["k5"] for r in report["records"]] == case["manifest"]["records"]
    assert all(r["join_status"] is r["join_error_code"] is None for r in report["records"])
    assert report["metadata_files_verified"] == 2
    assert report["metadata_bytes_verified"] == sum(p["bytes"] for p in report["inputs"])
    assert sorted(p.name for p in (tmp_path / OUTPUT).iterdir()) == ["report.json", "report.md"]
    assert "未提供" in (tmp_path / report["markdown"]).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "age,bin_name,scope",
    [
        (0, None, "outside"),
        (19.999, None, "outside"),
        (20, "20-29", "inside"),
        (29.999, "20-29", "inside"),
        (30, "30-39", "inside"),
        (69.999, "60-69", "inside"),
        (70, "70", "inside"),
        (70.001, None, "outside"),
        (120, None, "outside"),
    ],
)
def test_exact_age_edges_are_not_clamped_or_dropped(age, bin_name, scope):
    manifest = raw.manifest.__wrapped__()
    manifest["records"] = manifest["records"][:1]
    manifest["records"][0]["age"] = data.metadata.age_label("exact", age)
    result = data.summarize(manifest)
    s = result["statistics"]
    assert s["age"]["exact_label_min"] == s["age"]["exact_label_max"] == age
    assert s["age"]["scope_by_kind"]["exact"] == {scope: 1}
    assert sum(s["age"]["exact_bins_20_70"].values()) == (1 if bin_name else 0)
    if bin_name:
        assert s["age"]["exact_bins_20_70"][bin_name] == 1
    assert result["records"][0]["k5"]["age"]["value"] == age


@pytest.mark.parametrize(
    "lower,upper,scope",
    [
        (20, 70, "inside"),
        (19, 30, "outside_or_crossing"),
        (70, 71, "outside_or_crossing"),
        (0, 120, "outside_or_crossing"),
    ],
)
def test_intervals_remain_intervals_without_midpoint_bins(lower, upper, scope):
    manifest = raw.manifest.__wrapped__()
    for row in manifest["records"]:
        row["age"] = data.metadata.age_label("interval", lower=lower, upper=upper)
    result = data.summarize(manifest)
    s = result["statistics"]
    assert s["age"]["kinds"] == {"exact": 0, "interval": 3, "unknown": 0}
    assert s["age"]["scope_by_kind"]["interval"] == {scope: 3}
    assert sum(s["age"]["exact_bins_20_70"].values()) == 0
    assert s["age"]["exact_label_min"] is s["age"]["exact_label_max"] is None
    assert all(r["k5"]["age"]["value"] is None for r in result["records"])


def test_unknown_ages_are_not_inferred_from_filenames_or_uses():
    manifest = raw.manifest.__wrapped__()
    for row in manifest["records"]:
        row.update(age=data.metadata.age_label("unknown"), age_source="unknown")
    s = data.summarize(manifest)["statistics"]
    assert s["age"]["kinds"]["unknown"] == 3
    assert s["age"]["scope_by_kind"]["unknown"] == {"unknown": 3}
    assert sum(s["age"]["exact_bins_20_70"].values()) == 0


def test_history_exclusion_and_unknown_exposure_are_separate_from_actual_quality():
    manifest = raw.manifest.__wrapped__()
    rows = manifest["records"]
    rows[0]["processing"] = {"status": "failed", "reason": "historical:NO_FACE"}
    rows[1]["processing"] = {"status": "excluded", "reason": "declared-only"}
    rows[2]["processing"] = {"status": "not_checked", "reason": None}
    rows[0]["exposure"]["model_selection"] = "unknown"
    rows[1]["exposure"]["model_selection"] = "yes"
    s = data.summarize(manifest)["statistics"]
    assert s["historical_processing"] == {"not_checked": 1, "ok": 0, "failed": 1, "excluded": 1}
    assert s["historical_failure_reasons"] == {"historical:NO_FACE": 1}
    assert s["declared_exclusion_ratio"] == {"numerator": 1, "denominator": 3, "value": 1 / 3}
    assert s["unmeasured"]["actual_quality_exclusion_rate"] is None
    assert s["exposure_declarations"]["model_selection"] == {"yes": 1, "no": 1, "unknown": 1}


def test_identity_namespaces_and_linked_ids_are_not_added_as_verified_people():
    manifest = raw.manifest.__wrapped__()
    manifest["datasets"].append({**copy.deepcopy(manifest["datasets"][0]), "dataset_id": "d2"})
    for row in manifest["records"]:
        row["subject_id"] = "same-text-id"
    manifest["records"][2]["dataset_id"] = "d2"
    manifest["records"][0]["linked_subject_id"] = manifest["records"][2]["linked_subject_id"] = (
        "explicit-link"
    )
    s = data.summarize(manifest)["statistics"]
    assert s["identity_declarations"] == {
        "local_subjects": 2,
        "explicit_linked_subject_ids": 1,
        "unknown_subject_records": 0,
    }
    assert "IDENTITY_OR_LINEAGE_CROSSES_USES" in s["finding_counts"]
    assert all(d["evidence_integrity_rechecked"] is False for d in s["dataset_registrations"])


def test_missing_review_materials_and_full_audit_survive():
    manifest = raw.manifest.__wrapped__()
    dataset = manifest["datasets"][0]
    for name, status in [
        ("purpose_registration", "unresolved"),
        ("identity_review", "pending"),
        ("near_duplicate_review", "pending"),
        ("training_overlap", "unknown"),
    ]:
        dataset[name] = {"status": status, "evidence": None}
    result = data.summarize(manifest)
    assert result["metadata_audit"] == data.metadata.audit_manifest(manifest)
    assert {
        "USE_REGISTRATION_UNRESOLVED",
        "IDENTITY_REVIEW_PENDING",
        "NEAR_DUPLICATE_REVIEW_PENDING",
        "TRAINING_OVERLAP_UNRESOLVED",
    } <= set(result["statistics"]["finding_counts"])
    result["records"][0]["k5"]["age"]["value"] = 99
    assert manifest["records"][0]["age"]["value"] == 31


def test_zero_denominator_is_unknown_and_large_cohort_is_bounded(monkeypatch):
    assert data._ratio(0, 0) == {"numerator": 0, "denominator": 0, "value": None}
    monkeypatch.setattr(data, "MAX_RECORDS", 2)
    with pytest.raises(ValueError, match="RECORD_COUNT_LIMIT"):
        data.summarize(raw.manifest.__wrapped__())


def test_saved_failure_is_reported_as_coverage_not_a_failed_report(tmp_path):
    case = make_case(tmp_path, with_features=True)
    report = run(case)
    s = report["statistics"]["saved_features"]
    assert report["status"] == "reported" and report["input_mode"] == "saved_feature_join"
    assert s["join_coverage"] == {"numerator": 3, "denominator": 4, "value": 0.75}
    assert s["join_failure_codes"] == {"SOURCE_FIT_FAILED": 1}
    assert s["mapped_source_error_codes"] == {"NO_FACE": 1}
    assert s["source_summary"]["requested"] == 4 and s["source_summary"]["failed"] == 1
    assert report["records"][1]["join_error_code"] == "SOURCE_FIT_FAILED"
    assert report["records"][1]["source_error_code"] == "NO_FACE"
    assert all(report[k] is False for k in data.FLAGS)


def test_successful_join_does_not_erase_historical_no_face(tmp_path):
    report = run(make_case(tmp_path, with_features=True, all_ok=True))
    assert report["statistics"]["saved_features"]["failed"] == 0
    assert report["statistics"]["historical_processing"]["failed"] == 1
    assert report["statistics"]["historical_failure_reasons"] == {"historical:NO_FACE": 1}


@pytest.mark.parametrize(
    "field",
    ["records", "features", "summary", "source_summary", "flag", "version", "unstable", "inputs"],
)
def test_repinned_p05_report_requires_exact_full_replay(tmp_path, field):
    case = make_case(tmp_path, with_features=True)
    path = tmp_path / case["plan"]["feature_join_report"]["path"]
    value = json.loads(path.read_text(encoding="utf-8"))
    if field == "records":
        value["records"].pop()
    elif field == "features":
        value["features"]["shape"][0][0] += 1
    elif field == "summary":
        value["summary"]["failed"] = 0
    elif field == "source_summary":
        value["source_summary"]["failed"] = 0
    elif field == "flag":
        value["statistics_fitted"] = True
    elif field == "version":
        value["producer_sha256"] = "0" * 64
    elif field == "unstable":
        value["inputs_stable"] = False
    else:
        value["inputs"].pop()
    save(path, value)
    case["plan"]["feature_join_report"] = pin(tmp_path, path)
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_distinct_manifest_snapshot_cannot_be_pooled_with_saved_join(tmp_path):
    case = make_case(tmp_path, with_features=True)
    path = tmp_path / "output/research/input/copied-manifest.json"
    save(path, case["manifest"])
    case["plan"]["manifest"] = pin(tmp_path, path)
    with pytest.raises(ValueError, match="P05_COHORT_MISMATCH"):
        run(case)


def test_metadata_only_reads_even_when_every_image_and_binary_is_forbidden(tmp_path, monkeypatch):
    case = make_case(tmp_path, with_features=True)
    original = Path.open

    def guard(path, *args, **kwargs):
        assert path.suffix.lower() not in {".png", ".jpg", ".npz", ".npy", ".onnx", ".pth"}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    assert run(case)["status"] == "reported"


@pytest.mark.parametrize("field", ["manifest", "feature_join_report"])
def test_initial_pin_drift_rejects_before_writes(tmp_path, field):
    case = make_case(tmp_path, with_features=True)
    path = tmp_path / case["plan"][field]["path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="INPUT_PIN_MISMATCH"):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("field", ["manifest", "feature_join_report", "plan"])
def test_late_drift_withholds_all_statistics_but_retains_rows(tmp_path, monkeypatch, field):
    case = make_case(tmp_path, with_features=True)
    original = data.summarize

    def changed(*args):
        result = original(*args)
        name = (
            "output/research/input/quality-plan.json"
            if field == "plan"
            else case["plan"][field]["path"]
        )
        path = tmp_path / name
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(data, "summarize", changed)
    report = run(case)
    assert report["status"] == "invalidated" and not report["inputs_stable"]
    assert report["statistics"] is report["metadata_audit"] is None
    assert report["snapshot_record_count"] == len(report["records"]) == 4
    text = (tmp_path / report["markdown"]).read_text(encoding="utf-8")
    assert "统计结果未发布" in text and "| 用途 |" not in text


def test_markdown_escapes_untrusted_versions_and_has_null_measurements(tmp_path):
    manifest = raw.manifest.__wrapped__()
    manifest["datasets"][0]["version"] = "v1 | [click](bad) <script>\nnext"
    report = run(make_case(tmp_path, manifest))
    text = (tmp_path / report["markdown"]).read_text(encoding="utf-8")
    assert "[click](bad)" not in text and "<script>" not in text
    assert "\\|" in text and "&lt;script&gt;" in text and "未测/未核" in text


def test_output_scope_disk_budget_and_existing_evidence(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    with pytest.raises(ValueError):
        run(case, "data/quality")
    report = run(case)
    saved = (tmp_path / report["receipt"]).read_bytes()
    with pytest.raises(ValueError, match="OUTPUT_MUST_BE_NEW"):
        run(case)
    assert (tmp_path / report["receipt"]).read_bytes() == saved
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(data.shutil, "disk_usage", lambda _: usage._replace(free=0))
    with pytest.raises(ValueError, match="INSUFFICIENT_SPACE"):
        run(case, OUTPUT + "-new")


@pytest.mark.parametrize(
    "field,value", [("fit_train_statistics", True), ("reserve_bytes", True), ("schema_id", "wrong")]
)
def test_no_training_or_extra_plan_switches(tmp_path, field, value):
    case = make_case(tmp_path)
    case["plan"][field] = value
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_main_returns_one_for_late_invalidated_input(tmp_path, monkeypatch, capsys):
    case = make_case(tmp_path)
    name, digest = freeze(case)
    original = data.summarize

    def changed(*args):
        result = original(*args)
        path = tmp_path / case["plan"]["manifest"]["path"]
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(data, "summarize", changed)
    assert (
        data.main(
            [
                "--root",
                str(tmp_path),
                "--plan",
                name,
                "--plan-sha256",
                digest,
                "--output-dir",
                OUTPUT,
            ]
        )
        == 1
    )
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "invalidated" and response["statistics"] is None


@pytest.mark.parametrize("wrong_hash,expected", [(False, 0), (True, 2)])
def test_cli_reported_and_rejected(tmp_path, wrong_hash, expected):
    case = make_case(tmp_path)
    name, digest = freeze(case)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "preprocessing.data_quality",
            "--root",
            str(tmp_path),
            "--plan",
            name,
            "--plan-sha256",
            "0" * 64 if wrong_hash else digest,
            "--output-dir",
            OUTPUT,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected and not result.stderr
    response = json.loads(result.stdout)
    assert all(response[k] is False for k in data.FLAGS)
    assert (tmp_path / OUTPUT / "report.md").exists() is (expected == 0)
