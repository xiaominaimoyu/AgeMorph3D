"""Synthetic cross-domain reference checks; no photographs or models are opened."""

import copy
import hashlib
import importlib.util
import json
import math
import random
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "render_identity_reference_probe", _ROOT / "tools/render_identity_reference_probe.py"
)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)
CONFIG = "MASK/front/black"


def pair(left, right, score, config=CONFIG):
    positive = left == right
    return {
        "config_id": config,
        "category": "positive" if positive else "different_identity_render_photo",
        "unit": left if positive else f"render:{left}/photo:{right}",
        "subjects": [left] if positive else [left, right],
        "render_subject": left,
        "photo_subject": right,
        "score": score,
    }


def own_summary(rows, subjects=None, threshold=0.5, config=CONFIG):
    result = probe.summarize_pairs(rows, subjects or ["A", "B"], threshold)
    return next(row for row in result if row["config_id"] == config)


def encoded(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def test_threshold_equality_accepts_and_negative_directions_remain_separate():
    rows = [pair("A", "A", 0.5), pair("B", "B", 0.49), pair("A", "B", 0.5), pair("B", "A", 0.49)]
    result = own_summary(rows)
    assert result["positive"]["false_decisions"] == 1
    assert result["negative"]["false_decisions"] == 1
    assert result["positive"]["conditional_error_rate"] == 0.5
    assert result["negative"]["conditional_error_rate"] == 0.5
    assert len(result["negative"]["units"]) == 2
    assert {tuple(unit["subjects"]) for unit in result["negative"]["units"]} == {
        ("A", "B"),
        ("B", "A"),
    }


def test_missing_scores_remain_requested_and_do_not_become_correct_decisions():
    rows = [pair("A", "A", 0.8), pair("B", "B", None), pair("A", "B", None), pair("B", "A", 0.9)]
    result = own_summary(rows)
    p, n = result["positive"], result["negative"]
    assert (p["requested"], p["scored"], p["failed"]) == (2, 1, 1)
    assert p["conditional_error_rate"] == p["requested_error_lower"] == 0
    assert p["requested_error_upper"] == 0.5
    assert (n["requested"], n["scored"], n["failed"]) == (2, 1, 1)
    assert n["conditional_error_rate"] == 1
    assert n["requested_error_lower"] == 0.5 and n["requested_error_upper"] == 1


def test_all_failed_classes_have_null_conditional_rates_and_zero_one_bounds():
    result = own_summary([pair(a, b, None) for a in ["A", "B"] for b in ["A", "B"]])
    for category in ["positive", "negative"]:
        assert result[category]["conditional_error_rate"] is None
        assert result[category]["requested_error_lower"] == 0
        assert result[category]["requested_error_upper"] == 1
    for name in ["conditional_fnmr", "conditional_fmr"]:
        metric = result["bootstrap"]["metrics"][name]
        assert metric["valid_replicates"] == 0 and metric["null_replicates"] == 1000
        assert metric["percentile_025"] is metric["percentile_975"] is None
        assert (
            metric["replicate_values_sha256"] == hashlib.sha256(encoded([None] * 1000)).hexdigest()
        )


def test_configurations_do_not_pool_failures_or_scores():
    rows = [pair(a, b, 0.8 if a == b else 0.1) for a in ["A", "B"] for b in ["A", "B"]]
    rows += [pair(a, b, None, "BLEND/side/white") for a in ["A", "B"] for b in ["A", "B"]]
    result = probe.summarize_pairs(rows, ["A", "B"], 0.5)
    assert len(result) == 8
    frontal = next(row for row in result if row["config_id"] == CONFIG)
    side = next(row for row in result if row["config_id"] == "BLEND/side/white")
    assert frontal["positive"]["conditional_error_rate"] == 0
    assert side["positive"]["conditional_error_rate"] is None
    assert frontal["positive"]["requested"] == side["positive"]["requested"] == 2


def test_full_eight_identity_matrix_preserves_all_512_directed_requests():
    subjects = [f"S{index}" for index in range(8)]
    rows = [
        pair(left, right, 1.0 if left == right else 0.0, config)
        for config in probe.CONFIGURATIONS
        for left in subjects
        for right in subjects
    ]
    assert len(rows) == 512
    assert sum(row["category"] == "positive" for row in rows) == 64
    assert sum(row["category"] != "positive" for row in rows) == 448
    summaries = probe.summarize_pairs(rows, subjects, 0.5)
    assert len(summaries) == 8
    for summary in summaries:
        assert summary["positive"]["requested"] == summary["positive"]["scored"] == 8
        assert summary["negative"]["requested"] == summary["negative"]["scored"] == 56
        assert summary["positive"]["false_decisions"] == 0
        assert summary["negative"]["false_decisions"] == 0
    assert sum(s["positive"]["requested"] + s["negative"]["requested"] for s in summaries) == 512


def test_shared_identity_draws_include_failed_identities_and_never_invent_impostors():
    rows = [pair("A", "A", 0.4), pair("B", "B", None), pair("A", "B", 0.6), pair("B", "A", 0.2)]
    summary = own_summary(rows)
    boot = summary["bootstrap"]
    assert boot["subjects"] == ["A", "B"]
    key = "reference/" + CONFIG
    seed = 20261027 + int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
    assert boot["seed"] == seed and boot["replicates"] == 1000
    rng = random.Random(seed)
    values = {
        name: []
        for name in [
            "conditional_fnmr",
            "conditional_fmr",
            "requested_fnmr_lower",
            "requested_fnmr_upper",
            "requested_fmr_lower",
            "requested_fmr_upper",
        ]
    }
    for _ in range(1000):
        counts = Counter(["A", "B"][rng.randrange(2)] for _ in range(2))
        a, b = counts["A"], counts["B"]
        # Distinct identities alone make impostor units; two copies of A do not.
        negative = 0.5 if a * b else None
        expected = {
            "conditional_fnmr": 1.0 if a else None,
            "conditional_fmr": negative,
            "requested_fnmr_lower": a / 2,
            "requested_fnmr_upper": 1.0,
            "requested_fmr_lower": negative,
            "requested_fmr_upper": negative,
        }
        for name, value in expected.items():
            values[name].append(value)
    for name, repeats in values.items():
        metric = boot["metrics"][name]
        valid = [value for value in repeats if value is not None]
        assert metric["valid_replicates"] == len(valid)
        assert metric["null_replicates"] == 1000 - len(valid)
        assert metric["replicate_values_sha256"] == hashlib.sha256(encoded(repeats)).hexdigest()
        assert metric["percentile_025"] == min(valid)
        assert metric["percentile_975"] == max(valid)
    assert 0 < boot["metrics"]["conditional_fmr"]["null_replicates"] < 1000
    assert own_summary(list(reversed(rows))) == summary


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}'])
def test_invalid_nonfinite_or_duplicate_json_is_rejected(raw):
    with pytest.raises(ValueError):
        probe._json(raw)


