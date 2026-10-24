"""Synthetic render-domain diagnostics; no browser, real assets or models run."""

import copy
import hashlib
import importlib.util
import json
import math
import random
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load("render_probe_tests", ROOT / "tools/render_evaluator_probe.py")
age_tests = load("render_age_fixture", ROOT / "backend/tests/test_age_evaluator_probe.py")
pin, write = age_tests.pin, age_tests.write
ENVIRONMENT = {"runtime": "synthetic-only"}
FACE = age_tests.FACE
VECTOR = [1.0, *([0.0] * 127)]


class FakeIdentity:
    def __init__(self):
        self.environment = copy.deepcopy(ENVIRONMENT)
        self.calls = []
        self.closed = False
        self.behavior = None

    def evaluate(self, image):
        self.calls.append(image)
        if self.behavior:
            self.behavior(image)
        return {
            "face": list(FACE),
            "detector_input_size": list(image.size),
            "detector_to_original_scale_xy": [1.0, 1.0],
            "aligned_size": [112, 112],
            "embedding": list(VECTOR),
        }

    def close(self):
        self.closed = True


class FakeAge:
    def __init__(self):
        self.environment = copy.deepcopy(ENVIRONMENT)
        self.calls = []
        self.closed = False
        self.behavior = None

    def predict(self, image):
        self.calls.append(image)
        if self.behavior:
            self.behavior(image)
        return {"age": 25.125, "raw_age": (25.125 - 61) / 122}

    def close(self):
        self.closed = True


@pytest.fixture
def case(tmp_path, monkeypatch):
    value = age_tests.case.__wrapped__(tmp_path, monkeypatch)
    root = value["root"]
    for name in (*probe.SOURCES, *probe.CAPTURE_SOURCES):
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    monkeypatch.setattr(probe.identity, "MODELS", age_tests.identity_tests.probe.MODELS)
    monkeypatch.setattr(probe.age, "RELEASE", age_tests.probe.RELEASE)
    monkeypatch.setattr(probe.age, "MODEL", age_tests.probe.MODEL)
    monkeypatch.setattr(probe, "_environment", lambda stage: copy.deepcopy(ENVIRONMENT))
    bridge = value["manifest"]["bridge_cases"][0]
    source_id = bridge["sample_id"]
    frame = {"version": "synthetic-static-frame"}
    geometry = {name: hashlib.sha256(name.encode()).hexdigest() for name in probe.GEOMETRY_KEYS}
    original = {
        "sample_id": source_id,
        "subject_id": bridge["subject_id"],
        "group": "development",
        "status": "ok",
        "input": bridge["source"],
        "label_source_age": bridge["source_age"]["value"],
        "research_source_age": copy.deepcopy(bridge["source_age"]),
        "source_age": {"value": None, "method": "unknown", "calibration_id": None},
        "source_frame": frame,
        "artifacts": {},
    }
    value["source_reset"] = {
        "protocol_id": "agemorph3d-source-reset-v1",
        "research_only": True,
        "inputs": {},
        "records": [original],
        "service_ready": False,
        "g3_complete": False,
        "holdout_age_results_opened": False,
    }
    value["registration"]["source_geometry_invariants"] = {source_id: geometry}
    value["registration"]["research_only"] = True
    for row in value["registration"]["records"]:
        row.update(
            sample_id=f"{source_id}--sam-{row['target_age']:03}",
            source_frame=frame,
            status="ok",
            asset_mode="static",
            source_age=copy.deepcopy(original["source_age"]),
            capabilities={"age_morph": False, "age_texture": False},
            artifacts={},
            **geometry,
        )
    for row in [original, *value["registration"]["records"]]:
        for kind, suffix in (("glb", "glb"), ("atlas", "png")):
            path = root / f"output/research/assets/{row['sample_id']}.{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic pinned asset; never decoded")
            row["artifacts"][kind] = pin(path, root)
    assets, frames, pairs = probe.requests(
        value["manifest"], value["registration"], value["source_reset"]
    )
    value["capture"] = capture_for(frames)
    value["capture"].update(
        assets=[
            {
                **{
                    key: item for key, item in asset.items() if key not in {"artifacts", "geometry"}
                },
                "status": "captured",
                "glb": asset["artifacts"]["glb"],
                "atlas": asset["artifacts"]["atlas"],
                "expected_geometry": asset["geometry"],
            }
            for asset in assets
        ],
        asset_pins=[entry for asset in assets for entry in asset["artifacts"].values()],
        owned_servers_closed=True,
        browser_closed=True,
        interrupted=False,
        external_requests=[],
        browser_errors=[],
    )
    geometry_by_asset = {asset["asset_id"]: asset["geometry"] for asset in assets}
    for index, record in enumerate(value["capture"]["frames"]):
        path = root / record["image"]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.new("RGB", (16, 16), (index * 3, 70, 140)) as image:
            image.save(path, "PNG")
        record["image"] = pin(path, root)
        record["observed"] = {
            "geometry": geometry_by_asset[record["asset_id"]],
            "png_sha256": record["image"]["sha256"],
        }
    value["render_protocol"] = policy()
    value["render_protocol"]["capture"].update(width=16, height=16)
    value["render_protocol"]["cohort"].update(
        original_assets=1,
        sam_assets=3,
        source_age_labels_known=1,
        source_age_labels_unknown=0,
        same_age_control_assets=1,
        other_condition_assets=2,
        unknown_source_age_assets=0,
        unique_frames=len(frames),
        paired_comparisons=len(pairs),
    )
    value["identity_evaluator"] = FakeIdentity()
    value["age_evaluator"] = FakeAge()
    return value


