"""Entry scope, declaration boundaries, retained failures and metadata-only CLI."""

import copy
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
data = importlib.import_module("training.preflight")
spec = importlib.util.spec_from_file_location(
    "_t01_quality_fixtures", Path(__file__).with_name("test_data_quality.py")
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
save, pin = fixtures.save, fixtures.pin
OUTPUT = "output/research/t01-v1"


def make_case(root, *, features=False, all_ok=False):
    source = fixtures.make_case(root, with_features=features, all_ok=all_ok)
    draft = json.loads((ROOT / "training/baseline-draft-v1.json").read_text("utf-8"))
    for model in draft["models"]:
        path = root / model["manifest"]["path"]
        save(
            path,
            {
                "schema_version": 1,
                "model_id": model["model_id"],
                "revision": model["revision"],
                "license_status": "unresolved",
            },
        )
        model["manifest"] = pin(root, path)
    for item in draft["environment"]["dependency_files"]:
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic dependency text\n", encoding="utf-8")
        item.update(pin(root, path))
    path = root / "docs/t01-protocol.json"
    protocol = json.loads((ROOT / "docs/experiment-protocol-v1.json").read_text("utf-8"))
    save(path, protocol)
    draft["protocol"] = pin(root, path)
    case = {
        "root": root,
        "source": source,
        "draft": draft,
        "plan": {
            "schema_id": data.SCHEMA,
            "plan_id": "synthetic-t01-v1",
            "draft": None,
            "manifest": source["plan"]["manifest"],
            "freeze": None,
            "feature_join_report": source["plan"]["feature_join_report"],
            "reviews": [],
            "reserve_bytes": 0,
        },
    }
    if features:
        feature_plan = source["source_case"]["feature_plan"]
        case["plan"]["freeze"] = {
            "report": feature_plan["precheck_report"],
            "packet": feature_plan["frozen_inputs"],
        }
    persist(case)
    return case


def persist(case):
    path = case["root"] / "output/research/input/draft.json"
    save(path, case["draft"])
    case["plan"]["draft"] = pin(case["root"], path)
    path = case["root"] / "output/research/input/t01-plan.json"
    save(path, case["plan"])
    return pin(case["root"], path)


def run(case, output=OUTPUT):
    p = persist(case)
    return data.precheck(case["root"], p["path"], p["sha256"], output)


def review(case, gate, *, origin="human", state="recorded", evidence=True):
    root = case["root"]
    evidence_path = root / "output/research/input/review-note.md"
    evidence_path.write_text("Synthetic review evidence; no real approval.\n", encoding="utf-8")
    v = {
        "schema_id": data.REVIEW_SCHEMA,
        "gate_id": gate,
        "state": state,
        "origin": origin,
        "reviewer": "reviewer-b",
        "scope": {
            "draft": case["plan"]["draft"],
            "manifest": case["plan"]["manifest"],
            "protocol": case["draft"]["protocol"],
            "freeze": case["plan"]["freeze"],
            "feature_join_report": case["plan"]["feature_join_report"],
        },
        "evidence": pin(root, evidence_path) if evidence else None,
    }
    path = root / f"output/research/input/review-{gate}.json"
    save(path, v)
    p = pin(root, path)
    case["plan"]["reviews"].append(p)
    return path, v


def codes(report):
    return {r["code"] for r in report["blockers"]}


def test_current_draft_is_versioned_and_fixed():
    v = json.loads((ROOT / "training/baseline-draft-v1.json").read_text("utf-8"))
    assert data.validate_draft(v) == v
    assert v["seed"] == 20261030
    assert [c["id"] for c in v["candidates"]] == [
        "detector_pretrained",
        "reconstruction_pretrained",
        "age_no_change",
        "age_ridge",
    ]


def test_missing_materials_report_complete_research_records(tmp_path):
    case = make_case(tmp_path)
    path = tmp_path / case["plan"]["manifest"]["path"]
    manifest = case["source"]["manifest"]
    for row in manifest["records"]:
        row["use"] = "development"
    save(path, manifest)
    case["plan"]["manifest"] = pin(tmp_path, path)
    r = run(case)
    assert r["status"] == "blocked" and r["inputs_stable"]
    assert len(r["entry_reviews"]) == 9
    assert {v["gate_id"] for v in r["entry_reviews"]} == set(data.GATES)
    assert all(r[k] is False for k in data.FLAGS)
    assert [row["k5"] for row in r["records"]] == case["source"]["manifest"]["records"]
    assert r["statistics"]["unmeasured"]["formal_training_budget_hours"] is None
    assert "P04_INPUTS_MISSING" in codes(r) and "P05_SAVED_FEATURES_MISSING" in codes(r)
    assert "g3" not in " ".join(v["item"] for v in r["blockers"]).lower()
    assert len([b for b in r["blockers"] if b["code"] == "FORMAL_SPLIT_EMPTY"]) == 3


def test_unknown_and_interval_ages_remain_without_imputation(tmp_path):
    case = make_case(tmp_path)
    path = tmp_path / case["plan"]["manifest"]["path"]
    manifest = case["source"]["manifest"]
    manifest["records"][1]["age"] = data.metadata.age_label("interval", lower=30, upper=40)
    manifest["records"][2]["age"] = data.metadata.age_label("unknown")
    save(path, manifest)
    case["plan"]["manifest"] = pin(tmp_path, path)
    r = run(case)
    assert r["statistics"]["age"]["kinds"] == {"exact": 1, "interval": 1, "unknown": 1}
    assert r["records"][2]["k5"]["age"]["value"] is None


@pytest.mark.parametrize("all_ok,failed", [(True, 0), (False, 1)])
def test_saved_pipeline_replay_retains_source_denominator_and_synthetic_basis(
    tmp_path, all_ok, failed
):
    case = make_case(tmp_path, features=True, all_ok=all_ok)
    r = run(case)
    s = r["statistics"]["saved_features"]
    assert (s["requested"], s["joined"], s["failed"]) == (4, 4 - failed, failed)
    assert s["source_summary"]["requested"] == 4
    assert s["source_summary"]["failed"] == failed
    assert "P04_NONHUMAN_GROUP_BASIS" in codes(r)
    assert ("P05_SAVED_FEATURE_FAILURES" in codes(r)) == bool(failed)
    assert "P04_INPUTS_MISSING" not in codes(r)
    assert "P05_SAVED_FEATURES_MISSING" not in codes(r)
    assert r["training_authorized"] is False


@pytest.mark.parametrize(
    "origin,state,evidence,expected",
    [
        ("human", "recorded", True, "recorded_declaration"),
        ("official", "recorded", True, "recorded_declaration"),
        ("synthetic", "recorded", True, "blocked"),
        ("ai", "recorded", True, "blocked"),
        ("unknown", "recorded", True, "blocked"),
        ("human", "pending", True, "blocked"),
        ("human", "recorded", False, "blocked"),
    ],
)
def test_review_origin_is_self_reported_and_not_training_authority(
    tmp_path, origin, state, evidence, expected
):
    case = make_case(tmp_path)
    review(case, "R13", origin=origin, state=state, evidence=evidence)
    r = run(case)
    assert r["entry_reviews"][4]["status"] == expected
    assert r["training_authorized"] is r["review_authenticity_verified"] is False


@pytest.mark.parametrize("mutation", ["scope", "gate", "duplicate", "evidence_drift"])
def test_review_tampering_and_duplicate_gate_rejected_before_publication(tmp_path, mutation):
    case = make_case(tmp_path)
    path, v = review(case, "R11")
    if mutation == "scope":
        v["scope"]["draft"]["sha256"] = "0" * 64
    elif mutation == "gate":
        v["gate_id"] = "G3"
    elif mutation == "duplicate":
        case["plan"]["reviews"].append(copy.deepcopy(case["plan"]["reviews"][0]))
    else:
        (tmp_path / v["evidence"]["path"]).write_text("changed", encoding="utf-8")
    save(path, v)
    case["plan"]["reviews"][0] = pin(tmp_path, path)
    with pytest.raises(data.Error):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", True),
        ("seed", -1),
        ("seed", 2**32),
        ("status", "ready"),
        ("purpose", "commercial"),
        ("candidates", []),
        ("models", []),
        ("policy", {"test_scores_read": True}),
        ("measured_budget", {"hours": 0, "peak_gpu_bytes": None, "storage_bytes": None}),
    ],
)
def test_invalid_draft_rejected(tmp_path, field, value):
    case = make_case(tmp_path)
    case["draft"][field] = value
    with pytest.raises(data.Error):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("kind", ["model", "protocol", "dependency", "binary_pin", "plan_hash"])
