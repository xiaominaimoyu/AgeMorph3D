"""Metadata-only schema, declared leakage, N0 failure and CLI publication tests."""

import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "dataset_manifest", ROOT / "preprocessing/dataset_manifest.py"
)
data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(data)


def pin(name, content=b"not read by metadata audit"):
    return {"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


@pytest.fixture
def manifest():
    evidence = pin("data/registrations/synthetic.md")
    dataset = {
        "dataset_id": "d1",
        "version": "synthetic-v1",
        "purpose_registration": {"status": "recorded", "evidence": evidence},
        "identity_review": {"status": "recorded", "evidence": evidence},
        "training_overlap": {"status": "excluded", "evidence": evidence},
        "near_duplicate_review": {"status": "recorded", "evidence": evidence},
    }
    records = []
    for n, use in enumerate(("train", "validation", "test"), 1):
        records.append(
            {
                "sample_id": f"sample-{n}",
                "dataset_id": "d1",
                "file": pin(f"data/not-present/{n}.png", str(n).encode()),
                "subject_id": f"{n:03}",
                "linked_subject_id": None,
                "parent_id": None,
                "kind": "original",
                "use": use,
                "age": data.age_label("exact", 30 + n),
                "age_source": "dataset_annotation",
                "exposure": dict.fromkeys(
                    ("preprocessing", "model_selection", "result_inspection"), "no"
                ),
                "processing": {"status": "ok", "reason": None},
            }
        )
    return {
        "schema_id": data.SCHEMA,
        "schema_version": 1,
        "task": data.TASK,
        "manifest_id": "synthetic-v1",
        "origin": None,
        "datasets": [dataset],
        "records": records,
    }


@pytest.fixture
def n0():
    groups = {
        "001": "development",
        "002": "calibration_research",
        "003": "evaluation_research_holdout",
    }
    rows = []
    for subject, age in [("001", 21), ("001", 22), ("002", 30), ("003", 70)]:
        rows.append(
            dict(
                pin(f"data/FGNET/images/{subject}A{age:02}.JPG", f"{subject}:{age}".encode()),
                subject_id=subject,
                source_age=age,
                group=groups[subject],
            )
        )
    failure = rows[0]
    return {
        "schema_version": 1,
        "protocol_id": "agemorph3d-age-research-v1",
        "frozen_on": "2026-10-20",
        "research_only": True,
        "historical_preprocessing_exposed": True,
        "training_use": False,
        "service_ready": False,
        "g3_complete": False,
        "independent_external_evaluation": False,
        "identities": [
            {
                "subject_id": s,
                "group": g,
                "historical_preprocessing_exposed": True,
                "previously_viewed": False,
            }
            for s, g in groups.items()
        ],
        "adult_images": rows,
        "bridge_cases": [
            {
                "source_status": "failed",
                "error_code": "NO_FACE",
                "source": {k: failure[k] for k in ("path", "bytes", "sha256")},
                "subject_id": "001",
                "group": "development",
            }
        ],
        "summary": {
            "control_statuses": {"blocked_source_failure": 1},
            "adult_images": 4,
            "adult_identities": 3,
            "identity_groups": dict.fromkeys(data.RESEARCH_USES, 1),
            "image_groups": {
                "development": 2,
                "calibration_research": 1,
                "evaluation_research_holdout": 1,
            },
        },
    }


def codes(report):
    return {f["code"] for f in report["findings"]}


def test_consistent_declarations_do_not_grant_training_or_independence(manifest, monkeypatch):
    original = copy.deepcopy(manifest)

    def forbidden(*args, **kwargs):
        raise AssertionError("Pure schema audit must not read files or evidence pins.")

    monkeypatch.setattr(Path, "open", forbidden)
    report = data.audit_manifest(manifest)
    assert report["status"] == "metadata_consistent" and report["findings"] == []
    assert report["summary"]["records"] == 3 and report["summary"]["local_subjects"] == 3
    assert report["summary"]["uses"] == {"train": 1, "validation": 1, "test": 1}
    assert all(report[k] is False for k in data.FLAGS)
    assert report["binary_integrity_verified"] is report["near_duplicates_recomputed"] is False
    assert report["split_assignment_performed"] is False and manifest == original


@pytest.mark.parametrize(
    ("kind", "kwargs", "scope"),
    [
        ("exact", {"value": 0}, "outside"),
        ("exact", {"value": 19.9}, "outside"),
        ("exact", {"value": 20}, "inside"),
        ("exact", {"value": 42.5}, "inside"),
        ("exact", {"value": 70}, "inside"),
        ("exact", {"value": 70.1}, "outside"),
        ("exact", {"value": 120}, "outside"),
        ("interval", {"lower": 20, "upper": 30}, "inside"),
        ("interval", {"lower": 18, "upper": 22}, "outside_or_crossing"),
        ("interval", {"lower": 70, "upper": 80}, "outside_or_crossing"),
        ("unknown", {}, "unknown"),
    ],
)
def test_age_precision_and_outside_scope_are_retained(manifest, kind, kwargs, scope):
    label = data.age_label(kind, **kwargs)
    manifest["records"][0]["age"] = label
    if kind == "unknown":
        manifest["records"][0]["age_source"] = "unknown"
    result = data.audit_manifest(manifest)
    assert result["record_checks"][0]["age_scope"] == scope
    assert manifest["records"][0]["age"] == label and result["summary"]["records"] == 3
    if kind != "exact":
        assert label["value"] is None
    assert result["summary"]["age_kinds"][kind] >= 1


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        ("exact", {"value": True}),
        ("exact", {"value": float("nan")}),
        ("exact", {"value": float("inf")}),
        ("exact", {"value": -1}),
        ("exact", {"value": 121}),
        ("exact", {"value": 30, "lower": 20}),
        ("interval", {"lower": 30, "upper": 30}),
        ("interval", {"lower": 20, "upper": 30, "value": 25}),
        ("unknown", {"value": 45}),
        ("unknown", {"lower": 20}),
        ("estimated", {"value": 30}),
    ],
)
def test_invalid_age_and_midpoint_imputation_rejected(kind, kwargs):
    with pytest.raises(ValueError):
        data.age_label(kind, **kwargs)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda x: x["records"][2].update(subject_id="001"), "IDENTITY_OR_LINEAGE_CROSSES_USES"),
        (
            lambda x: x["records"][2].update(file=copy.deepcopy(x["records"][0]["file"])),
            "DECLARED_DUPLICATE_CONTENT_CROSSES_USES",
        ),
        (
            lambda x: x["records"][2]["file"].update(
                sha256=x["records"][0]["file"]["sha256"], bytes=999
            ),
            "DECLARED_HASH_SIZE_CONFLICT",
        ),
        (
            lambda x: x["records"][2]["file"].update(path=x["records"][0]["file"]["path"]),
            "DECLARED_PATH_CONTENT_CONFLICT",
        ),
        (
            lambda x: x["records"][2].update(parent_id="sample-1", kind="crop"),
            "IDENTITY_OR_LINEAGE_CROSSES_USES",
        ),
        (
            lambda x: x["records"][2].update(parent_id="sample-1", kind="generated"),
            "GENERATED_IMAGE_IS_NOT_AGE_GROUND_TRUTH",
        ),
        (lambda x: x["records"][2].update(subject_id=None), "FORMAL_IDENTITY_UNRESOLVED"),
        (
            lambda x: x["records"][2]["exposure"].update(preprocessing="yes"),
            "TEST_EXPOSURE_NOT_CLEAR",
        ),
        (
            lambda x: x["records"][2]["exposure"].update(result_inspection="unknown"),
            "TEST_EXPOSURE_NOT_CLEAR",
        ),
        (
            lambda x: x["records"][2]["processing"].update(status="failed", reason="NO_FACE"),
            "FORMAL_PROCESSING_NOT_VERIFIED",
        ),
        (
            lambda x: x["datasets"][0].update(
                purpose_registration={"status": "unresolved", "evidence": None}
            ),
            "USE_REGISTRATION_UNRESOLVED",
        ),
        (
            lambda x: x["datasets"][0].update(
                identity_review={"status": "pending", "evidence": None}
            ),
            "IDENTITY_REVIEW_PENDING",
        ),
        (
            lambda x: x["datasets"][0].update(
                near_duplicate_review={"status": "pending", "evidence": None}
            ),
            "NEAR_DUPLICATE_REVIEW_PENDING",
        ),
        (
            lambda x: x["datasets"][0].update(
                training_overlap={"status": "present", "evidence": pin("data/overlap.md")}
            ),
            "TEST_TRAINING_OVERLAP_NOT_EXCLUDED",
        ),
        (
            lambda x: x["records"][2].update(use="evaluation_research_holdout"),
            "FORMAL_SPLITS_NOT_DEFINED",
        ),
    ],
)
def test_declared_leakage_unresolved_reviews_and_failures_are_visible(manifest, change, expected):
    change(manifest)
    result = data.audit_manifest(manifest)
    assert expected in codes(result)
    assert len(result["record_checks"]) == len(manifest["records"]) == 3
    assert all(result[k] is False for k in data.FLAGS)