def freeze(case, stage):
    root = case["root"]
    age_pin = write(root, "docs/synthetic-n0-protocol.json", case["protocol"])
    case["manifest"]["inputs"]["protocol"] = age_pin
    n0_pin = write(root, "output/research/render-input/n0.json", case["manifest"])
    for name in ("registration", "source_reset"):
        case[name]["inputs"]["protocol_manifest"] = n0_pin
    roles = {
        "protocol": write(root, "docs/synthetic-render-protocol.json", case["render_protocol"]),
        "age_protocol": age_pin,
        "n0_manifest": n0_pin,
        "registration_report": write(
            root, "output/research/render-input/n4.json", case["registration"]
        ),
        "source_reset_report": write(
            root, "output/research/render-input/reset.json", case["source_reset"]
        ),
        "environment": write(root, "output/research/render-input/environment.json", ENVIRONMENT),
    }
    source_pins = [pin(root / name, root) for name in probe.CAPTURE_SOURCES]
    case["capture"].update(
        inputs=[
            *(
                roles[name]
                for name in (
                    "protocol",
                    "n0_manifest",
                    "registration_report",
                    "source_reset_report",
                )
            ),
            *source_pins,
        ],
        source_pins=source_pins,
        requested_configuration=copy.deepcopy(case["render_protocol"]["capture"]),
    )
    roles["capture_report"] = write(
        root, "output/research/render-input/capture.json", case["capture"]
    )
    if stage == "identity":
        roles["model_manifest"] = write(root, "data/models/evaluation/models.json", case["models"])
    else:
        roles.update(
            identity_report=write(
                root, "output/research/render-input/identity.json", case["render_identity"]
            ),
            source_acquisition=write(
                root, "output/research/render-input/age-sources.json", case["source_acquisition"]
            ),
            model_acquisition=write(
                root, "output/research/render-input/age-model.json", case["model_acquisition"]
            ),
        )
    plan = {
        "protocol_id": probe.PROTOCOL,
        **roles,
        "inputs": [
            *roles.values(),
            *(pin(root / name, root) for name in probe.SOURCES),
            *source_pins,
        ],
    }
    case["render_plan"] = plan
    entry = write(root, f"output/research/render-input/{stage}-plan.json", plan)
    return root / entry["path"]


def run_identity(case):
    return probe.build_identity_report(
        case["root"], freeze(case, "identity"), lambda _: case["identity_evaluator"]
    )


def run_age(case):
    case["render_identity"] = run_identity(case)
    return probe.build_age_report(
        case["root"], freeze(case, "age"), lambda _: case["age_evaluator"]
    )


def policy():
    return json.loads((ROOT / "docs/render-domain-v1.json").read_text("utf-8"))


def metadata_pin(name):
    return {"path": name, "bytes": 100, "sha256": hashlib.sha256(name.encode()).hexdigest()}


