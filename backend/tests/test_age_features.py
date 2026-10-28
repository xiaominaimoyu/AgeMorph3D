"""Research feature integrity and file boundaries, without models or image fixtures."""

import copy
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "preprocessing" / "age_features.py"
_SPEC = importlib.util.spec_from_file_location("age_features", _PATH)
features = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(features)


def pin(path, payload=b"unread historical binary"):
    return {"path": path, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def json_bytes(value):
    return json.dumps(value, allow_nan=False).encode()


@pytest.fixture
def study():
    protocol = {
        "protocol_id": "synthetic-n0",
        "source_age_policy": "unknown_stays_null",
        "expected_adult_images": 8,
        "expected_adult_identities": 4,
        "grouping": {
            "seed": "fixture",
            "development_subject_ids": ["001"],
            "calibration_identity_count": 2,
        },
    }
    others = sorted(
        ["002", "003", "004"], key=lambda s: hashlib.sha256(f"fixture:{s}".encode()).hexdigest()
    )
    groups = {
        s: "development"
        if s == "001"
        else "calibration_research"
        if s in others[:2]
        else "evaluation_research_holdout"
        for s in ("001", "002", "003", "004")
    }
    flags = {
        "schema_version": 1,
        "protocol_id": "synthetic-n0",
        "research_only": True,
        "training_use": False,
        "service_ready": False,
        "g3_complete": False,
        "independent_external_evaluation": False,
        "years_calibrated": False,
    }
    dataset = {"license": {"status": "research-only-unresolved"}}
    model_docs, old_models = {}, {}
    for role, backend, artifact_roles in (
        ("detector", "yolov5_face_onnx", ["detector"]),
        ("reconstructor", "3ddfa_v2_onnx", ["regressor", "bfm", "param_stats"]),
    ):
        items = [
            dict(path=f"{r}.npz", sha256=str(i + 1) * 64, size_bytes=123, role=r)
            for i, r in enumerate(artifact_roles)
        ]
        model = {
            "model_id": role,
            "backend": backend,
            "artifacts": items,
            "license_status": "unresolved",
        }
        mp = pin(f"data/models/{role}.json", json_bytes(model))
        model_docs[role] = model
        old_models[role] = {
            "model_id": role,
            "backend": backend,
            "manifest": mp,
            "manifest_sha256": mp["sha256"],
            "artifacts": [
                dict(path=f"data/models/{i['path']}", sha256=i["sha256"], bytes=i["size_bytes"])
                for i in items
            ],
        }
    manifest = {
        **flags,
        "identities": [
            dict(
                subject_id=s,
                group=g,
                historical_preprocessing_exposed=True,
                previously_viewed=s == "001",
            )
            for s, g in groups.items()
        ],
        "adult_images": [],
    }
    fits = []
    for s, group in groups.items():
        for age in (25, 35):
            image = dict(
                pin(f"data/images/{s}A{age}.JPG", f"{s}:{age}".encode()),
                subject_id=s,
                source_age=age,
                group=group,
            )
            manifest["adult_images"].append(image)
            if group != "calibration_research":
                continue
            frame = {
                "source_center": [1, 2, 3],
                "source_to_canonical_uniform_scale": 0.01,
                "normalization_reference": "unchanged_source_mesh",
            }
            fits.append(
                {
                    "sample_id": f"fgnet-{s}a{age}",
                    "subject_id": s,
                    "source_age": age,
                    "data_group": group,
                    "role": "original",
                    "input": pin(image["path"], f"{s}:{age}".encode()),
                    "status": "ok",
                    "error_code": None,
                    "topology_sha256": "a" * 64,
                    "vertex_count": 12,
                    "shape": list(range(40)),
                    "expr": list(range(10)),
                    "projection": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3]],
                    "roi": [0, 0, 100, 100],
                    "canonical_frame": frame,
                    "source_canonical_frame": copy.deepcopy(frame),
                    "projection_semantics": features.PROJECTION,
                    "fit_artifact": pin(f"output/old/{s}a{age}.npz"),
                }
            )
    # Preserve an actual failed request alongside successes; no fake feature row.
    fits[1] = {
        k: fits[1][k]
        for k in ("sample_id", "subject_id", "source_age", "data_group", "role", "input")
    }
    fits[1].update(status="failed", error_code="NO_FACE", failure_stage="detection")
    report = {
        **flags,
        "study": "calibration",
        "technical_execution": "passed",
        "models": old_models,
        "units": "source canonical display units, not metric or calibrated years",
        "fit_records": fits,
        "expression_basis": {
            "asset": old_models["reconstructor"]["artifacts"][1],
            "shape": [36, 10],
        },
        "topology_artifact": pin("output/old/topology.npz"),
        "summary": {
            "requested_images": len(fits),
            "fit_statuses": dict(Counter(r["status"] for r in fits)),
        },
    }
    freeze = {
        "protocol_id": "synthetic-n0",
        "before_new_control_inference": True,
        "identity_groups": groups,
    }
    return [report, manifest, freeze, protocol, dataset, model_docs]


