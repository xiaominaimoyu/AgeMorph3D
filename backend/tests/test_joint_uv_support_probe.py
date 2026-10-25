"""Synthetic support accounting and freeze counterexamples; no research arrays."""

import argparse
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "joint_uv_support_probe", _ROOT / "tools/joint_uv_support_probe.py"
)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def rgba(known):
    result = np.zeros((*known.shape, 4), np.uint8)
    result[known, 3] = 255
    result[known, :3] = [80, 90, 100]
    return result


def small_case():
    source = rgba(np.array([[True, True], [False, False]]))
    target = rgba(np.array([[True, False], [True, False]]))
    classes = np.array([[6, 5], [6, 2]], np.uint8)
    rc = np.array([[0, 0], [0, 1], [1, 0], [1, 1]], np.int32)
    bits = np.array([3, 1, 2, 0], np.uint8)
    return [source, target, classes, classes == 6, rc, bits]


def test_four_states_and_overlapping_target_regions_keep_separate_denominators():
    case = small_case()
    saved = [a.copy() for a in case]
    result = probe.joint_counts(*case)
    atlas = result["all_atlas"]
    assert [atlas["states"][state]["count"] for state in probe.STATES] == [1, 1, 1, 1]
    assert atlas["states"]["source_only"]["target_reasons"]["mask_rejected"] == 1
    assert atlas["source_only_fraction_of_source_known"] == 0.5
    assert atlas["source_only_fraction_of_region"] == 0.25
    assert result["eye_36_41"]["requested"] == result["eye_42_47"]["requested"] == 2
    assert result["eye_36_41"]["source_only_fraction_of_region"] == 0.5
    assert result["mouth_48_67"]["requested"] == 0
    assert result["mouth_48_67"]["source_only_fraction_of_source_known"] is None
    assert result["mouth_48_67"]["source_only_fraction_of_region"] is None
    for before, after in zip(saved, case, strict=True):
        assert np.array_equal(before, after)


@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("mutation", ["partial_alpha", "unknown_rgb"])
def test_partial_alpha_and_nonzero_unknown_are_rejected(side, mutation):
    case = small_case()
    if mutation == "partial_alpha":
        case[side][0, 0, 3] = 128
    else:
        case[side][1, 1, 0] = 1
    with pytest.raises(ValueError, match="binary|unknown"):
        probe.joint_counts(*case)


@pytest.mark.parametrize(
    "mutation", ["classes", "coverage", "duplicate_rc", "outside_rc", "missing_rc", "region_bit"]
)
def test_inconsistent_target_or_correspondence_is_rejected(mutation):
    case = small_case()
    if mutation == "classes":
        case[2][0, 0] = 7
    elif mutation == "coverage":
        case[3][0, 0] = False
    elif mutation == "duplicate_rc":
        case[4][0] = case[4][1]
    elif mutation == "outside_rc":
        case[4][0, 0] = 2
    elif mutation == "missing_rc":
        case[4], case[5] = case[4][1:], case[5][1:]
    else:
        case[5][0] = 16
    with pytest.raises(ValueError):
        probe.joint_counts(*case)


def test_conservative_delta_transfers_only_the_supported_joint_state():
    case = small_case()
    old = probe.joint_counts(*case)
    case[1][0, 1] = [80, 90, 100, 255]
    case[2][0, 1] = 6
    case[3][0, 1] = True
    new = probe.joint_counts(*case)
    delta = probe.count_deltas(old, new)["all_atlas"]["states"]
    assert delta["both_known"]["count"] == 1
    assert delta["source_only"]["count"] == -1
    assert delta["source_only"]["target_reasons"]["mask_rejected"] == -1
    assert delta["both_known"]["target_reasons"]["sampled"] == 1
    assert delta["target_only"]["count"] == delta["both_unknown"]["count"] == 0
    bad = copy.deepcopy(new)
    bad["all_atlas"]["source_known"] += 1
    with pytest.raises(ValueError, match="denominator"):
        probe.count_deltas(old, bad)


def npz(**arrays):
    output = io.BytesIO()
    np.savez_compressed(output, **arrays)
    return output.getvalue()


def trace_arrays():
    return {
        "texel_rows_columns": np.array([[0, 0], [0, 1]], np.int32),
        "face_owner": np.zeros(2, np.int32),
        "barycentric": np.ones((2, 3), np.float64) / 3,
        "target_xyz": np.zeros((2, 3), np.float64),
        "source_canonical_xyz": np.zeros((2, 3), np.float64),
        "region_bits": np.array([1, 2], np.uint8),
        "rejection_partition": np.array([1, 0], np.uint8),
    }