def test_namespace_identity_linking_and_transitive_lineage(manifest):
    dataset = copy.deepcopy(manifest["datasets"][0])
    dataset["dataset_id"] = "d2"
    manifest["datasets"].append(dataset)
    manifest["records"][2].update(dataset_id="d2", subject_id="001")
    assert "IDENTITY_OR_LINEAGE_CROSSES_USES" not in codes(data.audit_manifest(manifest))
    manifest["records"][0]["linked_subject_id"] = "cross-source-person"
    manifest["records"][2]["linked_subject_id"] = "cross-source-person"
    assert "IDENTITY_OR_LINEAGE_CROSSES_USES" in codes(data.audit_manifest(manifest))
    manifest["records"][2]["linked_subject_id"] = None
    manifest["records"][1].update(parent_id="sample-1", kind="crop", use="train")
    manifest["records"][2].update(parent_id="sample-2", kind="render")
    conflict = next(
        f
        for f in data.audit_manifest(manifest)["findings"]
        if f["code"] == "IDENTITY_OR_LINEAGE_CROSSES_USES"
    )
    assert conflict["sample_ids"] == ["sample-1", "sample-2", "sample-3"]


def test_within_use_duplicates_and_failed_exclusions_not_removed(manifest):
    manifest["records"][2].update(use="train", file=copy.deepcopy(manifest["records"][0]["file"]))
    manifest["records"][1]["processing"] = {"status": "excluded", "reason": "out of frozen scope"}
    result = data.audit_manifest(manifest)
    assert result["summary"]["declared_duplicate_groups"] == 1
    assert "DECLARED_DUPLICATE_CONTENT_CROSSES_USES" not in codes(result)
    assert result["summary"]["processing"] == {"ok": 2, "excluded": 1}
    assert len(result["record_checks"]) == 3


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(schema_version=True),
        lambda x: x.update(production_enabled=True),
        lambda x: x["records"].__setitem__(1, copy.deepcopy(x["records"][0])),
        lambda x: x["datasets"].append(copy.deepcopy(x["datasets"][0])),
        lambda x: x["records"][0].update(dataset_id="missing"),
        lambda x: x["records"][0]["file"].update(bytes=True),
        lambda x: x["records"][0]["file"].update(path="../private.jpg"),
        lambda x: x["records"][0]["file"].update(path="C:/private.jpg"),
        lambda x: x["records"][0]["file"].update(path="data//x.jpg"),
        lambda x: x["records"][0]["file"].update(path="data/private\x00.jpg"),
        lambda x: x["records"][0].update(use="evaluation"),
        lambda x: x["records"][0].update(parent_id="sample-1", kind="crop"),
        lambda x: x["records"][0].update(parent_id="missing", kind="crop"),
        lambda x: x["records"][0].update(kind="crop"),
        lambda x: x["records"][0]["processing"].update(status="failed"),
        lambda x: x["records"][0]["exposure"].update(preprocessing=False),
        lambda x: x["datasets"][0]["identity_review"].update(evidence=None),
    ],
)
def test_schema_aliases_missing_parents_and_claims_are_rejected(manifest, change):
    change(manifest)
    with pytest.raises(ValueError):
        data.validate_manifest(manifest)