def persist(root, study):
    report, manifest, freeze, protocol, dataset, models = copy.deepcopy(study)

    def save(path, obj):
        payload = json_bytes(obj)
        dst = root / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(payload)
        return pin(path, payload)

    proto_pin = save("docs/protocol.json", protocol)
    dataset_pin = save("data/dataset.json", dataset)
    freeze["inputs"] = {p["path"]: p["sha256"] for p in (proto_pin, dataset_pin)}
    freeze_pin = save("output/old/freeze.json", freeze)
    manifest["inputs"] = {
        "protocol": proto_pin,
        "dataset_manifest": dataset_pin,
        "pre_inference_freeze": freeze_pin,
    }
    n0_pin = save("output/old/n0.json", manifest)
    for role, doc in models.items():
        saved = save(report["models"][role]["manifest"]["path"], doc)
        assert saved == report["models"][role]["manifest"]
    report["inputs"] = {"protocol_manifest": n0_pin, "pre_inference_freeze": freeze_pin}
    rp = save("output/old/report.json", report)
    return rp


def test_dataset_retains_failures_indices_groups_and_detaches_mutable_data(study):
    result = features.build_feature_dataset(*study)
    assert result["summary"] == {
        "requested": 4,
        "valid": 3,
        "failed": 1,
        "identities": 2,
        "failure_codes": {"NO_FACE": 1},
    }
    assert len(result["records"]) == 4 and len(result["features"]["shape"]) == 3
    assert all(r["group"] == "calibration_research" for r in result["records"])
    for i, r in enumerate(result["records"]):
        j = r["feature_row_index"]
        if r["fit_status"] == "failed":
            assert j is None and r["error_code"] == "NO_FACE"
        else:
            assert result["features"]["record_indices"][j] == i
    assert result["records"][0]["exposure_history"] == {
        "historical_preprocessing_exposed": True,
        "n0_previously_viewed": False,
        "subsequent_research_calibration_exposed": True,
    }
    assert result["binding"]["binary_verification"] == "historical_declarations_unread"
    for key in (
        "training_use",
        "production_eligible",
        "service_ready",
        "g3_complete",
        "years_calibrated",
        "independent_external_evaluation",
    ):
        assert result[key] is False
    result["features"]["shape"][0][0] = 999
    assert study[0]["fit_records"][0]["shape"][0] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s[0]["fit_records"].pop(),
        lambda s: s[0]["fit_records"].append(copy.deepcopy(s[0]["fit_records"][0])),
        lambda s: s[0]["fit_records"][0].update(role="sam_generated"),
        lambda s: s[0]["fit_records"][0].update(target_age=45),
        lambda s: s[0]["fit_records"][0].update(data_group="development"),
        lambda s: s[0]["fit_records"][0].update(source_age=True),
        lambda s: s[0]["fit_records"][0].update(source_age=26),
        lambda s: s[0]["fit_records"][0]["input"].update(sha256="f" * 64),
        lambda s: s[0]["fit_records"][-1].update(topology_sha256="b" * 64),
        lambda s: s[0]["fit_records"][0].update(vertex_count=13),
        lambda s: s[0]["fit_records"][0].update(shape=[0] * 39),
        lambda s: s[0]["fit_records"][0]["shape"].__setitem__(0, float("nan")),
        lambda s: s[0]["fit_records"][0]["expr"].__setitem__(0, True),
        lambda s: s[0]["fit_records"][0].update(projection=[[0] * 4] * 2),
        lambda s: s[0]["fit_records"][0].update(roi=[1, 1, 0, 0]),
        lambda s: s[0]["fit_records"][0]["canonical_frame"].update(
            source_to_canonical_uniform_scale=0
        ),
        lambda s: s[0]["fit_records"][0].update(projection_semantics="canonical"),
        lambda s: s[0]["fit_records"][1].update(error_code=None),
        lambda s: s[0]["expression_basis"]["asset"].update(sha256="f" * 64),
        lambda s: s[5]["reconstructor"]["artifacts"][0].update(sha256="f" * 64),
        lambda s: s[0]["summary"].update(requested_images=3),
        lambda s: s[0].update(study="longitudinal"),
        lambda s: s[0].update(training_use=True),
        lambda s: s[1].update(independent_external_evaluation=True),
        lambda s: s[2]["identity_groups"].update({next(iter(s[2]["identity_groups"])): "test"}),
        lambda s: s[1]["adult_images"][0].update(group="calibration_research"),
        lambda s: s[1]["adult_images"][-1].update(sha256=s[1]["adult_images"][0]["sha256"]),
    ],
)
def test_conflicting_or_incomplete_study_is_rejected(study, mutation):
    mutation(study)
    with pytest.raises(ValueError):
        features.build_feature_dataset(*study)


