"""K1 closure reuse, explicit P04 joins, unfilled failures and metadata-only boundaries."""

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
data = importlib.import_module("preprocessing.feature_join")


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


legacy = module("_join_k1_fixtures", "test_age_features.py")
p04 = module("_join_p04_fixtures", "test_split_freeze.py")
OUTPUT = "output/research/joined-v1"


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


def make_case(root, *, all_ok=False, select=None, change=None):
    study = legacy.study.__wrapped__()
    fits = study[0]["fit_records"]
    for i, fit in enumerate(fits):
        if fit["status"] == "ok":
            fit["shape"] = [i * 1000 + j for j in range(40)]
            fit["expr"] = [-i * 100 - j for j in range(10)]
    if all_ok:
        old = fits[1]
        replacement = {
            **copy.deepcopy(fits[0]),
            **old,
            "status": "ok",
            "error_code": None,
            "shape": [1000 + j for j in range(40)],
            "expr": [-100 - j for j in range(10)],
        }
        replacement.pop("failure_stage", None)
        replacement["fit_artifact"] = legacy.pin("output/old/restored.npz")
        fits[1] = replacement
        study[0]["summary"]["fit_statuses"] = {"ok": 4}
    source = data.k1.build_feature_dataset(*study)
    report_pin = legacy.persist(root, study)
    selected = list(range(4)) if select is None else select
    with p04.fixtures.raster() as image:
        raw = p04.fixtures.encoded(image)
    case = p04.make_case(root, bodies=[raw] * len(selected))

    def mutate(packet):
        for row, source_index in zip(packet["records"], selected, strict=True):
            row["use"] = data.k1.GROUP
            if source_index is not None:
                fit = source["records"][source_index]
                row.update(
                    file=copy.deepcopy(fit["original_image"]),
                    subject_id=fit["subject_id"],
                    age={k: fit["research_age"][k] for k in ("kind", "value", "lower", "upper")},
                    age_source="filename_research",
                )
        if change is not None:
            change(packet)

    p04.update_k5_and_screening(case, mutate)
    for assignment, row in zip(
        case["plan"]["assignments"], case["prepared"]["records"], strict=True
    ):
        assignment["use"] = row["use"]
    frozen = p04.run(case)
    assert frozen["status"] == "consistent"
    case["p04_report"] = frozen
    case["k1"] = source
    case["source_study"] = study
    case["feature_plan"] = {
        "schema_id": data.SCHEMA,
        "plan_id": "synthetic-join-v1",
        "precheck_report": pin(root, root / frozen["receipt"]),
        "frozen_inputs": frozen["frozen_inputs"],
        "feature_report": report_pin,
        "expected_binding": copy.deepcopy(source["binding"]),
        "mappings": [
            {
                "sample_id": row["sample_id"],
                "feature_sample_id": None if i is None else source["records"][i]["sample_id"],
            }
            for row, i in zip(case["prepared"]["records"], selected, strict=True)
        ],
        "reserve_bytes": 0,
    }
    return case


def freeze(case):
    path = case["root"] / "output/research/input/feature-join-plan.json"
    save(path, case["feature_plan"])
    return path.relative_to(case["root"]).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def run(case, output=OUTPUT):
    name, digest = freeze(case)
    return data.join(case["root"], name, digest, output)


def edit_fit_report(case, mutate):
    path = case["root"] / case["feature_plan"]["feature_report"]["path"]
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    save(path, value)
    case["feature_plan"]["feature_report"] = pin(case["root"], path)


@pytest.fixture(autouse=True)
def clean_readonly(tmp_path):
    yield
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_saved_failure_and_history_are_preserved_without_zero_filling(tmp_path):
    case = make_case(tmp_path)
    report = run(case)
    assert report["status"] == "failed" and report["inputs_stable"]
    assert (
        report["summary"]["requested"] == 4
        and report["summary"]["joined"] == 3
        and report["summary"]["failed"] == 1
    )
    assert report["source_summary"] == case["k1"]["summary"]
    assert report["unmapped_source_records"] == []
    assert [r["k5"] for r in report["records"]] == case["prepared"]["records"]
    assert report["records"][0]["k5"]["processing"]["reason"] == "historical:NO_FACE"
    failed = report["records"][1]
    assert failed["error_code"] == "SOURCE_FIT_FAILED" and failed["source_error_code"] == "NO_FACE"
    assert (
        failed["feature_row_index"] is None
        and failed["source_record"]["failure_stage"] == "detection"
    )
    assert report["features"] == case["k1"]["features"]
    assert report["binding"] == case["k1"]["binding"]
    assert all(report[k] is False for k in data.FLAGS)
    assert report["metadata_audit"] == data.metadata.audit_manifest(case["prepared"])


