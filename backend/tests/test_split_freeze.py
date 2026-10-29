"""Metadata-only freezes, complete P03 ledgers, explicit provenance and blocking constraints."""

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
data = importlib.import_module("preprocessing.split_freeze")
spec = importlib.util.spec_from_file_location(
    "_split_screening_fixtures", Path(__file__).with_name("test_duplicate_screening.py")
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
OUTPUT = "output/research/freeze-precheck-v1"


def make_case(root, *, failed=False, bodies=None):
    with fixtures.raster() as image:
        raw = fixtures.encoded(image)
    # Same-content images stay in one existing research use for a consistent fixture.
    case = fixtures.make_case(
        root, [raw, b"bad image" if failed else raw, raw] if bodies is None else bodies
    )
    path = root / fixtures.fixtures.OUTPUT / "prepared-manifest.json"
    original = json.loads(case["manifest_path"].read_text(encoding="utf-8"))
    for packet in (original, case["prepared"]):
        for row in packet["records"]:
            row["use"] = "development"
    fixtures.fixtures.save_json(case["manifest_path"], original)
    fixtures.fixtures.save_json(path, case["prepared"])
    case["source"]["inputs"]["metadata_manifest"] = fixtures.fixtures.pin(
        root, case["manifest_path"]
    )
    case["plan"]["prepared_manifest"] = fixtures.fixtures.pin(root, path)
    fixtures.change_report(case)
    screening = fixtures.run(case)
    case["screening"] = screening
    case["screen_plan"] = case["plan"]
    support = root / "output/research/input/grouping-evidence.md"
    support.write_text(
        "Synthetic fixture declarations only; no real identity or human sign-off.\n",
        encoding="utf-8",
    )
    evidence = fixtures.fixtures.pin(root, support)
    ids = [row["sample_id"] for row in case["prepared"]["records"]]
    case["basis"] = {
        "schema_id": data.BASIS_SCHEMA,
        "basis_id": "fixture-basis-v1",
        "groups": [
            {
                "group_id": "group-A",
                "sample_ids": ids,
                "origin": "synthetic",
                "recorded_by": "fixture-generator",
                "evidence": evidence,
            }
        ],
        "candidate_reviews": [
            {
                "candidate_id": c["candidate_id"],
                "sample_ids": c["sample_ids"],
                "decision": "same_content",
                "origin": "synthetic",
                "recorded_by": "fixture-generator",
                "evidence": evidence,
            }
            for c in screening["candidates"]
        ],
    }
    case["plan"] = {
        "schema_id": data.SCHEMA,
        "plan_id": "fixture-freeze-v1",
        "prepared_manifest": fixtures.fixtures.pin(root, path),
        "screening_report": fixtures.fixtures.pin(root, root / screening["receipt"]),
        "basis": None,
        "assignments": [
            {"sample_id": sid, "group_id": "group-A", "use": "development"} for sid in ids
        ],
        "reserve_bytes": 0,
    }
    return case


def freeze(case):
    path = case["root"] / "output/research/input/freeze-basis.json"
    fixtures.fixtures.save_json(path, case["basis"])
    case["plan"]["basis"] = fixtures.fixtures.pin(case["root"], path)
    plan = case["root"] / "output/research/input/freeze-plan.json"
    fixtures.fixtures.save_json(plan, case["plan"])
    return plan.relative_to(case["root"]).as_posix(), hashlib.sha256(plan.read_bytes()).hexdigest()


def run(case, output=OUTPUT):
    name, digest = freeze(case)
    return data.precheck(case["root"], name, digest, output)


def repin_screening(case):
    path = case["root"] / case["screening"]["receipt"]
    fixtures.fixtures.save_json(
        path, {k: v for k, v in case["screening"].items() if k != "receipt"}
    )
    case["plan"]["screening_report"] = fixtures.fixtures.pin(case["root"], path)


def update_k5_and_screening(case, mutate):
    # Keep original/prepared lineage coherent and re-screen the synthetic PNGs.
    mutate(case["prepared"])
    path = case["root"] / case["plan"]["prepared_manifest"]["path"]
    fixtures.fixtures.save_json(path, case["prepared"])
    new_pin = fixtures.fixtures.pin(case["root"], path)
    case["plan"]["prepared_manifest"] = new_pin
    original = json.loads(case["manifest_path"].read_text(encoding="utf-8"))
    mutate(original)
    fixtures.fixtures.save_json(case["manifest_path"], original)
    case["source"]["inputs"]["metadata_manifest"] = fixtures.fixtures.pin(
        case["root"], case["manifest_path"]
    )
    preparation_path = case["root"] / fixtures.fixtures.OUTPUT / "report.json"
    fixtures.fixtures.save_json(
        preparation_path, {k: v for k, v in case["source"].items() if k != "receipt"}
    )
    case["screen_plan"]["prepared_manifest"] = new_pin
    case["screen_plan"]["preparation_report"] = fixtures.fixtures.pin(
        case["root"], preparation_path
    )
    plan_path = case["root"] / "output/research/input/screen-plan-modified.json"
    fixtures.fixtures.save_json(plan_path, case["screen_plan"])
    result = data.screening.screen(
        case["root"],
        plan_path.relative_to(case["root"]).as_posix(),
        hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "output/research/screened-modified-v1",
    )
    case["screening"] = result
    case["plan"]["screening_report"] = fixtures.fixtures.pin(
        case["root"], case["root"] / result["receipt"]
    )


@pytest.fixture(autouse=True)
def clean_readonly(tmp_path):
    yield
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_consistent_packet_is_separate_and_never_authorizes_actual_freeze(tmp_path):
    case = make_case(tmp_path)
    report = run(case)
    assert report["status"] == "consistent" and report["inputs_stable"]
    assert report["findings"] == []
    assert [r["k5"] for r in report["records"]] == case["prepared"]["records"]
    assert report["records"][0]["k5"]["processing"]["reason"] == "historical:NO_FACE"
    assert report["records"][1]["k5"]["age"]["value"] is None
    assert report["records"][2]["k5"]["age"]["kind"] == "interval"
    assert report["metadata_audit"] == data.metadata.audit_manifest(case["prepared"])
    assert all(v == 0 for v in report["summary"]["formal_split_records"].values())
    packet = json.loads((tmp_path / report["frozen_inputs"]["path"]).read_text(encoding="utf-8"))
    assert packet["schema_id"] == data.FROZEN_SCHEMA and packet["manifest"] == case["prepared"]
    assert packet["assignments"] == case["plan"]["assignments"]
    assert (
        packet["random_seed"] is None
        and packet["assignment_method"] == "explicit_declarations_only"
    )
    assert (
        fixtures.fixtures.pin(tmp_path, tmp_path / report["frozen_inputs"]["path"])
        == report["frozen_inputs"]
    )
    for value in (report, packet):
        assert value["provenance_assessment"] == "self_reported_declarations_only"
        assert all(value[k] is False for k in data.FLAGS)
    assert sorted(p.name for p in (tmp_path / OUTPUT).iterdir()) == [
        "frozen-inputs.json",
        "report.json",
    ]


def test_metadata_only_even_when_opening_any_image_is_forbidden(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    original_open = Path.open

    def guard(path, *args, **kwargs):
        assert path.suffix.lower() not in {".png", ".jpg", ".onnx", ".npz", ".npy"}
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    assert run(case)["status"] == "consistent"


def test_one_record_with_no_pairs_has_an_empty_complete_review_ledger(tmp_path):
    with fixtures.raster() as image:
        raw = fixtures.encoded(image)
    report = run(make_case(tmp_path, bodies=[raw]))
    assert report["status"] == "consistent"
    assert report["summary"]["records"] == 1 and report["summary"]["candidate_reviews"] == 0
    assert report["basis"]["candidate_reviews"] == []


def test_repinned_foreign_algorithm_cannot_reuse_the_current_producer_version(tmp_path):
    case = make_case(tmp_path)
    source = case["screening"]
    path = tmp_path / source["inputs"][4]["path"]
    path.write_bytes(path.read_bytes() + b"\n# foreign algorithm revision\n")
    case["screen_plan"]["algorithm_sources"][0] = fixtures.fixtures.pin(tmp_path, path)
    plan_path = tmp_path / source["inputs"][0]["path"]
    fixtures.fixtures.save_json(plan_path, case["screen_plan"])
    source["inputs"][0] = fixtures.fixtures.pin(tmp_path, plan_path)
    source["inputs"][4:] = copy.deepcopy(case["screen_plan"]["algorithm_sources"])
    repin_screening(case)
    with pytest.raises(ValueError, match="SCREENING_ALGORITHM_SOURCE_MISMATCH"):
        run(case)


@pytest.mark.parametrize("decision", ["pending", "uncertain"])
def test_pending_review_blocks_without_losing_any_request(tmp_path, decision):
    case = make_case(tmp_path)
    case["basis"]["candidate_reviews"][0].update(
        decision=decision, origin="unknown", recorded_by=None, evidence=None
    )
    report = run(case)
    assert report["status"] == "blocked" and report["frozen_inputs"] is None
    assert len(report["records"]) == len(report["basis"]["candidate_reviews"]) == 3
    assert "CANDIDATE_REVIEW_UNRESOLVED" in {f["code"] for f in report["findings"]}
    assert sorted(p.name for p in (tmp_path / OUTPUT).iterdir()) == ["report.json"]


@pytest.mark.parametrize(
    "field,value",
    [("origin", "ai"), ("origin", "unknown"), ("recorded_by", None), ("evidence", None)],
)
def test_ai_or_missing_review_provenance_does_not_unblock(tmp_path, field, value):
    case = make_case(tmp_path)
    case["basis"]["candidate_reviews"][0][field] = value
    report = run(case)
    assert "CANDIDATE_REVIEW_PROVENANCE_UNRESOLVED" in {f["code"] for f in report["findings"]}


@pytest.mark.parametrize("origin", ["human", "official", "synthetic"])
def test_explicit_origin_remains_a_self_reported_claim(tmp_path, origin):
    case = make_case(tmp_path)
    for item in [*case["basis"]["groups"], *case["basis"]["candidate_reviews"]]:
        item["origin"] = origin
    report = run(case)
    assert report["status"] == "consistent" and not report["human_review_verified"]


@pytest.mark.parametrize("mutation", ["unknown", "ai", "no_evidence", "no_recorder"])
def test_group_basis_missing_is_a_blocking_finding(tmp_path, mutation):
    case = make_case(tmp_path)
    group = case["basis"]["groups"][0]
    if mutation in {"unknown", "ai"}:
        group["origin"] = mutation
    elif mutation == "no_evidence":
        group["evidence"] = None
    else:
        group["recorded_by"] = None
    report = run(case)
    assert "GROUP_BASIS_UNRESOLVED" in {f["code"] for f in report["findings"]}


def test_failed_screening_preserves_source_failure_and_blocks(tmp_path):
    case = make_case(tmp_path, failed=True)
    report = run(case)
    assert report["status"] == "blocked" and report["frozen_inputs"] is None
    assert len(report["records"]) == 3
    assert report["records"][1]["screening_error_code"] == "SOURCE_PREPARATION_FAILED"
    assert "SCREENING_INCOMPLETE_OR_UNSTABLE" in {f["code"] for f in report["findings"]}


def test_use_change_and_unassigned_are_reported_without_changing_original(tmp_path):
    case = make_case(tmp_path)
    case["plan"]["assignments"][1]["use"] = "test"
    case["plan"]["assignments"][2]["use"] = "unassigned"
    report = run(case)
    codes = {f["code"] for f in report["findings"]}
    assert {
        "PROPOSED_USE_DIFFERS_FROM_INPUT",
        "UNASSIGNED_USE",
        "GROUP_CROSSES_USES",
        "EXACT_FILE_CROSSES_USES",
    } <= codes
    assert all(r["k5"]["use"] == "development" for r in report["records"])


def split_groups(case):
    group = case["basis"]["groups"][0]
    first = group["sample_ids"].pop()
    case["basis"]["groups"].append(
        {**copy.deepcopy(group), "group_id": "group-B", "sample_ids": [first]}
    )
    case["plan"]["assignments"][2]["group_id"] = "group-B"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("local", "DECLARED_IDENTITY_SPLIT"),
        ("linked", "LINKED_IDENTITY_SPLIT"),
        ("parent", "LINEAGE_SPLIT"),
    ],
)
def test_declared_subjects_links_and_lineage_cannot_be_split(tmp_path, kind, expected):
    case = make_case(tmp_path)

    def mutate(packet):
        first, _, last = packet["records"]
        if kind == "local":
            last["subject_id"] = first["subject_id"]
        elif kind == "linked":
            first["linked_subject_id"] = last["linked_subject_id"] = "linked-A"
        else:
            last.update(kind="crop", parent_id=first["sample_id"])

    update_k5_and_screening(case, mutate)
    split_groups(case)
    report = run(case)
    assert expected in {f["code"] for f in report["findings"]}
    assert "REVIEWED_DUPLICATE_SPLIT" in {f["code"] for f in report["findings"]}


