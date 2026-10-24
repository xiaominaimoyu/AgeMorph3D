"""Synthetic N8 metadata audits: neither assets nor legal clearance are inferred."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools/evaluation_readiness_probe.py"
_SPEC = importlib.util.spec_from_file_location("evaluation_readiness_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    raw = path.read_bytes()
    return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def pin(path, root):
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


@pytest.fixture
def case(tmp_path):
    root = tmp_path
    for name in probe.SOURCE_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        actual = _PATH if name.endswith("tools/evaluation_readiness_probe.py") else Path(__file__)
        path.write_bytes(actual.read_bytes())
    evidence = write(
        root, "docs/evidence.json", {"statement": "Synthetic evidence, no permission grant."}
    )
    protocol = {
        "schema_version": 1,
        "protocol_id": probe.N0_PROTOCOL,
        "source_age_policy": "unknown_stays_null",
        "same_age_policy": "exact_integer_label_only",
        "target_ages": [20, 45, 70],
        "statistics": {"age_strata": list(probe.STRATA)},
        "expected_adult_images": 3,
        "expected_adult_identities": 3,
        "expected_bridge_samples": 1,
        "expected_known_controls": 1,
        "grouping": {
            "seed": "synthetic",
            "development_subject_ids": ["001"],
            "calibration_identity_count": 1,
            "historical_preprocessing_exposed": True,
            "independent_external_evaluation": False,
            "near_duplicate_screening": "pending",
        },
        "thresholds": {"quality_acceptance": None},
        "service_ready": False,
        "years_calibrated": False,
        "identity_accepted": False,
        "g3_complete": False,
    }
    identities, rows = [], []
    for index, group in enumerate(probe.GROUPS, 1):
        subject = f"{index:03}"
        identities.append(
            {
                "subject_id": subject,
                "group": group,
                "historical_preprocessing_exposed": True,
                "previously_viewed": group == "development",
            }
        )
        rows.append(
            {
                "subject_id": subject,
                "group": group,
                "source_age": 20,
                "path": f"data/images/{subject}A20.JPG",
                "sha256": str(index) * 64,
                "bytes": 100,
            }
        )
    all_coverage = {
        label: {"images": 3 if label == "20-29" else 0, "identities": 3 if label == "20-29" else 0}
        for label in probe.STRATA
    }
    one_coverage = {
        label: {"images": 1 if label == "20-29" else 0, "identities": 1 if label == "20-29" else 0}
        for label in probe.STRATA
    }
    summary = {
        "adult_images": 3,
        "adult_identities": 3,
        "identity_groups": dict.fromkeys(probe.GROUPS, 1),
        "image_groups": dict.fromkeys(probe.GROUPS, 1),
        "control_statuses": {"reused_existing": 1},
        "same_age_controls_complete": True,
        "age_strata": {
            "all": all_coverage,
            **{group: copy.deepcopy(one_coverage) for group in probe.GROUPS},
        },
        "distinct_age_pair_eligible_identities": dict.fromkeys(("all", *probe.GROUPS), 0),
    }
    manifest = {
        "schema_version": 1,
        "protocol_id": probe.N0_PROTOCOL,
        "research_only": True,
        "training_use": False,
        "service_ready": False,
        "g3_complete": False,
        "independent_external_evaluation": False,
        "independent_landmark_nme_evaluation": False,
        "historical_preprocessing_exposed": True,
        "inputs": {},
        "identities": identities,
        "adult_images": rows,
        "bridge_cases": [
            {
                "sample_id": "synthetic",
                "subject_id": "001",
                "group": "development",
                "source_age": {
                    "value": 20,
                    "method": "dataset_filename",
                    "independently_verified": False,
                },
                "source_status": "passed",
                "same_age_control": {"status": "reused_existing", "target_age": 20},
            }
        ],
        "summary": summary,
    }
    catalog = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL,
        "reviewed_on": "2026-10-23",
        "scope": "Metadata preparation only.",
        "assets": [
            {
                "asset_id": asset_id,
                "acquisition_state": "metadata_present",
                "local_metadata": [evidence],
                "licenses": {
                    dimension: {
                        "status": "documented",
                        "evidence": [evidence],
                        "source_urls": ["https://example.org/terms"],
                        "reason": "Evidence is recorded, not legally accepted.",
                    }
                    for dimension in probe.DIMENSIONS
                },
                "independence": "separate_candidate" if asset_id.endswith("_evaluator") else None,
                "next_action": "Obtain an independent review.",
            }
            for asset_id in probe.ASSETS
        ],
    }
    for index in range(100):
        seed = f"synthetic-{index}"
        if (
            min(
                ("002", "003"),
                key=lambda subject: hashlib.sha256(f"{seed}:{subject}".encode()).hexdigest(),
            )
            == "002"
        ):
            protocol["grouping"]["seed"] = seed
            break
    return {
        "root": root,
        "protocol": protocol,
        "manifest": manifest,
        "summary": summary,
        "catalog": catalog,
        "evidence": evidence,
    }


def freeze(case):
    root = case["root"]
    protocol_pin = write(root, "docs/protocol.json", case["protocol"])
    case["manifest"]["inputs"]["protocol"] = protocol_pin
    return write(
        root,
        "output/research/input/study-plan.json",
        {
            "protocol_id": probe.PROTOCOL,
            "catalog": write(root, "docs/catalog.json", case["catalog"]),
            "age_protocol": protocol_pin,
            "n0_manifest": write(root, "output/research/n0/manifest.json", case["manifest"]),
            "n0_summary": write(root, "output/research/n0/summary.json", case["summary"]),
            "source_files": [pin(root / name, root) for name in probe.SOURCE_FILES],
        },
    )


def run(case):
    plan = freeze(case)
    return probe.build_report(case["root"], case["root"] / plan["path"])


def test_all_documented_metadata_never_enables_quality_or_production(case):
    report = run(case)
    assert report["integrity_status"] == "passed"
    assert report["preparation_status"] == "blocked"
    assert all(asset["status"] == "metadata_available" for asset in report["assets"])
    assert all(report[field] is False for field in probe.FALSE_FLAGS)
    assert report["legal_permission_established"] is False
    assert report["live_artifact_integrity_verified"] is False
    assert {blocker["code"] for blocker in report["blockers"]} >= {
        "EVALUATOR_DOMAIN_VALIDATION_MISSING",
        "QUALITY_THRESHOLD_NOT_FROZEN",
        "AGE_STRATUM_MISSING",
        "NEAR_DUPLICATE_REVIEW_NOT_VALIDATED",
    }


def test_no_images_or_weights_are_opened(case, monkeypatch):
    freeze(case)
    original = Path.open
    opened = []

    def guarded(path, *args, **kwargs):
        assert path.suffix.lower() in probe.SUFFIXES
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    report = probe.build_report(
        case["root"], case["root"] / "output/research/input/study-plan.json"
    )
    assert opened and report["images_opened"] is False
    assert not (case["root"] / "data/images").exists()


def test_only_code_license_cannot_clear_weights(case):
    asset = case["catalog"]["assets"][0]
    asset["licenses"]["weights"].update(status="unresolved", evidence=[])
    report = run(case)
    assert report["assets"][0]["status"] == "unresolved"
    assert any(item.get("dimension") == "weights" for item in report["blockers"])


def test_missing_evaluator_and_sam_loss_are_separate_blockers(case):
    age, identity = case["catalog"]["assets"][6:8]
    age.update(acquisition_state="not_acquired", local_metadata=[], independence="not_assessed")
    identity["independence"] = "sam_training_loss"
    report = run(case)
    assert report["assets"][6]["status"] == "missing"
    independent = [
        item
        for item in report["blockers"]
        if item["code"] == "EVALUATOR_INDEPENDENCE_NOT_ESTABLISHED"
    ]
    assert {item["independence"] for item in independent} == {"not_assessed", "sam_training_loss"}


@pytest.mark.parametrize("bad", [True, 0, probe.MAX_BYTES + 1])
def test_pin_size_is_strict_and_bounded(case, bad):
    plan_pin = freeze(case)
    path = case["root"] / plan_pin["path"]
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["catalog"]["bytes"] = bad
    write(case["root"], plan_pin["path"], plan)
    with pytest.raises(ValueError):
        probe.build_report(case["root"], path)


@pytest.mark.parametrize(
    "bad",
    [
        "../outside.json",
        "C:/outside.json",
        "docs\\catalog.json",
        "docs/./catalog.json",
        "/outside.json",
        "data/weights.pt",
        "data/image.png",
    ],
)
def test_noncanonical_or_binary_pin_rejected_without_open(case, bad):
    plan_pin = freeze(case)
    path = case["root"] / plan_pin["path"]
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["catalog"]["path"] = bad
    write(case["root"], plan_pin["path"], plan)
    with pytest.raises(ValueError):
        probe.build_report(case["root"], path)


def test_changed_evidence_fails_pin(case):
    plan = freeze(case)
    (case["root"] / case["evidence"]["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="pin mismatch"):
        probe.build_report(case["root"], case["root"] / plan["path"])


@pytest.mark.parametrize("location", ["plan", "evidence"])
def test_duplicate_json_keys_rejected_for_all_inputs(case, location):
    plan = freeze(case)
    path = case["root"] / (plan["path"] if location == "plan" else case["evidence"]["path"])
    path.write_text('{"value":1,"value":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON"):
        probe.build_report(case["root"], case["root"] / plan["path"])


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing_asset",
        "duplicate_asset",
        "missing_dimension",
        "no_evidence",
        "acquisition",
        "independence",
        "http_url",
    ],
)
def test_strict_catalog_rejects_unsupported_claims(case, mutation):
    catalog = case["catalog"]
    asset = catalog["assets"][0]
    if mutation == "extra":
        catalog["quality_accepted"] = True
    elif mutation == "missing_asset":
        catalog["assets"].pop()
    elif mutation == "duplicate_asset":
        catalog["assets"][-1] = copy.deepcopy(asset)
    elif mutation == "missing_dimension":
        asset["licenses"].pop("weights")
    elif mutation == "no_evidence":
        asset["licenses"]["weights"]["evidence"] = []
    elif mutation == "acquisition":
        asset["acquisition_state"] = "not_acquired"
    elif mutation == "independence":
        asset["independence"] = "separate_candidate"
    else:
        asset["licenses"]["code"]["source_urls"] = ["http://example.org/terms"]
    with pytest.raises(ValueError):
        run(case)


def test_duplicate_pin_rejected(case):
    case["catalog"]["assets"][0]["local_metadata"] *= 2
    with pytest.raises(ValueError, match="Duplicate pin"):
        run(case)


@pytest.mark.parametrize(
    "mutation",
    [
        "viewed_holdout",
        "age_unknown_default",
        "counts",
        "summary",
        "production",
        "hash_leakage",
        "schema",
        "seed_assignment",
    ],
)
def test_n0_provenance_and_metadata_are_checked(case, mutation):
    manifest = case["manifest"]
    if mutation == "viewed_holdout":
        manifest["identities"][2]["previously_viewed"] = True
    elif mutation == "age_unknown_default":
        manifest["bridge_cases"][0]["source_age"] = {
            "value": None,
            "method": "dataset_filename",
            "independently_verified": False,
        }
    elif mutation == "counts":
        case["protocol"]["expected_adult_images"] = 4
    elif mutation == "summary":
        case["summary"]["age_strata"]["calibration_research"]["70"]["images"] = 1
    elif mutation == "production":
        manifest["service_ready"] = True
    elif mutation == "hash_leakage":
        manifest["adult_images"][1]["sha256"] = manifest["adult_images"][0]["sha256"]
    elif mutation == "schema":
        manifest["schema_version"] = True
    else:
        for record in [*manifest["identities"][1:], *manifest["adult_images"][1:]]:
            record["group"] = (
                "evaluation_research_holdout"
                if record["group"] == "calibration_research"
                else "calibration_research"
            )
    with pytest.raises(ValueError):
        run(case)


def test_source_files_must_pin_running_implementation_and_tests(case):
    plan_pin = freeze(case)
    path = case["root"] / plan_pin["path"]
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["source_files"] = plan["source_files"][:1]
    write(case["root"], plan_pin["path"], plan)
    with pytest.raises(ValueError, match="implementation and tests"):
        probe.build_report(case["root"], path)


def test_inputs_rechecked_after_report_construction(case, monkeypatch):
    plan = freeze(case)
    original = probe._catalog

    def mutate(value, inputs):
        assets = original(value, inputs)
        (case["root"] / case["evidence"]["path"]).write_text("{}", encoding="utf-8")
        return assets

    monkeypatch.setattr(probe, "_catalog", mutate)
    with pytest.raises(ValueError, match="pin mismatch"):
        probe.build_report(case["root"], case["root"] / plan["path"])


def test_cli_success_is_blocked_and_existing_output_is_preserved(case, capsys):
    plan = freeze(case)
    args = [
        "--root",
        str(case["root"]),
        "--study-plan",
        plan["path"],
        "--output-dir",
        "output/research/audit",
    ]
    assert probe.main(args) == 0
    path = case["root"] / "output/research/audit/report.json"
    before = path.read_bytes()
    assert json.loads(before)["preparation_status"] == "blocked"
    assert probe.main(args) == 1
    assert path.read_bytes() == before
    assert "already exists" in capsys.readouterr().out


def test_cli_rejects_output_outside_research(case):
    plan = freeze(case)
    assert (
        probe.main(
            [
                "--root",
                str(case["root"]),
                "--study-plan",
                plan["path"],
                "--output-dir",
                "docs/audit",
            ]
        )
        == 1
    )
    assert not (case["root"] / "docs/audit").exists()