@pytest.mark.parametrize(
    "mutation",
    ["extra", "shape", "dtype", "nonfinite", "partition", "overflow", "barycentric", "owner"],
)
def test_bounded_trace_npz_rejects_wrong_members_and_headers(mutation):
    arrays = trace_arrays()
    if mutation == "extra":
        arrays["extra"] = np.zeros(1)
    elif mutation == "shape":
        arrays["target_xyz"] = np.zeros((3, 3), np.float64)
    elif mutation == "dtype":
        arrays["face_owner"] = arrays["face_owner"].astype(np.int64)
    elif mutation == "nonfinite":
        arrays["target_xyz"][0, 0] = np.nan
    elif mutation == "partition":
        arrays["rejection_partition"][0] = 4
    elif mutation == "barycentric":
        arrays["barycentric"][0, 0] = 0.9
    elif mutation == "owner":
        arrays["face_owner"][0] = 300000
    else:
        arrays["face_owner"] = np.zeros(65537, np.int32)
    with pytest.raises(ValueError):
        probe.trace_npz(npz(**arrays))


def test_bounded_trace_npz_preserves_expected_arrays():
    arrays = trace_arrays()
    actual = probe.trace_npz(npz(**arrays))
    assert actual.keys() == arrays.keys()
    for name, value in arrays.items():
        assert np.array_equal(actual[name], value)