def test_multi_node_parent_cycle_is_rejected(manifest):
    manifest["records"][0].update(kind="crop", parent_id="sample-2")
    manifest["records"][1].update(kind="crop", parent_id="sample-1")
    with pytest.raises(ValueError, match="cyclic"):
        data.validate_manifest(manifest)


def test_n0_conversion_preserves_groups_historical_failure_and_unknown_exposure(n0):
    original = copy.deepcopy(n0)
    converted = data.from_n0(n0, pin("output/research/n0.json"))
    assert [r["use"] for r in converted["records"]] == [r["group"] for r in n0["adult_images"]]
    assert [r["file"]["sha256"] for r in converted["records"]] == [
        r["sha256"] for r in n0["adult_images"]
    ]
    assert converted["records"][0]["processing"] == {
        "status": "failed",
        "reason": "historical_bridge:NO_FACE",
    }
    assert all(r["processing"]["status"] == "not_checked" for r in converted["records"][1:])
    assert all(
        r["exposure"]
        == {"preprocessing": "yes", "model_selection": "unknown", "result_inspection": "unknown"}
        for r in converted["records"]
    )
    assert all(r["linked_subject_id"] is None for r in converted["records"])
    report = data.audit_manifest(converted)
    assert report["summary"]["records"] == 4 and report["summary"]["local_subjects"] == 3
    assert "FORMAL_SPLITS_NOT_DEFINED" in codes(report) and n0 == original


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(training_use=True),
        lambda x: x.update(schema_version=True),
        lambda x: x["adult_images"].pop(),
        lambda x: x["adult_images"][0].update(source_age=22),
        lambda x: x["adult_images"][0].update(group="test"),
        lambda x: x["identities"][0].update(historical_preprocessing_exposed=False),
        lambda x: x["summary"]["identity_groups"].update(development=99),
        lambda x: x["bridge_cases"][0].update(error_code=None),
        lambda x: x["bridge_cases"][0]["source"].update(sha256="f" * 64),
        lambda x: x["bridge_cases"].append(copy.deepcopy(x["bridge_cases"][0])),
    ],
)
def test_n0_corruption_does_not_resplit_or_drop_failed_sources(n0, change):
    change(n0)
    with pytest.raises(ValueError):
        data.from_n0(n0, pin("output/research/n0.json"))