@pytest.mark.parametrize(
    "kind,value,kwargs",
    [
        ("unknown", 30, {}),
        ("exact", None, {}),
        ("exact", True, {}),
        ("exact", float("inf"), {}),
        ("exact", 19, {}),
        ("exact", 71, {}),
        ("interval", 45, {"lower": 40, "upper": 50}),
        ("interval", None, {"lower": 50, "upper": 40}),
        ("exact", 30, {"lower": 20}),
        ("unknown", None, {"upper": 70}),
    ],
)
def test_age_labels_reject_imputation_and_invalid_values(kind, value, kwargs):
    with pytest.raises(ValueError):
        features.research_age_label(kind, value, **kwargs)


def test_unknown_and_interval_do_not_manufacture_exact_labels():
    assert features.research_age_label("unknown")["value"] is None
    interval = features.research_age_label("interval", lower=40, upper=50)
    assert interval == {"kind": "interval", "value": None, "lower": 40, "upper": 50}
    assert features.research_age_label("exact", 42.5)["value"] == 42.5


def test_cli_export_reads_only_bound_json_and_refuses_existing_output(tmp_path, study, monkeypatch):
    rp = persist(tmp_path, study)
    opened = []
    original = Path.open

    def track(path, mode="r", *args, **kwargs):
        if "r" in mode:
            opened.append(path)
            assert path.suffix == ".json"
        return original(path, mode, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(Path, "open", track)
        result = features.export_dataset(tmp_path, rp["path"], rp["sha256"], "output/new")
    assert len(set(opened)) == 7
    saved = json.loads((tmp_path / result["path"]).read_bytes())
    assert len(saved["verified_json_inputs"]) == 7
    assert result["sha256"] == hashlib.sha256((tmp_path / result["path"]).read_bytes()).hexdigest()
    assert (
        features.main(
            [
                "--root",
                str(tmp_path),
                "--report",
                rp["path"],
                "--report-sha256",
                rp["sha256"],
                "--output-dir",
                "output/new",
            ]
        )
        == 2
    )


@pytest.mark.parametrize(
    "output",
    [
        "../escape",
        "preprocessing/new",
        "output",
        "data",
        "output/../../escape",
        "D:/escape",
        "output\\new",
    ],
)
def test_output_paths_do_not_escape_or_target_source(tmp_path, study, output):
    rp = persist(tmp_path, study)
    with pytest.raises(ValueError):
        features.export_dataset(tmp_path, rp["path"], rp["sha256"], output)


def test_input_tampering_refuses_before_output_creation(tmp_path, study):
    rp = persist(tmp_path, study)
    (tmp_path / "docs/protocol.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="fingerprint"):
        features.export_dataset(tmp_path, rp["path"], rp["sha256"], "output/new")
    assert not (tmp_path / "output/new").exists()


def test_final_input_change_removes_partial_result(tmp_path, study, monkeypatch):
    rp = persist(tmp_path, study)
    original = features._JsonInputs.recheck
    calls = 0

    def change(inputs):
        nonlocal calls
        calls += 1
        if calls == 2:
            (tmp_path / "data/dataset.json").write_bytes(b"{}")
        original(inputs)

    monkeypatch.setattr(features._JsonInputs, "recheck", change)
    with pytest.raises(ValueError, match="fingerprint"):
        features.export_dataset(tmp_path, rp["path"], rp["sha256"], "output/new")
    assert calls == 2 and not (tmp_path / "output/new").exists()


def test_metadata_size_duplicate_keys_and_report_hash_are_checked(tmp_path, study):
    rp = persist(tmp_path, study)
    with pytest.raises(ValueError, match="fingerprint"):
        features.export_dataset(tmp_path, rp["path"], "0" * 64, "output/new")
    path = tmp_path / "duplicate.json"
    payload = b'{"a": 1, "a": 2}'
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="Duplicate"):
        features._JsonInputs(tmp_path).read(pin("duplicate.json", payload))
    with pytest.raises(ValueError, match="bounded"):
        features._JsonInputs(tmp_path).read(
            dict(pin("duplicate.json"), bytes=features.MAX_JSON_BYTES + 1)
        )