def pin_file(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def json_bytes(data):
    return json.dumps(data, allow_nan=False).encode()


@pytest.fixture
def study(tmp_path, monkeypatch):
    root = tmp_path
    pins = []

    def put(name, data):
        pin = pin_file(root, name, data)
        pins.append(pin)
        return pin

    for name in probe.SOURCES:
        put(name, b"synthetic frozen source, never executed\n")
    # A temporary synthetic workspace does not execute its placeholder sources.
    monkeypatch.setattr(
        probe,
        "LOADED_CODE_SHA256",
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in probe.LOADED_CODE_SHA256
        },
    )
    put(".gitignore", b"output/\n")
    protocol = json.loads((_ROOT / "docs/joint-uv-support-v1.json").read_text(encoding="utf-8"))
    protocol_pin = put("protocol.json", json_bytes(protocol))
    unused = {"path": "unused/metadata-reference.npz", "bytes": 1, "sha256": "a" * 64}
    binding = {key: dict(unused) for key in ("uv", "generated_report", "protocol_manifest")}
    common = {
        "research_only": True,
        "g3_complete": False,
        "service_ready": False,
        "inputs": binding,
    }
    source_report = {**copy.deepcopy(common), "records": []}
    old_report = {**copy.deepcopy(common), "records": []}
    new_report = {**copy.deepcopy(common), "records": []}
    trace_report = {
        **copy.deepcopy(common),
        "protocol_id": probe.uv.PROTOCOL_ID,
        "classification_codes": probe.REASONS,
        "region_bit_order": list(probe.REGIONS),
        "roles": {},
        "records": [],
    }
    uv_array = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    texture = {
        "uv_array_sha256": "b" * 64,
        "atlas_size": 256,
        "input_uv_origin": "bottom_left_BFM_UV_indices",
        "gltf_uv_origin": "top_left",
        "uv_transform": "synthetic shared mapping",
        "atlas_texel_sample": "synthetic center",
        "classification_codes": probe.REASONS,
    }
    for source_id, conditions in probe.COHORT.items():
        observed = np.zeros((256, 256), bool)
        observed[0, :2] = True
        source_pixels = rgba(observed)
        buffer = io.BytesIO()
        Image.fromarray(source_pixels).save(buffer, format="PNG")
        atlas = put(f"arrays/{source_id}/source.png", buffer.getvalue())
        frame = {"synthetic_source": source_id}
        source_report["records"].append(
            {
                "sample_id": source_id,
                "subject_id": source_id,
                "status": "ok",
                "group": "development",
                "source_age": probe.UNKNOWN_AGE,
                "label_source_age": 40,
                "source_frame": frame,
                "artifacts": {"atlas": atlas},
                "rgba_sha256": probe.uv._digest(source_pixels.tobytes()),
                "texture_metadata": {**texture, "observed_texels": 2},
            }
        )
        for condition in conditions:
            sample = f"{source_id}--sam-{condition:03d}"
            classification = np.zeros((256, 256), np.uint8)
            classification[0, :2] = [5, 6]
            old_arrays = {
                "rgba": rgba(classification == 6),
                "classification": classification,
                "coverage": classification == 6,
                "gltf_uv": uv_array,
            }
            new_arrays = {key: value.copy() for key, value in old_arrays.items()}
            if source_id == "fgnet-004a63":
                new_arrays["classification"][0, 0] = 6
                new_arrays["coverage"][0, 0] = True
                new_arrays["rgba"][0, 0] = [70, 80, 90, 255]
            for variant, arrays, report in (
                ("old", old_arrays, old_report),
                ("conservative", new_arrays, new_report),
            ):
                artifact = put(f"arrays/{sample}/{variant}.npz", npz(**arrays))
                report["records"].append(
                    {
                        "sample_id": sample,
                        "source_id": source_id,
                        "subject_id": source_id,
                        "target_age": condition,
                        "source_age_label": 40,
                        "status": "ok",
                        "source_age": probe.UNKNOWN_AGE,
                        "source_frame": frame,
                        "common_uv": binding["uv"],
                        "sampling_geometry": "target_full_identity_expression_raw_fit",
                        "capabilities": {"age_morph": False, "age_texture": False},
                        "input": unused,
                        "target_fit": unused,
                        "projection": [[condition]],
                        "roi": [0, 0, 1, 1],
                        "gltf_uv_sha256": probe.uv._digest(uv_array.tobytes()),
                        "source_positions_sha256": "c" * 64,
                        "source_normals_sha256": "d" * 64,
                        "source_indices_sha256": "e" * 64,
                        "texture_metadata": {
                            **texture,
                            "classification_counts": {
                                reason: int(np.count_nonzero(arrays["classification"] == code))
                                for reason, code in probe.REASONS.items()
                            },
                        },
                        "artifacts": {"samples": artifact},
                    }
                )
            correspondence = put(f"arrays/{sample}/trace.npz", npz(**trace_arrays()))
            counts = {
                "all_unique_correspondence": {
                    "requested": 2,
                    "classification_counts": {
                        reason: int(code in (5, 6)) for reason, code in probe.REASONS.items()
                    },
                }
            }
            for index, name in enumerate(probe.REGIONS):
                codes = [5] if index == 0 else [6] if index == 1 else []
                counts[name] = {
                    "requested": len(codes),
                    "classification_counts": {
                        reason: codes.count(code) for reason, code in probe.REASONS.items()
                    },
                }
            trace_report["records"].append(
                {
                    "sample_id": sample,
                    "source_id": source_id,
                    "target_age_condition": condition,
                    "source_age_label": 40,
                    "status": "ok",
                    "source_age": probe.UNKNOWN_AGE,
                    "source_frame_verified": True,
                    "classification_mismatches": 0,
                    "gltf_uv_mismatches": 0,
                    "correspondence": correspondence,
                    "counts": counts,
                    "global_classification_counts": {
                        reason: int(np.count_nonzero(classification == code))
                        for reason, code in probe.REASONS.items()
                    },
                }
            )
    reset_pin = put("source-reset.json", json_bytes(source_report))
    old_pin = put("old.json", json_bytes(old_report))
    new_pin = put("conservative.json", json_bytes(new_report))
    trace_report["roles"] = {"source_reset_report": reset_pin, "registration_report": old_pin}
    trace_pin = put("trace.json", json_bytes(trace_report))
    roles = dict(
        zip(probe.ROLES, (protocol_pin, reset_pin, trace_pin, old_pin, new_pin), strict=True)
    )
    plan = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL_ID,
        "runtime": probe.uv.runtime_fingerprint(),
        "roles": roles,
        "inputs": pins,
    }
    plan_path = root / "study-plan.json"
    plan_path.write_bytes(json_bytes(plan))
    args = argparse.Namespace(root=root, study_plan=plan_path, output_dir="output/research/joint")
    return args, plan, source_report, old_report, new_report, trace_report


def test_full_frozen_synthetic_study_publishes_all24_json_rows_and_deltas(study):
    args, *_ = study
    result = probe.run(args)
    assert result["summary"]["records_verified"] == 24
    assert len(result["deltas"]) == 12
    assert [row["new_sampled_texels"] for row in result["deltas"]] == [1] * 4 + [0] * 8
    assert all(row["source_age"] == probe.UNKNOWN_AGE for row in result["records"])
    assert {p.name for p in (args.root / args.output_dir).iterdir()} == {"report.json"}
    assert all(result[key] is value for key, value in probe.FLAGS.items())