def test_all_successful_synthetic_fits_produce_passed_but_closed_packet(tmp_path):
    case = make_case(tmp_path, all_ok=True)
    report = run(case)
    assert report["status"] == "passed" and report["summary"]["joined"] == 4
    assert report["features"]["record_indices"] == [0, 1, 2, 3]
    assert all(report[k] is False for k in data.FLAGS)
    assert sorted(p.name for p in (tmp_path / OUTPUT).iterdir()) == ["report.json"]


def test_permuted_mapping_keeps_k5_order_and_exact_source_coefficients(tmp_path):
    case = make_case(tmp_path, select=[3, 2, 1, 0])
    report = run(case)
    assert report["features"]["record_indices"] == [0, 1, 3]
    assert report["features"]["shape"] == [[i * 1000 + j for j in range(40)] for i in [3, 2, 0]]
    assert [r["k1_record_index"] for r in report["records"]] == [3, 2, 1, 0]
    assert report["records"][2]["source_error_code"] == "NO_FACE"


def test_subset_does_not_erase_the_full_k1_failure_denominator(tmp_path):
    case = make_case(tmp_path, select=[0, 3])
    report = run(case)
    assert report["status"] == "passed" and report["summary"]["requested"] == 2
    assert report["source_summary"]["requested"] == 4 and report["source_summary"]["failed"] == 1
    assert len(report["unmapped_source_records"]) == 2
    assert any(r["error_code"] == "NO_FACE" for r in report["unmapped_source_records"])


def test_unknown_interval_and_absent_mapping_stay_explicit(tmp_path):
    def change(packet):
        packet["records"][-1].update(
            age=data.metadata.age_label("interval", lower=30, upper=40),
            age_source="dataset_annotation",
        )

    case = make_case(tmp_path, select=[0, None, None], change=change)
    report = run(case)
    assert [r["error_code"] for r in report["records"]] == [
        None,
        "NO_SAVED_FEATURE_MAPPING",
        "NO_SAVED_FEATURE_MAPPING",
    ]
    assert report["records"][1]["k5"]["age"] == data.metadata.age_label("unknown")
    assert report["records"][2]["k5"]["age"]["kind"] == "interval"
    assert report["features"]["record_indices"] == [0]


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("file", "ORIGINAL_IMAGE_DECLARATION_MISMATCH"),
        ("subject", "SUBJECT_DECLARATION_MISMATCH"),
        ("age", "AGE_DECLARATION_MISMATCH"),
        ("interval", "AGE_DECLARATION_MISMATCH"),
        ("derived", "ORIGINAL_PHOTO_REQUIRED"),
    ],
)
def test_each_declared_source_mismatch_is_a_retained_row_failure(tmp_path, kind, expected):
    def change(packet):
        row = packet["records"][0]
        if kind == "file":
            row["file"]["sha256"] = "d" * 64
        elif kind == "subject":
            row["subject_id"] = None
        elif kind == "age":
            row.update(age=data.metadata.age_label("unknown"), age_source="unknown")
        elif kind == "interval":
            row.update(
                age=data.metadata.age_label("interval", lower=20, upper=30),
                age_source="dataset_annotation",
            )
        else:
            row.update(kind="crop", parent_id=packet["records"][2]["sample_id"])

    report = run(make_case(tmp_path, change=change))
    assert report["records"][0]["error_code"] == expected
    assert len(report["records"]) == 4 and report["summary"]["failed"] == 2


def test_calibration_features_cannot_be_relabelled_as_development(tmp_path):
    def change(packet):
        for row in packet["records"]:
            row["use"] = "development"

    report = run(make_case(tmp_path, change=change))
    assert report["summary"]["joined"] == 0
    assert all(r["error_code"] == "SOURCE_USE_MISMATCH" for r in report["records"])
    assert report["features"] == dict.fromkeys(
        ["record_indices", "shape", "expression", "projection"], []
    )