def test_same_local_id_in_different_datasets_does_not_establish_identity(tmp_path):
    case = make_case(tmp_path)

    def mutate(packet):
        packet["datasets"].append({**copy.deepcopy(packet["datasets"][0]), "dataset_id": "other"})
        packet["records"][2].update(dataset_id="other", subject_id="A")

    update_k5_and_screening(case, mutate)
    split_groups(case)
    report = run(case)
    assert "DECLARED_IDENTITY_SPLIT" not in {f["code"] for f in report["findings"]}
    assert not report["cross_source_identity_proven"]


def test_exact_file_cannot_be_overridden_as_different_content(tmp_path):
    case = make_case(tmp_path)
    case["basis"]["candidate_reviews"][0]["decision"] = "different_content"
    assert "EXACT_FILE_REVIEW_CONFLICT" in {f["code"] for f in run(case)["findings"]}


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "flag",
        "k5",
        "rows",
        "pairs",
        "summary",
        "candidate",
        "candidate_bool",
        "matches",
        "distance",
        "nan",
        "pixels",
        "groups",
        "components",
    ],
)
def test_repinned_screening_cannot_omit_or_forge_structural_evidence(tmp_path, mutation):
    case = make_case(tmp_path)
    source = case["screening"]
    if mutation == "version":
        source["producer_sha256"] = "0" * 64
    elif mutation == "flag":
        source["no_leakage_accepted"] = True
    elif mutation == "k5":
        source["records"][0]["k5"]["age"]["value"] = 46
    elif mutation == "rows":
        source["records"].pop()
    elif mutation == "pairs":
        source["pair_ledger"].pop()
    elif mutation == "summary":
        source["summary"]["requested_pairs"] = 0
    elif mutation == "candidate":
        source["candidates"].pop()
    elif mutation == "candidate_bool":
        source["pair_ledger"][0]["candidate_id"] = False
    elif mutation == "matches":
        source["candidates"][0]["matched_view_pairs"].pop()
    elif mutation == "distance":
        source["candidates"][0]["matched_view_pairs"][0]["horizontal_hamming"] = 1
    elif mutation == "nan":
        source["candidates"][0]["matched_view_pairs"][0]["gray32_mae"] = float("nan")
    elif mutation == "pixels":
        source["candidates"][0]["equal_rgb_pixel_view_pairs"] = []
    elif mutation == "groups":
        source["exact_groups"] = []
    else:
        source["components"] = []
    repin_screening(case)
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_assignment",
        "order",
        "unknown_use",
        "omitted_review",
        "review_id",
        "review_pair",
        "extra_member",
        "missing_member",
        "duplicate_member",
        "extra_plan",
    ],
)
def test_complete_assignment_basis_and_review_contracts(tmp_path, mutation):
    case = make_case(tmp_path)
    if mutation == "missing_assignment":
        case["plan"]["assignments"].pop()
    elif mutation == "order":
        case["plan"]["assignments"].reverse()
    elif mutation == "unknown_use":
        case["plan"]["assignments"][0]["use"] = "new-use"
    elif mutation == "omitted_review":
        case["basis"]["candidate_reviews"].pop()
    elif mutation == "review_id":
        case["basis"]["candidate_reviews"][0]["candidate_id"] = True
    elif mutation == "review_pair":
        case["basis"]["candidate_reviews"][0]["sample_ids"].reverse()
    elif mutation == "extra_member":
        case["basis"]["groups"][0]["sample_ids"].append("not-present")
    elif mutation == "missing_member":
        case["basis"]["groups"][0]["sample_ids"].pop()
    elif mutation == "duplicate_member":
        case["basis"]["groups"][0]["sample_ids"].append(case["basis"]["groups"][0]["sample_ids"][0])
    else:
        case["plan"]["ignore_pending_reviews"] = True
    with pytest.raises(ValueError):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("which", ["manifest", "screening", "evidence"])