def pin(name, raw):
    return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n").encode()


def test_input_budget_rejects_before_opening_an_oversized_payload(tmp_path, monkeypatch):
    declared = {"path": "not-opened.json", "bytes": 8 * 1024**2 + 1, "sha256": "0" * 64}
    opened = []
    original = Path.open

    def monitor(path, *args, **kwargs):
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", monitor)
    with pytest.raises(ValueError):
        probe.Inputs(tmp_path, [declared])
    assert not opened


def vector(index):
    return [float(position == index) for position in range(128)]


def source_pin(name, suffix="JPG"):
    return pin(f"never-opened/{name}.{suffix}", name.encode())


def old_flags():
    return {
        "research_only": True,
        **dict.fromkeys(
            [
                "new_model_inference",
                "age_quality_accepted",
                "years_calibrated",
                "identity_quality_accepted",
                "independent_evaluation",
                "training_overlap_excluded",
                "legal_permission_established",
                "service_ready",
                "production_enabled",
                "g3_complete",
                "images_or_crops_written",
                "holdout_embeddings_extracted",
                "holdout_predictions_extracted",
                "demographic_classification_exported",
                "production_source_reset_accepted",
                "rendered_continuity_accepted",
                "age_texture_quality_accepted",
                "holdout_age_results_opened",
            ],
            False,
        ),
    }