def synthetic_metadata(labels=(27, 27, 63, 55, 45, 35, 25, 38, None, None)):
    """Construct the requested source/target relationships without real output files."""
    n0 = {"bridge_cases": [], "adult_images": []}
    registration = {
        "protocol_id": "agemorph3d-target-uv-v1",
        "records": [],
        "source_geometry_invariants": {},
    }
    reset = {"records": []}
    for index, label in enumerate(labels):
        source_id = f"synthetic-{index:02}"
        source_pin = metadata_pin(f"data/images/{source_id}.png")
        geometry = {
            name: hashlib.sha256(f"{source_id}/{name}".encode()).hexdigest()
            for name in (
                "source_positions_sha256",
                "source_normals_sha256",
                "source_indices_sha256",
                "gltf_uv_sha256",
            )
        }
        source_frame = {"version": "synthetic-fixed-canonical", "source_id": source_id}
        target_ages = sorted({20, 45, 70, *([] if label is None else [label])})
        runs = [
            {
                "target_age": target,
                **metadata_pin(f"output/research/sam/{source_id}/{target}.png"),
            }
            for target in target_ages
        ]
        same = next((run for run in runs if run["target_age"] == label), None)
        n0["bridge_cases"].append(
            {
                "sample_id": source_id,
                "subject_id": f"subject-{index:02}",
                "group": "development",
                "source_status": "passed",
                "source": source_pin,
                "source_age": {
                    "value": label,
                    "method": "unknown" if label is None else "dataset_filename",
                    "independently_verified": False,
                },
                "target_runs": [run for run in runs if run["target_age"] in (20, 45, 70)],
                "same_age_control": {
                    "status": "not_applicable_unknown_source_age"
                    if label is None
                    else "reused_existing"
                    if label in (20, 45, 70)
                    else "generated",
                    "target_age": label,
                    **(
                        {"output": {k: same[k] for k in ("path", "bytes", "sha256")}}
                        if same
                        else {}
                    ),
                },
            }
        )
        registration["source_geometry_invariants"][source_id] = geometry
        reset["records"].append(
            {
                "sample_id": source_id,
                "subject_id": f"subject-{index:02}",
                "group": "development",
                "input": source_pin,
                "label_source_age": label,
                "research_source_age": copy.deepcopy(n0["bridge_cases"][-1]["source_age"]),
                "source_age": {"value": None, "method": "unknown", "calibration_id": None},
                "source_frame": source_frame,
                "status": "ok",
                "artifacts": {
                    kind: metadata_pin(f"output/research/original/{source_id}.{suffix}")
                    for kind, suffix in (("glb", "glb"), ("atlas", "png"))
                },
            }
        )
        for run in runs:
            sample_id = f"{source_id}--sam-{run['target_age']:03}"
            registration["records"].append(
                {
                    "sample_id": sample_id,
                    "source_id": source_id,
                    "subject_id": f"subject-{index:02}",
                    "source_age_label": label,
                    "target_age": run["target_age"],
                    "status": "ok",
                    "asset_mode": "static",
                    "source_age": {"value": None, "method": "unknown", "calibration_id": None},
                    "capabilities": {"age_morph": False, "age_texture": False},
                    "input": {k: run[k] for k in ("path", "bytes", "sha256")},
                    "source_frame": source_frame,
                    **geometry,
                    "artifacts": {
                        kind: metadata_pin(f"output/research/registered/{sample_id}.{suffix}")
                        for kind, suffix in (("glb", "glb"), ("atlas", "png"))
                    },
                }
            )
    return n0, registration, reset


def capture_for(frames):
    return {
        "protocol_id": probe.PROTOCOL,
        "status": "passed",
        "research_only": True,
        **dict.fromkeys(probe.FALSE_FLAGS, False),
        "frames": [
            {
                **copy.deepcopy(frame),
                "status": "ok",
                "image": metadata_pin(f"output/research/render/frame-{index:03}.png"),
            }
            for index, frame in enumerate(frames)
        ],
    }


def select(rows, config="MASK/front/black", category="other_condition"):
    return next(row for row in rows if row["config_id"] == config and row["category"] == category)