def test_wrong_input_binding_rejected(tmp_path, kind):
    case = make_case(tmp_path)
    if kind == "model":
        case["draft"]["models"][0]["revision"] = "different"
    elif kind == "protocol":
        path = tmp_path / case["draft"]["protocol"]["path"]
        v = json.loads(path.read_text("utf-8"))
        v["production_enabled"] = True
        save(path, v)
        case["draft"]["protocol"] = pin(tmp_path, path)
    elif kind == "dependency":
        (tmp_path / "backend/uv.lock").write_text("different", encoding="utf-8")
    elif kind == "binary_pin":
        case["draft"]["models"][0]["manifest"]["path"] = "data/model.onnx"
    if kind == "plan_hash":
        p = persist(case)

        def action():
            return data.precheck(tmp_path, p["path"], "0" * 64, OUTPUT)
    else:

        def action():
            return run(case)

    with pytest.raises(data.Error):
        action()
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("kind", ["metadata", "source"])
def test_late_changes_withdraw_statistics_and_keep_complete_snapshot(tmp_path, monkeypatch, kind):
    case = make_case(tmp_path)
    original = data.assess

    def changed(inputs, plan):
        result = original(inputs, plan)
        if kind == "metadata":
            (tmp_path / "backend/uv.lock").write_text("late drift", encoding="utf-8")
        else:
            monkeypatch.setitem(data._SOURCES, "training/preflight.py", "0" * 64)
        return result

    monkeypatch.setattr(data, "assess", changed)
    r = run(case)
    assert r["status"] == "invalidated" and r["changed_inputs"]
    assert r["statistics"] is r["metadata_audit"] is None
    assert len(r["records"]) == 3 and "INPUT_OR_SOURCE_CHANGED" in codes(r)
    assert "末检变化" in (tmp_path / r["markdown"]).read_text("utf-8")