def persist(study, *, overrides=None):
    root, docs = study["args"].root, study["documents"]
    overrides = overrides or {}
    roles = {}

    def write(role):
        raw = overrides.get(role, json_bytes(docs[role]))
        name = "frozen/" + role + ".json"
        (root / name).write_bytes(raw)
        roles[role] = pin(name, raw)

    for role in ["protocol", "n0_manifest", "photo_report"]:
        write(role)
    docs["reference_report"]["roles"] = {
        "identity_report": roles["photo_report"],
        "n0_manifest": roles["n0_manifest"],
    }
    docs["reference_report"]["inputs"] = [roles["photo_report"], roles["n0_manifest"]]
    write("reference_report")
    docs["reference_verification"]["artifacts"] = [roles["reference_report"]]
    docs["reference_verification"]["inputs"] = [roles["photo_report"], roles["n0_manifest"]]
    write("reference_verification")
    docs["source_reset_report"]["inputs"] = {"protocol_manifest": roles["n0_manifest"]}
    write("source_reset_report")
    docs["capture_report"]["inputs"] = [roles["n0_manifest"], roles["source_reset_report"]]
    write("capture_report")
    docs["render_report"]["inputs"] = [
        roles[k] for k in ["n0_manifest", "source_reset_report", "capture_report"]
    ]
    write("render_report")
    docs["render_verification"]["artifacts"] = [roles["render_report"], roles["capture_report"]]
    write("render_verification")
    roles = {role: roles[role] for role in probe.ROLES}
    plan = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL_ID,
        "runtime": probe.runtime_fingerprint(),
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
    config_ids = [
        f"{material}/{view}/{background}"
        for material in ["MASK", "BLEND"]
        for view in ["front", "side"]
        for background in ["black", "white"]
    ]
    protocol = json.loads((_ROOT / "docs/render-identity-reference-v1.json").read_bytes())
    protocol["reference"]["threshold"] = 0.5
    protocol["cohort"]["source_count"] = 2
    protocol["cohort"]["external_source_count"] = 1
    protocol["cohort"]["sam_asset_count"] = 1
    adults, bridges, reset, photos = [], [], [], []
    for index, subject in enumerate(["A", "B", "external-X"]):
        label = 25 + index * 5 if index < 2 else None
        source = source_pin("photo-" + subject)
        bridge = {
            "sample_id": "source-" + subject,
            "subject_id": subject,
            "group": "development",
            "source": source,
            "source_status": "passed",
            "source_age": {
                "value": label,
                "method": "dataset_filename" if label is not None else "unknown",
                "independently_verified": False,
            },
        }
        bridges.append(bridge)
        if label is not None:
            adults.append(
                {**source, "subject_id": subject, "group": "development", "source_age": label}
            )
        artifacts = {
            kind: source_pin("asset-" + subject, suffix)
            for kind, suffix in [("glb", "glb"), ("atlas", "png")]
        }
        reset.append(
            {
                "sample_id": bridge["sample_id"],
                "subject_id": subject,
                "group": "development",
                "input": source,
                "status": "ok",
                "reset_status": "passed",
                "label_source_age": label,
                "research_source_age": copy.deepcopy(bridge["source_age"]),
                "source_age": {"value": None, "method": "unknown", "calibration_id": None},
                "artifacts": artifacts,
                "source_frame": {"version": "synthetic-static"},
            }
        )
        check = {**source, "verification": "verified", "matches_declared": True}
        photos.append(
            {
                "image_id": index,
                "source": source,
                "subject_id": subject,
                "group": "development",
                "source_age_label": label,
                "roles": ["original", "source"] if label is not None else ["source"],
                "status": "ok",
                "embedding": vector(index),
                "source_changed": False,
                "initial_source_check": check,
                "final_source_check": copy.deepcopy(check),
            }
        )
    held = {
        **source_pin("photo-held"),
        "subject_id": "H",
        "group": "evaluation_research_holdout",
        "source_age": 40,
    }
    adults.append(held)
    n0 = {
        "protocol_id": "agemorph3d-age-research-v1",
        "research_only": True,
        "training_use": False,
        "service_ready": False,
        "g3_complete": False,
        "identities": [{"subject_id": s, "group": "development"} for s in ["A", "B"]]
        + [{"subject_id": "H", "group": "evaluation_research_holdout"}],
        "adult_images": adults,
        "bridge_cases": bridges,
    }
    models = [
        source_pin("face_recognition_sface_2021dec", "onnx"),
        source_pin("face_detection_yunet_2023mar", "onnx"),
    ]
    assets = []
    for row in reset:
        assets.append(
            {
                "asset_id": row["sample_id"] + "--original",
                "source_id": row["sample_id"],
                "sample_id": None,
                "role": "original_static_3d",
                "source_age_label": row["label_source_age"],
                "target_age": None,
                "category": "baseline",
                "status": "captured",
                "glb": row["artifacts"]["glb"],
                "atlas": row["artifacts"]["atlas"],
                "source_frame": row["source_frame"],
                "expected_geometry": {"positions": "a" * 64},
            }
        )
    assets.append(
        {
            "asset_id": "source-A--sam-045",
            "source_id": "source-A",
            "sample_id": "source-A--sam-045",
            "role": "sam_texture_static_3d",
            "source_age_label": 25,
            "target_age": 45,
            "category": "other_condition",
            "status": "captured",
            "glb": source_pin("generated", "glb"),
            "atlas": source_pin("generated", "png"),
            "source_frame": {"version": "synthetic-static"},
            "expected_geometry": {"positions": "a" * 64},
        }
    )
    captures, renders = [], []
    for asset_index, asset in enumerate(assets):
        for config in config_ids:
            image = source_pin(asset["asset_id"] + "-" + config.replace("/", "-"), "png")
            material, view, background = config.split("/")
            frame = {
                **{
                    key: asset[key]
                    for key in [
                        "asset_id",
                        "source_id",
                        "sample_id",
                        "role",
                        "source_age_label",
                        "target_age",
                        "category",
                    ]
                },
                "frame_id": asset["asset_id"] + "::" + config,
                "config_id": config,
                "configuration": {
                    "material_mode": material,
                    "view": view,
                    "background": background,
                },
                "status": "ok",
                "image": image,
                "observed": {"geometry": asset["expected_geometry"], "png_sha256": image["sha256"]},
            }
            captures.append(frame)
            good = not (asset_index == 0 and view == "side" and background == "black")
            check = {**image, "verification": "verified", "matches_declared": True}
            renders.append(
                {
                    **copy.deepcopy(frame),
                    "image_id": len(renders),
                    "source": image,
                    "status": "ok" if good else "NO_FACE",
                    "embedding": vector(asset_index) if good else None,
                    "source_changed": False,
                    "initial_source_check": check,
                    "final_source_check": copy.deepcopy(check),
                }
            )
    flags = old_flags()
    photo_report = {
        "protocol_id": "agemorph3d-identity-evaluator-v1",
        **flags,
        "quality_threshold": None,
        "integrity_status": "passed",
        "models_closed": True,
        "records": photos,
        "environment": {"runtime": "synthetic-only"},
        "model_pins": models,
        "image_counts": {"requested": len(photos), "successful": len(photos), "failed": 0},
    }
    capture_report = {
        "protocol_id": "agemorph3d-render-domain-v1",
        **flags,
        "status": "passed",
        "quality_threshold": None,
        "assets": assets,
        "frames": captures,
        "input_integrity": "passed",
        "frame_counts": {"requested": len(captures), "captured": len(captures), "failed": 0},
        "requested_frames": len(captures),
        "requested_pairs": 8,
    }
    successful = sum(row["status"] == "ok" for row in renders)
    render_report = {
        "protocol_id": "agemorph3d-render-domain-v1",
        "stage": "identity",
        **flags,
        "quality_threshold": None,
        "integrity_status": "passed",
        "execution_status": "completed_with_failures",
        "models_closed": True,
        "frames": renders,
        "environment": photo_report["environment"],
        "model_pins": models,
        "frame_counts": {
            "requested": len(renders),
            "successful": successful,
            "failed": len(renders) - successful,
        },
        "cohort_counts": {
            "original_assets": 3,
            "sam_assets": 1,
            "source_age_labels_known": 2,
            "source_age_labels_unknown": 1,
            "unique_frames": len(renders),
            "paired_comparisons": 8,
        },
    }
    reference = {
        "protocol_id": "agemorph3d-identity-calibration-v1",
        **flags,
        "development_candidate_threshold": 0.5,
        "development_selection": {"threshold": 0.5},
        "quality_threshold": None,
        "calibration_curve_computed": False,
        "calibration_threshold_retuned": False,
        "integrity": {
            "all_inputs_unchanged": True,
            "plan_unchanged": True,
            "runtime_unchanged": True,
        },
    }
    study = {
        "args": SimpleNamespace(
            root=root, study_plan="frozen/study-plan.json", output_dir="output/research/result"
        ),
        "documents": {
            "protocol": protocol,
            "n0_manifest": n0,
            "photo_report": photo_report,
            "reference_report": reference,
            "reference_verification": {"status": "passed", "quality_threshold": None, **flags},
            "render_report": render_report,
            "render_verification": {"status": "passed", **flags},
            "capture_report": capture_report,
            "source_reset_report": {
                "protocol_id": "agemorph3d-source-reset-v1",
                **flags,
                "records": reset,
            },
        },
    }
    return persist(study)