def test_existing_output_is_never_overwritten(study):
    args, *_ = study
    path = args.root / args.output_dir
    path.mkdir(parents=True)
    marker = path / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="new directory"):
        probe.run(args)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_missing_binary_pin_or_extra_model_input_rejected_before_output(study):
    args, plan, *_ = study
    plan["inputs"] = [p for p in plan["inputs"] if not p["path"].endswith("/source.png")]
    args.study_plan.write_bytes(json_bytes(plan))
    with pytest.raises(ValueError, match="Freeze omits"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


@pytest.mark.parametrize("mutation", ["age", "projection", "source_frame", "uv", "duplicate"])
def test_metadata_crosslink_errors_fail_before_binary_reads(study, monkeypatch, mutation):
    args, plan, source, old, new, trace = study
    metadata = dict(
        zip(
            probe.ROLES,
            (
                json.loads(
                    (args.root / plan["roles"]["protocol"]["path"]).read_text(encoding="utf-8")
                ),
                source,
                trace,
                old,
                new,
            ),
            strict=True,
        )
    )
    if mutation == "age":
        old["records"][0]["source_age"] = {"value": 40, "method": "user", "calibration_id": None}
    elif mutation == "projection":
        new["records"][0]["projection"] = [[99]]
    elif mutation == "source_frame":
        new["records"][0]["source_frame"] = {"new": True}
    elif mutation == "uv":
        new["records"][0]["texture_metadata"]["uv_array_sha256"] = "f" * 64
    else:
        trace["records"].append(copy.deepcopy(trace["records"][0]))
    with pytest.raises(ValueError):
        probe.select_records(metadata, plan["roles"])


def test_frozen_plan_runtime_drift_rejected(study):
    args, plan, *_ = study
    plan["runtime"]["python"] = "changed"
    args.study_plan.write_bytes(json_bytes(plan))
    with pytest.raises(ValueError, match="runtime"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


def test_extra_metadata_input_is_not_read_even_if_hash_valid(study):
    args, plan, *_ = study
    extra = pin_file(args.root, "holdout/age-results.json", b'{"synthetic_holdout":true}')
    plan["inputs"].append(extra)
    args.study_plan.write_bytes(json_bytes(plan))
    with pytest.raises(ValueError, match="Freeze omits"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


def test_loaded_helper_cannot_be_replaced_by_a_newly_pinned_disk_file(study):
    args, plan, *_ = study
    name = "tools/uv_support_probe.py"
    new = pin_file(args.root, name, b"different helper, not loaded\n")
    plan["inputs"] = [new if row["path"] == name else row for row in plan["inputs"]]
    args.study_plan.write_bytes(json_bytes(plan))
    with pytest.raises(ValueError, match="code loaded"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


def test_changed_binary_bytes_fail_pin_before_publication(study):
    args, plan, *_ = study
    name = next(row["path"] for row in plan["inputs"] if row["path"].endswith("/old.npz"))
    (args.root / name).write_bytes(b"changed array snapshot")
    with pytest.raises(ValueError, match="pin mismatch"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


def test_late_input_drift_removes_only_owned_pending_publication(study, monkeypatch):
    args, plan, *_ = study
    original = probe.recheck_inputs
    calls = 0

    def recheck(inputs):
        nonlocal calls
        calls += 1
        if calls == 2:
            path = inputs.root / plan["roles"]["source_reset_report"]["path"]
            path.write_bytes(b"changed")
        original(inputs)

    monkeypatch.setattr(probe, "recheck_inputs", recheck)
    with pytest.raises(ValueError, match="drift"):
        probe.run(args)
    assert not (args.root / args.output_dir).exists()


def test_final_recheck_stops_after_declared_size_plus_one(tmp_path, monkeypatch):
    value = pin_file(tmp_path, "small.json", b"1234")
    inputs = probe.uv.Inputs(tmp_path, [value])
    requested = []

    class NeverEndingFile(io.BytesIO):
        def read(self, count=-1):
            requested.append(count)
            assert count > 0
            return b"x" * count

    original = Path.open

    def opened(path, *args, **kwargs):
        if path == tmp_path / "small.json":
            return NeverEndingFile()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ValueError, match="drift"):
        probe.recheck_inputs(inputs)
    assert requested == [5]