def test_output_never_overwrites_or_leaves_research_directory(tmp_path):
    case = make_case(tmp_path)
    run(case)
    saved = (tmp_path / OUTPUT / "report.json").read_bytes()
    with pytest.raises(data.Error, match="OUTPUT_MUST_BE_NEW"):
        run(case)
    with pytest.raises(data.Error, match="OUTPUT_MUST_BE_NEW"):
        run(case, "training/report")
    assert (tmp_path / OUTPUT / "report.json").read_bytes() == saved


def test_all_nine_recorded_reviews_cannot_bypass_missing_pipeline(tmp_path):
    case = make_case(tmp_path)
    for gate in data.GATES:
        review(case, gate)
    r = run(case)
    assert all(v["status"] == "recorded_declaration" for v in r["entry_reviews"])
    assert "ENTRY_REVIEW_MISSING_OR_PENDING" not in codes(r)
    assert r["status"] == "blocked" and r["training_authorized"] is False
    assert {
        "MODEL_PURPOSE_UNRESOLVED",
        "P04_INPUTS_MISSING",
        "P05_SAVED_FEATURES_MISSING",
        "SHORT_RUN_CONFIG_PENDING",
    } <= codes(r)


def test_p05_without_exact_p04_binding_rejected(tmp_path):
    case = make_case(tmp_path, features=True, all_ok=True)
    case["plan"]["freeze"] = None
    with pytest.raises(data.Error, match="P04_P05_FREEZE_BINDING_MISMATCH"):
        run(case)


def test_review_for_old_freeze_scope_cannot_be_reused(tmp_path):
    case = make_case(tmp_path, features=True, all_ok=True)
    path, v = review(case, "P04_human_freeze")
    v["scope"]["freeze"] = None
    save(path, v)
    case["plan"]["reviews"][0] = pin(tmp_path, path)
    with pytest.raises(data.Error, match="REVIEW_SCOPE_MISMATCH"):
        run(case)


def test_cli_blocked_and_rejected_exit_codes(tmp_path):
    case = make_case(tmp_path)
    p = persist(case)
    cmd = [
        sys.executable,
        "-m",
        "training.preflight",
        "--root",
        str(tmp_path),
        "--plan",
        p["path"],
        "--plan-sha256",
        p["sha256"],
        "--output-dir",
        OUTPUT,
    ]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 1 and json.loads(r.stdout)["status"] == "blocked"
    cmd[cmd.index("--plan-sha256") + 1] = "0" * 64
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 2 and json.loads(r.stdout)["error_code"] == "PLAN_SHA256_MISMATCH"