@pytest.fixture
def study(tmp_path):
    return make_study(tmp_path)


def test_complete_synthetic_run_only_reads_its_closed_metadata_and_sources(study, monkeypatch):
    root = study["args"].root
    allowed = {(root / pin["path"]).resolve() for pin in study["plan"]["inputs"]}
    allowed.add((root / study["args"].study_plan).resolve())
    original = Path.open
    reads = []

    def guard(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if "r" in mode and root in path.resolve().parents:
            reads.append(path.resolve())
            assert path.resolve() in allowed
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    report = probe.run(study["args"])
    assert report["diagnostic_reference_threshold"] == 0.5
    assert report["quality_threshold"] is None
    assert all(report[key] is value for key, value in probe.FLAGS.items())
    assert len(report["pairs"]) == 32 and len(report["configurations"]) == 8
    assert report["subjects"] == ["A", "B"]
    assert report["accounting"]["known_original_frames"] == 16
    assert report["accounting"]["known_original_failed"] == 2
    assert report["accounting"]["pairs_scored"] == 28
    assert report["accounting"]["pairs_failed"] == 4
    assert (
        report["accounting"]["positive_requested"]
        == report["accounting"]["negative_requested"]
        == 16
    )
    assert report["accounting"]["excluded_external_original_frames"] == 8
    assert report["accounting"]["excluded_sam_frames"] == 8
    assert not any("never-opened" in str(path) for path in reads)
    assert (root / study["args"].output_dir / "report.json").is_file()


def test_main_accepts_argparse_path_and_rejects_parent_or_absolute_output(study, capsys):
    args = study["args"]
    common = ["--root", str(args.root), "--study-plan", str(args.study_plan), "--output-dir"]
    assert probe.main([*common, "output/research/main-result"]) == 0
    assert json.loads(capsys.readouterr().out)["diagnostic_reference_threshold"] == 0.5
    assert probe.main([*common, "../escaped-result"]) == 1
    assert probe.main([*common, str(args.root / "output/research/absolute-result")]) == 1
    assert not (args.root / "output/research/absolute-result").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "reference-value",
        "reference-qualified",
        "photo-qualified",
        "render-qualified",
        "photo-role",
        "photo-duplicate",
        "photo-feature-size",
        "photo-feature-zero",
        "photo-feature-bool",
        "photo-feature-huge-integer",
        "model-version",
        "environment",
        "n0-cross-group",
        "n0-held-hash",
        "known-source-group",
        "known-source-pin",
        "duplicate-source-identity",
        "api-age",
        "asset-glb",
        "capture-observation",
        "capture-target-age",
        "duplicate-capture",
        "missing-capture",
        "render-source-change",
        "render-failure-feature",
        "render-source-check",
    ],
)
def test_semantic_counterexamples_reject_even_after_their_metadata_are_refrozen(study, mutation):
    docs = study["documents"]
    photo = docs["photo_report"]["records"][0]
    frame = docs["render_report"]["frames"][0]
    if mutation == "reference-value":
        docs["reference_report"]["development_candidate_threshold"] = math.nextafter(0.5, math.inf)
    elif mutation == "reference-qualified":
        docs["reference_report"]["identity_quality_accepted"] = True
    elif mutation == "photo-qualified":
        docs["photo_report"]["identity_quality_accepted"] = True
    elif mutation == "render-qualified":
        docs["render_report"]["production_enabled"] = True
    elif mutation == "photo-role":
        photo["roles"] = ["generated"]
    elif mutation == "photo-duplicate":
        docs["photo_report"]["records"].append(copy.deepcopy(photo))
    elif mutation == "photo-feature-size":
        photo["embedding"] = photo["embedding"][:-1]
    elif mutation == "photo-feature-zero":
        photo["embedding"] = [0.0] * 128
    elif mutation == "photo-feature-bool":
        photo["embedding"][0] = True
    elif mutation == "photo-feature-huge-integer":
        photo["embedding"][0] = 10**1000
    elif mutation == "model-version":
        docs["render_report"]["model_pins"] = copy.deepcopy(docs["render_report"]["model_pins"])
        docs["render_report"]["model_pins"][0]["sha256"] = "0" * 64
    elif mutation == "environment":
        docs["render_report"]["environment"] = {"runtime": "different-version"}
    elif mutation == "n0-cross-group":
        docs["n0_manifest"]["identities"][0]["group"] = "calibration_research"
    elif mutation == "n0-held-hash":
        docs["n0_manifest"]["adult_images"][-1]["sha256"] = docs["n0_manifest"]["adult_images"][0][
            "sha256"
        ]
    elif mutation == "known-source-group":
        docs["source_reset_report"]["records"][0]["group"] = "calibration_research"
    elif mutation == "known-source-pin":
        docs["source_reset_report"]["records"][0]["input"] = source_pin("wrong-photo")
    elif mutation == "duplicate-source-identity":
        docs["n0_manifest"]["bridge_cases"][1]["subject_id"] = "A"
        docs["source_reset_report"]["records"][1]["subject_id"] = "A"
    elif mutation == "api-age":
        docs["source_reset_report"]["records"][0]["source_age"] = {
            "value": 25,
            "method": "user",
            "calibration_id": None,
        }
    elif mutation == "asset-glb":
        docs["capture_report"]["assets"][0]["glb"] = source_pin("wrong-glb", "glb")
    elif mutation == "capture-observation":
        frame["observed"]["png_sha256"] = "0" * 64
    elif mutation == "capture-target-age":
        docs["capture_report"]["assets"][0]["target_age"] = 45
    elif mutation == "duplicate-capture":
        docs["capture_report"]["frames"].append(copy.deepcopy(docs["capture_report"]["frames"][0]))
    elif mutation == "missing-capture":
        del docs["capture_report"]["frames"][0]
    elif mutation == "render-source-change":
        frame["source_changed"] = True
    elif mutation == "render-failure-feature":
        frame["status"] = "NO_FACE"
    elif mutation == "render-source-check":
        frame["final_source_check"]["matches_declared"] = False
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])
    assert not (study["args"].root / study["args"].output_dir / "report.json").exists()