def test_no_image_npz_weights_or_inference_are_needed(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    original_open = Path.open

    def guard(path, *args, **kwargs):
        assert path.suffix.lower() not in {".png", ".jpg", ".npz", ".npy", ".onnx", ".pth"}
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    assert run(case)["summary"]["joined"] == 3


@pytest.mark.parametrize("kind", ["omit", "order", "unknown", "reuse", "extra"])
def test_mapping_contract_is_complete_and_explicit(tmp_path, kind):
    case = make_case(tmp_path)
    items = case["feature_plan"]["mappings"]
    if kind == "omit":
        items.pop()
    elif kind == "order":
        items.reverse()
    elif kind == "unknown":
        items[0]["feature_sample_id"] = "not-in-k1"
    elif kind == "reuse":
        items[1]["feature_sample_id"] = items[0]["feature_sample_id"]
    else:
        items[0]["guess_age"] = 45
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("kind", ["topology", "basis", "dimensions", "standardized"])
def test_expected_binding_is_pinned_before_any_join(tmp_path, kind):
    case = make_case(tmp_path)
    binding = case["feature_plan"]["expected_binding"]
    if kind == "topology":
        binding["topology_sha256"] = "b" * 64
    elif kind == "basis":
        binding["models"]["reconstructor"]["artifacts"]["bfm"]["sha256"] = "b" * 64
    elif kind == "dimensions":
        binding["shape_dimensions"] = 39
    else:
        binding["standardized"] = True
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        run(case)


@pytest.mark.parametrize(
    "kind", ["nan", "bool", "short", "projection", "topology", "purpose", "omitted_fit"]
)
def test_existing_k1_validation_rejects_bad_saved_fits(tmp_path, kind):
    case = make_case(tmp_path)

    def mutate(report):
        fit = report["fit_records"][0]
        if kind == "nan":
            fit["shape"][0] = float("nan")
        elif kind == "bool":
            fit["shape"][0] = True
        elif kind == "short":
            fit["shape"].pop()
        elif kind == "projection":
            fit["projection_semantics"] = "copied from another image"
        elif kind == "topology":
            fit["topology_sha256"] = "b" * 64
        elif kind == "purpose":
            fit["data_group"] = "evaluation_research_holdout"
        else:
            report["fit_records"].pop()

    edit_fit_report(case, mutate)
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize(
    "kind",
    [
        "packet_flag",
        "packet_assignment",
        "report_flag",
        "report_rows",
        "report_version",
        "report_summary",
    ],
)
def test_repinned_p04_artifacts_must_match_full_replay(tmp_path, kind):
    case = make_case(tmp_path)
    role = "frozen_inputs" if kind.startswith("packet") else "precheck_report"
    path = tmp_path / case["feature_plan"][role]["path"]
    value = json.loads(path.read_text(encoding="utf-8"))
    if kind == "packet_flag":
        value["freeze_authorized"] = True
    elif kind == "packet_assignment":
        value["assignments"][0]["use"] = "test"
    elif kind == "report_flag":
        value["human_review_verified"] = True
    elif kind == "report_rows":
        value["records"].pop()
    elif kind == "report_version":
        value["producer_sha256"] = "0" * 64
    else:
        value["summary"]["candidate_reviews"] = 0
    save(path, value)
    case["feature_plan"][role] = pin(tmp_path, path)
    if role == "frozen_inputs":
        p = tmp_path / case["feature_plan"]["precheck_report"]["path"]
        report = json.loads(p.read_text(encoding="utf-8"))
        report["frozen_inputs"] = case["feature_plan"]["frozen_inputs"]
        save(p, report)
        case["feature_plan"]["precheck_report"] = pin(tmp_path, p)
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("role", ["feature_report", "precheck_report", "frozen_inputs"])
def test_initial_metadata_pin_drift_rejects(tmp_path, role):
    case = make_case(tmp_path)
    path = tmp_path / case["feature_plan"][role]["path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="INPUT_PIN_MISMATCH"):
        run(case)


@pytest.mark.parametrize("role", ["feature_report", "precheck_report", "frozen_inputs", "plan"])
def test_late_drift_invalidates_all_exported_feature_rows(tmp_path, monkeypatch, role):
    case = make_case(tmp_path)
    original = data._join_rows

    def changed(*args):
        result = original(*args)
        path = tmp_path / (
            "output/research/input/feature-join-plan.json"
            if role == "plan"
            else case["feature_plan"][role]["path"]
        )
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(data, "_join_rows", changed)
    report = run(case)
    assert not report["inputs_stable"] and report["status"] == "failed"
    assert report["summary"]["feature_rows_before_final_check"] == 3
    assert report["summary"]["failed"] == 4 and all(not v for v in report["features"].values())
    assert all(
        r["feature_row_index"] is None and r["error_code"] == "INPUT_CHANGED_AT_FINAL_CHECK"
        for r in report["records"]
    )
    assert report["records"][1]["previous_error_code"] == "SOURCE_FIT_FAILED"
    assert report["records"][1]["source_error_code"] == "NO_FACE"


def test_budget_scope_and_old_output_preserved(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    with pytest.raises(ValueError):
        run(case, "data/joined")
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
    "all_ok,wrong_hash,expected", [(True, False, 0), (False, False, 1), (True, True, 2)]
)
def test_cli_success_saved_failure_and_rejection(tmp_path, all_ok, wrong_hash, expected):
    case = make_case(tmp_path, all_ok=all_ok)
    name, digest = freeze(case)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "preprocessing.feature_join",
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
    assert (tmp_path / OUTPUT / "report.json").exists() is (expected != 2)