def test_initial_pin_drift_rejects_before_writes(tmp_path, which):
    case = make_case(tmp_path)
    paths = {
        "manifest": case["plan"]["prepared_manifest"]["path"],
        "screening": case["plan"]["screening_report"]["path"],
        "evidence": case["basis"]["groups"][0]["evidence"]["path"],
    }
    path = tmp_path / paths[which]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="INPUT_PIN_MISMATCH"):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("which", ["plan", "basis", "manifest", "screening", "evidence"])
def test_final_pin_drift_produces_blocked_report_without_packet(tmp_path, monkeypatch, which):
    case = make_case(tmp_path)
    original = data._constraints

    def changed(*args):
        result = original(*args)
        paths = {
            "plan": "output/research/input/freeze-plan.json",
            "basis": "output/research/input/freeze-basis.json",
            "manifest": case["plan"]["prepared_manifest"]["path"],
            "screening": case["plan"]["screening_report"]["path"],
            "evidence": case["basis"]["groups"][0]["evidence"]["path"],
        }
        path = tmp_path / paths[which]
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(data, "_constraints", changed)
    report = run(case)
    assert not report["inputs_stable"] and report["status"] == "blocked"
    assert report["frozen_inputs"] is None
    assert report["findings"][-1]["code"] == "INPUT_CHANGED_AT_FINAL_CHECK"