@pytest.mark.parametrize("where", ["excluded-photo", "excluded-render"])
def test_heldout_sha_alias_is_rejected_before_excluded_role_can_hide_it(study, where):
    docs = study["documents"]
    held = docs["n0_manifest"]["adult_images"][-1]
    alias = {key: held[key] for key in ["path", "bytes", "sha256"]}
    alias["path"] = "never-opened/alias-not-a-heldout-filename.png"
    check = {**alias, "verification": "verified", "matches_declared": True}
    if where == "excluded-photo":
        row = docs["photo_report"]["records"][-1]
        row["source"] = alias
        row["initial_source_check"] = check
        row["final_source_check"] = copy.deepcopy(check)
    else:
        row = docs["render_report"]["frames"][-1]
        row["image"] = row["source"] = alias
        row["initial_source_check"] = check
        row["final_source_check"] = copy.deepcopy(check)
        row["observed"]["png_sha256"] = alias["sha256"]
        capture = docs["capture_report"]["frames"][-1]
        capture["image"] = alias
        capture["observed"]["png_sha256"] = alias["sha256"]
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_a_failed_photo_keeps_its_full_render_pair_denominator(study):
    docs = study["documents"]
    photo = docs["photo_report"]["records"][0]
    photo["status"], photo["embedding"] = "NO_FACE", None
    docs["photo_report"]["image_counts"]["successful"] -= 1
    docs["photo_report"]["image_counts"]["failed"] += 1
    persist(study)
    result = probe.run(study["args"])
    assert result["accounting"]["pairs_requested"] == 32
    assert all(row["score"] is None for row in result["pairs"] if row["photo_subject"] == "A")