def test_n0_cannot_omit_a_reported_failed_bridge_source(n0):
    n0["bridge_cases"] = []
    with pytest.raises(ValueError, match="failed-source denominator"):
        data.from_n0(n0, pin("output/research/n0.json"))


def test_output_json_budget_is_checked_before_publication(tmp_path, manifest, monkeypatch):
    source = tmp_path / "input.json"
    raw = data._encode(manifest)
    source.write_bytes(raw)
    monkeypatch.setattr(data, "MAX_JSON_BYTES", 100)
    with pytest.raises(ValueError, match="Output JSON"):
        data.export_manifest(
            tmp_path, "input.json", hashlib.sha256(raw).hexdigest(), "output/research/too-large"
        )
    assert not (tmp_path / "output/research/too-large").exists()


def test_output_refuses_existing_directory_and_drift_cleanup_is_owned(
    tmp_path, manifest, monkeypatch
):
    source = tmp_path / "input.json"
    source.write_bytes(data._encode(manifest))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    target = tmp_path / "output/research/existing"
    target.mkdir(parents=True)
    (target / "other.txt").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        data.export_manifest(tmp_path, "input.json", digest, "output/research/existing")
    assert (target / "other.txt").read_bytes() == b"keep"
    original = data._read
    count = 0

    def drift(path, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 3:
            (tmp_path / "output/research/late/other.txt").write_bytes(b"not owned")
            source.write_bytes(b"changed")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(data, "_read", drift)
    with pytest.raises(ValueError):
        data.export_manifest(tmp_path, "input.json", digest, "output/research/late")
    assert sorted(p.name for p in (tmp_path / "output/research/late").iterdir()) == ["other.txt"]


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_duplicate_keys_and_nonfinite_json_are_rejected(payload):
    with pytest.raises(ValueError):
        data._json(payload)


def test_reads_are_bounded_and_symlink_escape_rejected(tmp_path, monkeypatch):
    source = tmp_path / "x.json"
    source.write_bytes(b"12345")
    with pytest.raises(ValueError):
        data._read(source, 4)
    native_open = Path.open
    monkeypatch.setattr(
        Path,
        "open",
        lambda p, *a, **k: io.BytesIO(b"1234567") if p == source else native_open(p, *a, **k),
    )
    with pytest.raises(ValueError):
        data._read(source, 5)
    monkeypatch.undo()
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.write_bytes(b"outside")
    try:
        (tmp_path / "link.json").symlink_to(outside)
    except OSError:
        pytest.skip("Host cannot create a file symlink.")
    with pytest.raises(ValueError):
        data._resolve(tmp_path, "link.json")


@pytest.mark.parametrize(("mode", "expected"), [("consistent", 0), ("findings", 1), ("invalid", 2)])
def test_actual_cli_exit_codes_publication_and_binary_nonreads(tmp_path, manifest, mode, expected):
    module = tmp_path / "preprocessing/dataset_manifest.py"
    module.parent.mkdir()
    module.write_bytes((ROOT / "preprocessing/dataset_manifest.py").read_bytes())
    if mode == "findings":
        manifest["records"][2]["exposure"]["preprocessing"] = "yes"
    if mode == "invalid":
        manifest["records"][2]["age"]["value"] = True
    source = tmp_path / "input.json"
    source.write_bytes(data._encode(manifest))
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(module),
            "--manifest",
            "input.json",
            "--sha256",
            hashlib.sha256(source.read_bytes()).hexdigest(),
            "--output-dir",
            "output/research/cli",
        ],
        capture_output=True,
        cwd=tmp_path,
    )
    assert result.returncode == expected
    output = tmp_path / "output/research/cli"
    if expected == 2:
        assert not output.exists() and json.loads(result.stderr)["status"] == "invalid_input"
    else:
        report = json.loads((output / "audit.json").read_bytes())
        assert report["summary"]["records"] == 3
        assert all(report[k] is False for k in data.FLAGS)
        assert not (tmp_path / "data").exists()
        assert json.loads((output / "manifest.json").read_bytes()) == manifest