def pair(source, age=10.0, identity=0.5, *, category="other_condition", config="MASK/front/black"):
    return {
        "source_id": source,
        "config_id": config,
        "category": category,
        "age_status": "scored" if age is not None else "failed",
        "identity_status": "scored" if identity is not None else "failed",
        "identity_cosine": identity,
        "age_shift": age,
        "condition_deviation": age,
        "static_condition_deviation": None if age is None else age + 2,
        "absolute_condition_reduction": None if age is None else 2.0,
    }


def percentile(values, quantile):
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[min(lower + 1, len(ordered) - 1)] * fraction


def independent_interval(values, key):
    rng = random.Random(20261023 + int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    draws = []
    for _ in range(1000):
        indices = [rng.randrange(len(values)) for _ in values]
        draws.append(sum(values[index] for index in indices) / len(values))
    return [percentile(draws, 0.025), percentile(draws, 0.975)]


def test_requests_preserve_full_matrix_controls_unknown_ages_and_reused_baselines():
    assets, frames, pairs = probe.requests(*synthetic_metadata())
    assert (len(assets), len(frames), len(pairs)) == (47, 376, 296)
    assert len({frame["frame_id"] for frame in frames}) == 376
    assert len({pair["left_id"] for pair in pairs}) == 80
    assert Counter(pair["category"] for pair in pairs) == {
        "same_age_control": 64,
        "other_condition": 184,
        "unknown_source_age": 48,
    }
    originals = [asset for asset in assets if asset["role"] == "original_static_3d"]
    assert len(originals) == 10
    assert all(asset["target_age"] is None for asset in originals)
    assert sum(asset["source_age_label"] is None for asset in originals) == 2
    for comparison in pairs:
        left, right = frames[comparison["left_id"]], frames[comparison["right_id"]]
        assert left["source_id"] == right["source_id"] == comparison["source_id"]
        assert left["config_id"] == right["config_id"] == comparison["config_id"]
        assert left["role"] == "original_static_3d"
        assert right["role"] == "sam_texture_static_3d"


@pytest.mark.parametrize("field", ["source_frame", "source_positions_sha256", "gltf_uv_sha256"])
def test_metadata_rejects_mismatched_target_canonical_geometry(field):
    n0, registration, reset = synthetic_metadata((27,))
    registration["records"][0][field] = {} if field == "source_frame" else "0" * 64
    with pytest.raises(ValueError):
        probe.requests(n0, registration, reset)


def test_metadata_rejects_duplicate_target_or_missing_same_age_control():
    n0, registration, reset = synthetic_metadata((27,))
    registration["records"].append(copy.deepcopy(registration["records"][0]))
    with pytest.raises(ValueError):
        probe.requests(n0, registration, reset)
    n0, registration, reset = synthetic_metadata((27,))
    registration["records"] = [row for row in registration["records"] if row["target_age"] != 27]
    with pytest.raises(ValueError):
        probe.requests(n0, registration, reset)


def test_capture_keeps_exact_configurations_and_rejects_missing_duplicate_or_wrong_role():
    _, frames, _ = probe.requests(*synthetic_metadata((27,)))
    capture = capture_for(frames)
    validated = probe.validate_capture(capture, frames)
    assert len(validated) == len(frames)
    for replacement in (capture["frames"][:-1], [*capture["frames"][:-1], capture["frames"][0]]):
        invalid = {**capture, "frames": replacement}
        with pytest.raises(ValueError):
            probe.validate_capture(invalid, frames)
    capture["frames"][0]["target_age"] = 20
    with pytest.raises(ValueError):
        probe.validate_capture(capture, frames)


@pytest.mark.parametrize("key", ["g3_complete", "production_enabled", "service_ready"])
def test_capture_cannot_promote_acceptance_flags(key):
    _, frames, _ = probe.requests(*synthetic_metadata((27,)))
    capture = capture_for(frames)
    capture[key] = True
    with pytest.raises(ValueError):
        probe.validate_capture(capture, frames)


def test_capture_rejects_nonresearch_or_nonpng_image_paths():
    _, frames, _ = probe.requests(*synthetic_metadata((27,)))
    for path in ("data/private.png", "output/research/render/frame.jpg", "../outside.png"):
        capture = capture_for(frames)
        capture["frames"][0]["image"]["path"] = path
        with pytest.raises(ValueError):
            probe.validate_capture(capture, frames)


def test_macro_weights_sources_equally_and_keeps_independent_complete_case_sets():
    rows = [pair("a", age=1, identity=0.2) for _ in range(3)]
    rows += [pair("b", age=9, identity=None), pair("c", age=None, identity=0.8)]
    result = select(probe.aggregate_pairs(rows, policy()))
    assert result["age"]["requested"] == result["identity"]["requested"] == 5
    assert result["age"]["scored"] == result["identity"]["scored"] == 4
    assert result["age"]["effective_units"] == result["identity"]["effective_units"] == 2
    assert result["age"]["macro"]["age_shift"] == 5
    assert result["identity"]["macro"]["identity_cosine"] == pytest.approx(0.5)
    assert result["age"]["macro"]["age_shift"] != pytest.approx((3 + 9) / 4)


def test_bootstrap_uses_sorted_source_vectors_and_protocol_key_not_pair_count():
    rows = [pair("z", age=9), pair("a", age=-1), pair("m", age=4)]
    result = select(probe.aggregate_pairs(rows, policy()))["age"]
    expected = independent_interval([-1, 4, 9], "paired/MASK/front/black/other_condition")
    assert result["bootstrap"]["intervals"]["age_shift"] == pytest.approx(expected)
    reordered = select(probe.aggregate_pairs(list(reversed(rows)), policy()))["age"]
    assert reordered == result


def test_all_eight_configurations_and_three_categories_retain_zero_unit_summaries():
    results = probe.aggregate_pairs([pair("one", age=4)], policy())
    assert len(results) == 24
    assert len({row["config_id"] for row in results}) == 8
    effective = select(results)["age"]
    assert effective["effective_units"] == 1
    assert effective["bootstrap"]["intervals"]["age_shift"] == [4, 4]
    empty = select(results, category="unknown_source_age")["age"]
    assert empty["requested"] == empty["effective_units"] == 0
    assert empty["macro"]["age_shift"] is None
    assert empty["bootstrap"]["intervals"]["age_shift"] is None


def test_pair_scores_use_matching_static_baseline_and_separate_failure_denominators():
    requests = [
        {
            "pair_id": index,
            "left_id": 0,
            "right_id": index + 1,
            "source_id": "unknown-source",
            "sample_id": f"sam-{target}",
            "category": "unknown_source_age",
            "config_id": "MASK/front/black",
            "target_age": target,
            "source_age_label": None,
        }
        for index, target in enumerate((70, 45, 20))
    ]
    records = [
        {"status": "ok" if estimate is not None else "NO_FACE", "age_estimate": estimate}
        for estimate in (40.0, 60.0, None, 25.0)
    ]
    vector = [1.0, *([0.0] * 127)]
    orthogonal = [0.0, 1.0, *([0.0] * 126)]
    identities = [
        {"status": "ok", "embedding": vector},
        {"status": "NO_FACE", "embedding": None},
        {"status": "ok", "embedding": vector},
        {"status": "ok", "embedding": orthogonal},
    ]
    result = probe.score_pairs(requests, records, identities)
    assert len(result) == 3
    assert result[0]["age_status"] == "scored"
    assert result[0]["identity_status"] == "failed"
    assert result[0]["identity_cosine"] is None
    assert result[0]["age_shift"] == 20
    assert result[0]["condition_deviation"] == -10
    assert result[0]["static_condition_deviation"] == -30
    assert result[0]["absolute_condition_reduction"] == 20
    assert result[0]["source_age_label"] is None
    assert result[1]["identity_cosine"] == 1
    assert result[1]["age_status"] == "failed"
    assert all(
        result[1][metric] is None
        for metric in (
            "age_shift",
            "condition_deviation",
            "static_condition_deviation",
            "absolute_condition_reduction",
        )
    )
    assert result[2]["identity_cosine"] == 0
    assert result[2]["age_shift"] == -15


def test_original_age_error_keeps_unknown_and_failed_requests_without_default_ages():
    records = [
        {
            "role": "original_static_3d",
            "source_id": source,
            "config_id": "MASK/front/black",
            "source_age_label": label,
            "status": "ok" if estimate is not None else "NO_FACE",
            "age_estimate": estimate,
        }
        for source, label, estimate in (
            ("known-a", 20, 23),
            ("known-b", 50, 43),
            ("unknown", None, 45),
            ("failed", 60, None),
        )
    ]
    summaries = probe.aggregate_originals(records, policy())
    assert len(summaries) == 8
    result = next(row for row in summaries if row["config_id"] == "MASK/front/black")
    assert result["requested"] == 4
    assert result["scored"] == 2 and result["null"] == 2
    assert result["known_label_requests"] == 3
    assert result["unknown_label_requests"] == 1
    assert result["effective_units"] == 2
    assert result["macro"]["mae"] == 5
    assert result["macro"]["bias"] == -2
    assert result["macro"]["rmse"] == pytest.approx(math.sqrt(29))
    assert records[2]["source_age_label"] is None
    assert all(row["requested"] == 0 for row in summaries if row is not result)


def test_fake_identity_and_age_runs_close_every_image_and_preserve_all_flags(case):
    report = run_age(case)
    identity = case["render_identity"]
    assert (
        report["frame_counts"]
        == identity["frame_counts"]
        == {
            "requested": 32,
            "successful": 32,
            "failed": 0,
        }
    )
    assert (
        report["pair_counts"]["age"]
        == report["pair_counts"]["identity"]
        == {
            "requested": 24,
            "scored": 24,
            "failed": 0,
        }
    )
    assert report["integrity_status"] == identity["integrity_status"] == "passed"
    assert report["execution_status"] == "complete"
    assert len(report["paired_summaries"]) == 24
    assert len(report["original_age_summaries"]) == 8
    assert all(report[key] is False and identity[key] is False for key in probe.FALSE_FLAGS)
    assert report["quality_threshold"] is None and report["models_closed"]
    assert report["images_or_crops_written"] is False
    assert report["holdout_predictions_extracted"] is False
    for evaluator in (case["identity_evaluator"], case["age_evaluator"]):
        assert evaluator.closed and len(evaluator.calls) == 32
        for image in evaluator.calls:
            with pytest.raises(ValueError, match="closed"):
                image.getpixel((0, 0))


def test_cached_identity_failure_skips_age_but_retains_frame_and_pair_denominators(case):
    def fail_first(_):
        if len(case["identity_evaluator"].calls) == 1:
            raise probe.identity.EvaluationFailure("NO_FACE")

    case["identity_evaluator"].behavior = fail_first
    report = run_age(case)
    assert len(case["age_evaluator"].calls) == 31
    assert report["frames"][0]["status"] == "NO_FACE"
    assert report["frames"][0]["reused_detection_status"] == "NO_FACE"
    assert report["frames"][0]["age_estimate"] is None
    assert report["frame_counts"] == {"requested": 32, "successful": 31, "failed": 1}
    assert report["pair_counts"]["age"] == {"requested": 24, "scored": 21, "failed": 3}
    assert report["pair_counts"]["identity"] == {"requested": 24, "scored": 21, "failed": 3}


def test_age_only_failure_does_not_erase_valid_cached_identity_scores(case):
    def fail_first(_):
        if len(case["age_evaluator"].calls) == 1:
            raise RuntimeError("synthetic age-only failure")

    case["age_evaluator"].behavior = fail_first
    report = run_age(case)
    assert report["frames"][0]["status"] == "EVALUATOR_FAILED"
    assert report["frames"][0]["reused_detection_status"] == "ok"
    assert report["frames"][0]["age_estimate"] is None
    assert report["pair_counts"]["age"] == {"requested": 24, "scored": 21, "failed": 3}
    assert report["pair_counts"]["identity"] == {"requested": 24, "scored": 24, "failed": 0}
    assert case["age_evaluator"].closed


def test_cached_box_is_clipped_without_padding_or_landmark_warp(case, monkeypatch):
    result = case["identity_evaluator"].evaluate

    def clipped_box(image):
        value = result(image)
        value["face"][:4] = [-1.2, 2.7, 11.1, 30.2]
        return value

    monkeypatch.setattr(case["identity_evaluator"], "evaluate", clipped_box)
    report = run_age(case)
    assert report["frames"][0]["crop_bounds"] == [0, 2, 10, 16]
    assert report["frames"][0]["age_estimate"] == 25.125
    assert report["frame_counts"]["successful"] == 32
    assert all(image.size == (10, 14) for image in case["age_evaluator"].calls)


def test_frozen_capture_mismatch_is_rejected_before_factory(case):
    plan = freeze(case, "identity")
    path = case["root"] / case["render_plan"]["capture_report"]["path"]
    path.write_text("{}", encoding="utf-8")
    calls = []
    with pytest.raises(ValueError):
        probe.build_identity_report(case["root"], plan, lambda _: calls.append(True))
    assert calls == []


def test_source_pin_mismatch_is_not_decoded_and_keeps_all_requests(case, monkeypatch):
    plan = freeze(case, "identity")
    source = case["capture"]["frames"][0]["image"]
    (case["root"] / source["path"]).write_bytes(b"untrusted changed bytes")
    decoded = []
    original = probe.identity.decode_image

    def record_decode(raw, *args):
        decoded.append(raw)
        return original(raw, *args)

    monkeypatch.setattr(probe.identity, "decode_image", record_decode)
    report = probe.build_identity_report(case["root"], plan, lambda _: case["identity_evaluator"])
    assert len(decoded) == 31 and b"untrusted changed bytes" not in decoded
    assert len(report["frames"]) == 32 and len(report["pairs"]) == 24
    assert report["integrity_status"] == "failed"
    assert report["frames"][0]["embedding"] is None
    assert report["pair_counts"]["identity"]["failed"] == 3
    assert case["identity_evaluator"].closed


def test_late_image_drift_after_bootstrap_invalidates_embedding_and_recomputes(case, monkeypatch):
    aggregate = probe.aggregate_pairs
    calls = []

    def drift_once(pairs, protocol):
        value = aggregate(pairs, protocol)
        calls.append(True)
        if len(calls) == 1:
            source = case["capture"]["frames"][0]["image"]
            (case["root"] / source["path"]).write_bytes(b"late render drift")
        return value

    monkeypatch.setattr(probe, "aggregate_pairs", drift_once)
    report = run_identity(case)
    assert len(calls) == 2
    assert report["frames"][0]["status"] == "source_changed"
    assert report["frames"][0]["embedding"] is None
    assert report["integrity_status"] == "failed"
    assert report["frame_counts"]["requested"] == 32
    assert report["pair_counts"]["identity"] == {"requested": 24, "scored": 21, "failed": 3}
    result = select(report["paired_summaries"], category="same_age_control")
    assert result["identity"]["requested"] == 1 and result["identity"]["scored"] == 0
    assert case["identity_evaluator"].closed


def test_late_metadata_drift_rejects_publication_and_closes_evaluator(case):
    def mutate_protocol(_):
        if len(case["identity_evaluator"].calls) == 1:
            path = case["root"] / case["render_plan"]["protocol"]["path"]
            path.write_text("{}", encoding="utf-8")

    case["identity_evaluator"].behavior = mutate_protocol
    with pytest.raises(ValueError):
        run_identity(case)
    assert case["identity_evaluator"].closed


def test_new_large_report_allowance_applies_only_to_explicit_capture_role(case):
    case["capture"]["synthetic_padding"] = "x" * (2 * 1024 * 1024)
    report = run_identity(case)
    assert report["frame_counts"]["successful"] == 32
    assert report["integrity_status"] == "passed"


def test_age_drift_after_bootstrap_clears_estimates_and_recomputes_original_errors(
    case, monkeypatch
):
    case["render_identity"] = run_identity(case)
    aggregate = probe.aggregate_pairs
    calls = []

    def drift_once(pairs, protocol):
        result = aggregate(pairs, protocol)
        calls.append(True)
        if len(calls) == 1:
            image = case["capture"]["frames"][0]["image"]
            (case["root"] / image["path"]).write_bytes(b"late age frame drift")
        return result

    monkeypatch.setattr(probe, "aggregate_pairs", drift_once)
    report = probe.build_age_report(
        case["root"], freeze(case, "age"), lambda _: case["age_evaluator"]
    )
    assert len(calls) == 2
    assert report["frames"][0]["status"] == "source_changed"
    assert report["frames"][0]["age_estimate"] is None
    assert report["frames"][0]["raw_age_estimate"] is None
    assert report["integrity_status"] == "failed"
    assert report["pair_counts"]["age"] == {"requested": 24, "scored": 21, "failed": 3}
    result = next(
        row for row in report["original_age_summaries"] if row["config_id"] == "MASK/front/black"
    )
    assert result["requested"] == result["null"] == 1
    assert result["macro"]["mae"] is None
    assert case["age_evaluator"].closed


@pytest.mark.parametrize("stage", ["identity", "age"])
def test_fixed_model_drift_during_inference_rejects_publication_and_releases_resources(case, stage):
    evaluator = case[stage + "_evaluator"]
    if stage == "age":
        case["render_identity"] = run_identity(case)
        artifact = case["model_acquisition"]["model"]
    else:
        artifact = case["models"]["models"][0]["artifact"]

    def change_weights(_):
        if len(evaluator.calls) == 1:
            (case["root"] / artifact["path"]).write_bytes(b"changed synthetic weights")

    evaluator.behavior = change_weights
    build = probe.build_age_report if stage == "age" else probe.build_identity_report
    with pytest.raises(ValueError):
        build(case["root"], freeze(case, stage), lambda _: evaluator)
    assert evaluator.closed


def test_evaluator_environment_drift_rejects_publication_and_closes_resources(case):
    evaluator = case["identity_evaluator"]

    def change_environment(_):
        evaluator.environment["runtime"] = "changed"

    evaluator.behavior = change_environment
    with pytest.raises(ValueError, match="environment changed"):
        run_identity(case)
    assert evaluator.closed


def test_ordinary_metadata_cannot_use_the_large_capture_report_allowance(case):
    plan = freeze(case, "identity")
    roles = case["render_plan"]
    path = case["root"] / roles["environment"]["path"]
    path.write_text(json.dumps({"padding": "x" * (2 * 1024 * 1024)}), encoding="utf-8")
    old_pin = roles["environment"]
    updated = pin(path, case["root"])
    roles["environment"] = updated
    roles["inputs"] = [updated if entry == old_pin else entry for entry in roles["inputs"]]
    write(case["root"], plan.relative_to(case["root"]).as_posix(), roles)
    factories = []
    with pytest.raises(ValueError):
        probe.build_identity_report(case["root"], plan, lambda _: factories.append(True))
    assert factories == []


def test_cli_refuses_to_overwrite_prior_evidence_before_evaluation(case, monkeypatch):
    output = case["root"] / "output/research/preserved"
    output.mkdir(parents=True)
    artifact = output / "report.json"
    artifact.write_text("previous evidence", encoding="utf-8")
    invoked = []
    monkeypatch.setattr(probe, "build_identity_report", lambda *_: invoked.append(True))
    code = probe.main(
        [
            "identity",
            "--root",
            str(case["root"]),
            "--study-plan",
            str(case["root"] / "nonexistent-plan.json"),
            "--output-dir",
            "output/research/preserved",
        ]
    )
    assert code == 1 and invoked == []
    assert artifact.read_text("utf-8") == "previous evidence"


@pytest.mark.parametrize(
    "failure",
    [
        "foreign_protocol",
        "missing_producer",
        "wrong_asset",
        "wrong_pixel",
        "unclosed_browser",
        "external_request",
    ],
)
def test_capture_linkage_rejects_foreign_provenance_or_unclosed_external_execution(case, failure):
    freeze(case, "identity")
    assets, _, _ = probe.requests(case["manifest"], case["registration"], case["source_reset"])
    capture = copy.deepcopy(case["capture"])
    assert (
        probe._link_capture(capture, assets, case["render_plan"], case["render_protocol"]) is None
    )
    if failure == "foreign_protocol":
        capture["inputs"][0]["sha256"] = "0" * 64
    elif failure == "missing_producer":
        capture["source_pins"].pop()
    elif failure == "wrong_asset":
        capture["assets"][0]["glb"]["sha256"] = "0" * 64
    elif failure == "wrong_pixel":
        capture["frames"][0]["observed"]["png_sha256"] = "0" * 64
    elif failure == "unclosed_browser":
        capture["browser_closed"] = False
    else:
        capture["external_requests"] = ["https://example.org/unexpected"]
    with pytest.raises(ValueError):
        probe._link_capture(capture, assets, case["render_plan"], case["render_protocol"])


def test_age_rejects_cached_identity_from_a_different_model_before_predictor_creation(case):
    case["render_identity"] = run_identity(case)
    case["render_identity"]["model_pins"][0]["sha256"] = "0" * 64
    invoked = []
    with pytest.raises(ValueError):
        probe.build_age_report(case["root"], freeze(case, "age"), lambda _: invoked.append(True))
    assert invoked == []