def test_existing_output_and_changed_python_runtime_are_rejected(study):
    probe.run(study["args"])
    with pytest.raises(ValueError):
        probe.run(study["args"])
    study["args"].output_dir = "output/research/other"
    study["plan"]["runtime"]["python"] = "different interpreter"
    (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_undeclared_extra_input_cannot_expand_the_metadata_read_set(study):
    study["plan"]["inputs"].append(pin("must-not-open.json", b"not declared"))
    (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    with pytest.raises(ValueError):
        probe.run(study["args"])


@pytest.mark.parametrize("source", [0, 2])
def test_loaded_cli_or_helper_cannot_be_replaced_by_a_new_file_pin(study, source):
    name = probe.SOURCES[source]
    path = study["args"].root / name
    raw = path.read_bytes() + b"\n# changed after load\n"
    path.write_bytes(raw)
    study["plan"]["inputs"] = [
        pin(name, raw) if item["path"] == name else item for item in study["plan"]["inputs"]
    ]
    (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_non_json_metadata_is_rejected_before_its_payload_is_opened(study, monkeypatch):
    original_pin = study["plan"]["roles"]["photo_report"]
    bad = pin("never-opened/photo.JPG", b"not JSON")
    study["plan"]["roles"]["photo_report"] = bad
    study["plan"]["inputs"] = [
        bad if item == original_pin else item for item in study["plan"]["inputs"]
    ]
    (study["args"].root / study["args"].study_plan).write_bytes(json_bytes(study["plan"]))
    original = Path.open

    def guard(path, *args, **kwargs):
        assert path.name != "photo.JPG"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    with pytest.raises(ValueError):
        probe.run(study["args"])


@pytest.mark.parametrize("phase", ["calculation", "serialization", "plan"])
def test_late_changes_do_not_publish_a_success_report(study, monkeypatch, phase):
    args = study["args"]
    target = args.root / study["plan"]["roles"]["render_report"]["path"]
    if phase == "serialization":
        serialize = probe.json.dumps

        def mutate(value, *a, **kw):
            result = serialize(value, *a, **kw)
            if isinstance(value, dict) and "configurations" in value and "pairs" in value:
                target.write_bytes(target.read_bytes() + b" ")
            return result

        monkeypatch.setattr(probe.json, "dumps", mutate)
    else:
        calculate = probe.summarize_pairs

        def mutate(*a, **kw):
            result = calculate(*a, **kw)
            changed = args.root / args.study_plan if phase == "plan" else target
            changed.write_bytes(changed.read_bytes() + b" ")
            return result

        monkeypatch.setattr(probe, "summarize_pairs", mutate)
    with pytest.raises(ValueError):
        probe.run(args)
    assert not (args.root / args.output_dir / "report.json").exists()


def test_original_source_frame_must_match_the_source_reset_record(study):
    study["documents"]["capture_report"]["assets"][0]["source_frame"] = {
        "version": "different-source-frame"
    }
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_identically_wrong_capture_and_render_observation_cannot_replace_the_image_pin(study):
    docs = study["documents"]
    capture = docs["capture_report"]["frames"][0]
    render = docs["render_report"]["frames"][0]
    original_pin = copy.deepcopy(capture["image"])
    capture["observed"]["png_sha256"] = "0" * 64
    render["observed"]["png_sha256"] = "0" * 64
    assert capture["image"] == render["image"] == render["source"] == original_pin
    assert render["initial_source_check"]["sha256"] == original_pin["sha256"]
    assert render["final_source_check"]["sha256"] == original_pin["sha256"]
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_external_original_cannot_disappear_by_being_relabelled_as_a_sam_asset(study):
    docs = study["documents"]
    asset = docs["capture_report"]["assets"][2]
    asset.update(role="sam_texture_static_3d", target_age=45, category="unknown_source_age")
    for frames in [docs["capture_report"]["frames"], docs["render_report"]["frames"]]:
        for row in frames:
            if row["asset_id"] == asset["asset_id"]:
                row.update(role=asset["role"], target_age=45, category=asset["category"])
    persist(study)
    with pytest.raises(ValueError):
        probe.run(study["args"])


def test_input_drift_at_the_pending_report_recheck_removes_only_own_partial_output(
    study, monkeypatch
):
    original = probe.Inputs.recheck
    count = 0
    args = study["args"]
    target = args.root / study["plan"]["roles"]["render_report"]["path"]

    def mutate_before_last_check(inputs):
        nonlocal count
        count += 1
        if count == 3:
            assert (args.root / args.output_dir / "pending-report.json").exists()
            target.write_bytes(target.read_bytes() + b" ")
        return original(inputs)

    monkeypatch.setattr(probe.Inputs, "recheck", mutate_before_last_check)
    with pytest.raises(ValueError):
        probe.run(args)
    assert count == 3
    assert not (args.root / args.output_dir).exists()


def test_large_model_references_are_valid_metadata_and_never_opened(study):
    docs = study["documents"]
    models = copy.deepcopy(docs["photo_report"]["model_pins"])
    models[0]["bytes"] = 38_696_353
    models[1]["bytes"] = 232_589
    docs["photo_report"]["model_pins"] = copy.deepcopy(models)
    docs["render_report"]["model_pins"] = copy.deepcopy(models)
    persist(study)
    result = probe.run(study["args"])
    assert result["accounting"]["pairs_requested"] == 32
    assert not any((study["args"].root / model["path"]).exists() for model in models)