def test_image_evidence_pin_is_rejected_without_read(tmp_path):
    case = make_case(tmp_path)
    case["basis"]["groups"][0]["evidence"] = case["screening"]["records"][0]["normalized"]
    with pytest.raises(ValueError, match="METADATA_SUFFIX_REQUIRED"):
        run(case)


def test_disk_output_scope_and_old_evidence_preserved(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    with pytest.raises(ValueError):
        run(case, "data/frozen")
    report = run(case)
    saved = (tmp_path / report["receipt"]).read_bytes()
    with pytest.raises(ValueError, match="OUTPUT_MUST_BE_NEW"):
        run(case)
    assert (tmp_path / report["receipt"]).read_bytes() == saved
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(data.shutil, "disk_usage", lambda _: usage._replace(free=0))
    with pytest.raises(ValueError, match="INSUFFICIENT_SPACE"):
        run(case, OUTPUT + "-new")


def test_metadata_budget_is_checked_before_opening(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.setattr(data, "MAX_INPUTS", 1)
    with pytest.raises(ValueError, match="METADATA_INPUT_COUNT_LIMIT"):
        run(case)
    monkeypatch.setattr(data, "MAX_INPUTS", 64)
    monkeypatch.setattr(data, "MAX_TOTAL_METADATA", 1)
    with pytest.raises(ValueError, match="METADATA_TOTAL_BYTE_LIMIT"):
        run(case)


@pytest.mark.parametrize(
    "blocked,wrong_hash,expected", [(False, False, 0), (True, False, 1), (False, True, 2)]
)
def test_cli_consistent_blocked_and_rejected(tmp_path, blocked, wrong_hash, expected):
    case = make_case(tmp_path)
    if blocked:
        case["basis"]["candidate_reviews"][0]["decision"] = "pending"
    name, digest = freeze(case)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "preprocessing.split_freeze",
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
    assert (tmp_path / OUTPUT / "frozen-inputs.json").exists() is (expected == 0)
