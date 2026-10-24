"""Synthetic identity diagnostics: no real photos, weights or face inference."""

import csv
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load("identity_probe_tests", ROOT / "tools/identity_evaluator_probe.py")
n0_tests = load("identity_n0_fixture", ROOT / "backend/tests/test_evaluation_readiness_probe.py")
pin, write = n0_tests.pin, n0_tests.write
ENVIRONMENT = dict.fromkeys(
    ("python_version", "pillow_version", "opencv_version", "numpy_version"), "synthetic"
)
FACE = [1, 1, 13, 13, 4, 5, 11, 5, 8, 8, 5, 11, 10, 11, 0.95]
VECTOR = [1.0, *([0.0] * 127)]


def photo(root, name, color):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", (16, 16), color) as image:
        image.save(path, format="JPEG" if path.suffix.lower() == ".jpg" else "PNG")
    return pin(path, root)


def freeze(case):
    root = case["root"]
    age_pin = write(root, "docs/age-protocol.json", case["protocol"])
    case["manifest"]["inputs"]["protocol"] = age_pin
    n0_pin = write(root, "output/research/n0/manifest.json", case["manifest"])
    case["registration"]["inputs"]["protocol_manifest"] = n0_pin
    plan = {
        "protocol_id": probe.PROTOCOL,
        "protocol": write(root, "docs/identity-protocol.json", case["identity_protocol"]),
        "age_protocol": age_pin,
        "n0_manifest": n0_pin,
        "registration_report": write(root, "output/research/n4/report.json", case["registration"]),
        "model_manifest": write(root, "data/models/evaluation/manifest.json", case["models"]),
        "source_files": [pin(root / name, root) for name in probe.SOURCES],
        "environment": ENVIRONMENT,
    }
    case["plan"] = plan
    value = write(root, "output/research/input/study-plan.json", plan)
    return root / value["path"]


class FakeEvaluator:
    def __init__(self, behavior=None):
        self.environment = dict(ENVIRONMENT)
        self.calls = []
        self.closed = False
        self.behavior = behavior

    def evaluate(self, rgb):
        self.calls.append(rgb)
        if self.behavior:
            self.behavior(rgb)
        return {
            "face": list(FACE),
            "detector_input_size": list(rgb.size),
            "detector_to_original_scale_xy": [1.0, 1.0],
            "aligned_size": [112, 112],
            "embedding": list(VECTOR),
        }

    def close(self):
        self.closed = True


@pytest.fixture
def case(tmp_path, monkeypatch):
    case = n0_tests.case.__wrapped__(tmp_path)
    root = case["root"]
    for name in probe.SOURCES:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    # The held-out image deliberately has no file: a successful run cannot have read it.
    for index, row in enumerate(case["manifest"]["adult_images"][:2]):
        row.update(photo(root, row["path"], (50 + index * 60, 20, 100)))
    source = case["manifest"]["bridge_cases"][0]
    source["source"] = probe._image_pin(case["manifest"]["adult_images"][0])
    source["target_runs"] = [
        {**photo(root, f"output/research/sam/age-{age}.png", (age, 50, 90)), "target_age": age}
        for age in (20, 45, 70)
    ]
    source["same_age_control"]["output"] = probe._image_pin(source["target_runs"][0])
    case["registration"] = {
        "protocol_id": "agemorph3d-target-uv-v1",
        "inputs": {},
        **dict.fromkeys(
            (
                "service_ready",
                "g3_complete",
                "identity_quality_accepted",
                "holdout_age_results_opened",
                "training",
            ),
            False,
        ),
        "records": [
            {
                "source_id": "synthetic",
                "subject_id": "001",
                "target_age": row["target_age"],
                "source_age_label": 20,
                "input": probe._image_pin(row),
            }
            for row in source["target_runs"]
        ],
    }
    protocol = json.loads((ROOT / "docs/identity-evaluator-v1.json").read_text("utf-8"))
    protocol["cohort"].update(
        expected_originals=2,
        expected_generated=3,
        expected_sources=1,
        expected_unique_images=5,
        expected_original_pairs=0,
        expected_source_generated_pairs=3,
    )
    case["identity_protocol"] = protocol
    models, expectations, documents = [], {}, []
    for role, expected in probe.MODELS.items():
        body = f"synthetic {role} model; no inference".encode()
        path = root / "data/models/evaluation" / expected["filename"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        artifact_pin = pin(path, root)
        expected = {**expected, "bytes": len(body), "sha256": artifact_pin["sha256"]}
        expectations[role] = expected
        base = f"opencv/opencv_zoo/{probe.REVISION}/models/{expected['folder']}"
        url = f"https://media.githubusercontent.com/media/{base}/{expected['filename']}"
        models.append(
            {
                "role": role,
                **expected,
                "artifact": {**artifact_pin, "url": url, "resolved_url": url},
            }
        )
        for suffix, upstream in (
            ("README.md", "README.md"),
            ("LICENSE", "LICENSE"),
            ("model-lfs-pointer.txt", expected["filename"]),
        ):
            path = root / "data/models/evaluation" / f"{role}-{suffix}"
            path.write_text(f"Synthetic {role} {suffix} reference.", encoding="utf-8")
            url = f"https://raw.githubusercontent.com/{base}/{upstream}"
            documents.append({**pin(path, root), "url": url, "resolved_url": url})
    monkeypatch.setattr(probe, "MODELS", expectations)
    case["models"] = {
        "schema_version": 1,
        "revision": probe.REVISION,
        "models": models,
        "documents": documents,
        "production_enabled": False,
        "g3_complete": False,
        "legal_permission_established": False,
    }
    case["evaluator"] = FakeEvaluator()
    case["factory"] = lambda _: case["evaluator"]
    return case


def run(case):
    return probe.build_report(case["root"], freeze(case), case["factory"])


def requests(case):
    freeze(case)
    return probe._requests(
        case["root"],
        case["manifest"],
        case["registration"],
        case["plan"]["n0_manifest"],
        case["identity_protocol"]["cohort"],
    )


@pytest.mark.parametrize(
    "other, expected", [(VECTOR, 1), ([-1, *([0] * 127)], -1), ([0, 1, *([0] * 126)], 0)]
)
def test_cosine_known_vectors_and_overflow_resistant_scaling(other, expected):
    assert probe.cosine([value * 1e308 for value in VECTOR], other) == pytest.approx(expected)


@pytest.mark.parametrize(
    "values", [[1], [0] * 128, [float("nan")] * 128, [float("inf")] * 128, [True] * 128]
)
def test_invalid_embeddings_are_rejected(values):
    with pytest.raises(probe.EvaluationFailure, match="INVALID_EMBEDDING"):
        probe.embedding(values)


def test_detector_rounding_uses_actual_unequal_axis_scales_without_upscaling():
    assert probe.detector_size(1001, 777) == (320, 248)
    assert probe.detector_size(101, 73) == (101, 73)
    mapped = probe.map_face(FACE, (320, 248), (1001, 777))
    assert mapped[4] == pytest.approx(FACE[4] * 1001 / 320)
    assert mapped[5] == pytest.approx(FACE[5] * 777 / 248)
    assert mapped[5] != pytest.approx(FACE[5] * 1001 / 320)
    assert mapped[14] == FACE[14]


@pytest.mark.parametrize(
    "rows, code", [(None, "NO_FACE"), ([], "NO_FACE"), ([FACE, FACE], "MULTI_FACE")]
)
def test_face_failure_never_selects_an_arbitrary_detection(rows, code):
    with pytest.raises(probe.EvaluationFailure, match=code):
        probe.one_face(rows, (16, 16), (16, 16))


def test_invalid_landmarks_and_nonfinite_faces_are_rejected():
    invalid = list(FACE)
    invalid[4] = -1
    with pytest.raises(probe.EvaluationFailure, match="INVALID_LANDMARKS"):
        probe.map_face(invalid, (16, 16), (16, 16))
    invalid[4] = float("nan")
    with pytest.raises(probe.EvaluationFailure, match="INVALID_FACE"):
        probe.map_face(invalid, (16, 16), (16, 16))


def test_synthetic_run_closes_images_and_evaluator_preserves_flags_and_holdout(case):
    report, pairs = run(case)
    assert report["execution_status"] == "complete"
    assert report["image_counts"] == {"requested": 5, "successful": 5, "failed": 0}
    assert report["pair_counts"] == {"requested": 3, "scored": 3, "failed": 0}
    assert all(report[key] is False for key in probe.FALSE_FLAGS)
    assert report["quality_threshold"] is None
    assert report["holdout_embeddings_extracted"] is False
    assert {row["group"] for row in report["records"]} == {"development", "calibration_research"}
    assert all(pair["type"] == "source_generated_comparison" for pair in pairs)
    assert {pair["category"] for pair in pairs} == {"same_age_control", "other_condition"}
    assert case["evaluator"].closed
    for image in case["evaluator"].calls:
        with pytest.raises(ValueError, match="closed"):
            image.getpixel((0, 0))


def test_environment_mismatch_closes_before_any_image_evaluation(case):
    case["evaluator"].environment["opencv_version"] = "different"
    with pytest.raises(ValueError, match="environment"):
        run(case)
    assert case["evaluator"].closed and not case["evaluator"].calls


def test_cpu_constructor_failure_restores_prior_thread_count(monkeypatch):
    threads = [7]

    def fail(*args):
        raise RuntimeError("synthetic constructor failure")

    cv = SimpleNamespace(
        getNumThreads=lambda: threads[-1],
        setNumThreads=threads.append,
        FaceDetectorYN_create=fail,
        dnn=SimpleNamespace(DNN_BACKEND_OPENCV=3, DNN_TARGET_CPU=0),
    )
    monkeypatch.setitem(sys.modules, "cv2", cv)
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace())
    with pytest.raises(RuntimeError, match="constructor failure"):
        probe.CpuEvaluator({"detector": "fake", "identity": "fake"})
    assert threads == [7, 1, 7]


def test_source_hash_mismatch_prevents_decode_and_keeps_full_pair_denominator(case, monkeypatch):
    plan = freeze(case)
    source = case["manifest"]["bridge_cases"][0]["source"]
    (case["root"] / source["path"]).write_bytes(b"changed")
    original_decode, decoded = probe.decode_image, []

    def decode(data, *args):
        decoded.append(data)
        return original_decode(data, *args)

    monkeypatch.setattr(probe, "decode_image", decode)
    report, pairs = probe.build_report(case["root"], plan, case["factory"])
    assert len(decoded) == 4 and b"changed" not in decoded
    assert report["integrity_status"] == "failed"
    assert report["pair_counts"] == {"requested": 3, "scored": 0, "failed": 3}
    assert all(pair["score"] is None for pair in pairs)


def test_corrupt_but_correctly_pinned_image_is_an_explicit_decode_failure(case):
    source = case["manifest"]["bridge_cases"][0]["source"]
    path = case["root"] / source["path"]
    path.write_bytes(b"not a jpeg")
    source.update(pin(path, case["root"]))
    case["manifest"]["adult_images"][0].update(source)
    report, pairs = run(case)
    assert report["records"][0]["status"] == "BAD_INPUT"
    assert report["integrity_status"] == "passed"
    assert report["image_counts"]["failed"] == 1
    assert len(pairs) == 3 and all(pair["score"] is None for pair in pairs)


def test_pixel_resource_limit_rejects_before_evaluator(case, monkeypatch):
    monkeypatch.setattr(
        probe,
        "Settings",
        lambda **_: SimpleNamespace(max_image_bytes=10485760, max_image_pixels=100),
    )
    report, pairs = run(case)
    assert {record["status"] for record in report["records"]} == {"INPUT_TOO_LARGE"}
    assert not case["evaluator"].calls
    assert len(pairs) == 3 and all(pair["score"] is None for pair in pairs)


@pytest.mark.parametrize("code", ["NO_FACE", "MULTI_FACE"])
def test_evaluation_failure_remains_in_image_and_pair_denominators(case, code):
    def fail(_):
        raise probe.EvaluationFailure(code)

    case["evaluator"].behavior = fail
    report, pairs = run(case)
    assert {record["status"] for record in report["records"]} == {code}
    assert report["image_counts"]["requested"] == 5
    assert len(pairs) == 3 and all(pair["score"] is None for pair in pairs)
    assert case["evaluator"].closed


def test_late_image_drift_during_aggregation_invalidates_all_affected_scores(case, monkeypatch):
    original, calls = probe.aggregate, []
    source = case["manifest"]["bridge_cases"][0]["source"]

    def aggregate(pairs):
        result = original(pairs)
        calls.append(None)
        if len(calls) == 1:
            (case["root"] / source["path"]).write_bytes(b"late source drift")
        return result

    monkeypatch.setattr(probe, "aggregate", aggregate)
    report, pairs = run(case)
    assert len(calls) == 2
    assert report["records"][0]["status"] == "source_changed"
    assert report["records"][0]["embedding"] is None
    assert report["pair_counts"] == {"requested": 3, "scored": 0, "failed": 3}
    assert all(pair["score"] is None for pair in pairs)
    assert case["evaluator"].closed


def test_model_hash_mismatch_prevents_factory_creation(case):
    plan = freeze(case)
    artifact = case["models"]["models"][0]["artifact"]
    (case["root"] / artifact["path"]).write_bytes(b"changed model")
    created = []
    with pytest.raises(ValueError, match="Artifact"):
        probe.build_report(case["root"], plan, lambda _: created.append(True))
    assert not created


def test_late_model_drift_rejects_report_and_closes_evaluator(case):
    artifact = case["models"]["models"][0]["artifact"]

    def change(_):
        (case["root"] / artifact["path"]).write_bytes(b"late model drift")

    case["evaluator"].behavior = change
    with pytest.raises(ValueError, match="Artifact"):
        run(case)
    assert case["evaluator"].closed


def test_metadata_drift_after_scoring_rejects_report(case, monkeypatch):
    original = probe.aggregate

    def change(pairs):
        path = case["root"] / "docs/identity-protocol.json"
        path.write_text("{}", encoding="utf-8")
        return original(pairs)

    monkeypatch.setattr(probe, "aggregate", change)
    with pytest.raises(ValueError, match="Metadata pin mismatch"):
        run(case)
    assert case["evaluator"].closed


def test_source_missing_from_frozen_allowlist_is_rejected_before_factory(case):
    plan = freeze(case)
    case["plan"]["source_files"].pop()
    write(case["root"], plan.relative_to(case["root"]).as_posix(), case["plan"])
    with pytest.raises(ValueError, match="exact ten"):
        probe.build_report(case["root"], plan, case["factory"])
    assert not case["evaluator"].calls


def test_holdout_hash_cannot_be_smuggled_in_as_a_generated_output(case):
    output = case["manifest"]["bridge_cases"][0]["target_runs"][1]
    output["sha256"] = case["manifest"]["adult_images"][2]["sha256"]
    case["registration"]["records"][1]["input"] = probe._image_pin(output)
    with pytest.raises(ValueError, match="research-holdout"):
        requests(case)


def test_unknown_source_age_stays_null_and_generated_comparisons_are_not_positive(case):
    source = case["manifest"]["bridge_cases"][0]
    source["subject_id"] = "external:synthetic"
    source["source"] = photo(case["root"], "data/external/source.png", (22, 77, 88))
    source["source_age"] = {"value": None, "method": "unknown", "independently_verified": False}
    source["same_age_control"] = {"status": "not_applicable_unknown_source_age", "target_age": None}
    for row in case["registration"]["records"]:
        row["source_age_label"] = None
        row["subject_id"] = "external:synthetic"
    case["identity_protocol"]["cohort"]["expected_unique_images"] = 6
    images, pairs, _ = requests(case)
    assert images[pairs[0]["left_id"]]["source_age_label"] is None
    assert {pair["category"] for pair in pairs} == {"unknown_source_age"}
    assert all(pair["label_age_difference"] is None for pair in pairs)
    assert all(pair["type"] == "source_generated_comparison" for pair in pairs)
    assert not any("positive" in pair for pair in pairs)


def test_macro_weights_units_equally_and_retains_null_units():
    pairs = [
        {
            "type": "source_generated_comparison",
            "group": "development",
            "category": "other_condition",
            "unit": unit,
            "score": score,
        }
        for unit, score in [("a", 1.0), ("a", 1.0), ("a", 1.0), ("b", 0.0), ("c", None)]
    ]
    summary = next(row for row in probe.aggregate(pairs) if row["category"] == "other_condition")
    assert summary["requested"] == 5 and summary["scored"] == 4 and summary["null"] == 1
    assert summary["eligible_units"] == 3 and summary["effective_units"] == 2
    assert summary["macro_mean"] == 0.5  # Pooled pair mean would incorrectly be 0.75.
    assert summary["units"][-1]["mean"] is None


def test_all_failed_macro_keeps_null_rather_than_zero():
    pairs = [
        {
            "type": "original_comparison",
            "group": "development",
            "category": "same_identity_cross_age",
            "unit": "001",
            "score": None,
        }
    ]
    summary = next(
        row
        for row in probe.aggregate(pairs)
        if row["group"] == "development" and row["category"] == "same_identity_cross_age"
    )
    assert summary["macro_mean"] is None
    assert summary["eligible_units"] == 1 and summary["effective_units"] == 0


def test_negative_macro_combines_ages_inside_subject_pairs_and_keeps_empty_strata():
    pairs = [
        {
            "type": "original_comparison",
            "group": "development",
            "category": f"different_identity_{age_category}",
            "unit": unit,
            "score": score,
        }
        for unit, age_category, score in [
            ("001:002", "same_age", 1.0),
            ("001:002", "same_age", 1.0),
            ("001:002", "same_age", 1.0),
            ("001:002", "cross_age", 0.0),
            ("001:003", "cross_age", 0.0),
        ]
    ]
    summaries = probe.aggregate(pairs)
    overall = next(
        row
        for row in summaries
        if row["group"] == "development" and row["category"] == "different_identity"
    )
    # Unit means are 0.75 and 0; pooling gives 0.6, averaging age strata gives 0.5.
    assert overall["macro_mean"] == 0.375
    assert overall["requested"] == 5 and overall["scored"] == 5
    assert overall["eligible_units"] == 2 and overall["effective_units"] == 2
    assert overall["aggregation_scope"] == "all_requested_ages"
    empty = next(
        row
        for row in summaries
        if row["group"] == "development" and row["category"] == "same_identity_same_age"
    )
    assert empty["requested"] == 0 and empty["eligible_units"] == 0
    assert empty["effective_units"] == 0 and empty["macro_mean"] is None


def test_csv_keeps_every_request_and_uses_empty_fields_for_failed_scores(case):
    _, pairs, _ = requests(case)
    records = [{"status": "NO_FACE", "embedding": None}] * 5
    encoded = probe.csv_bytes(probe.score_pairs(pairs, records))
    rows = list(csv.DictReader(io.StringIO(encoded.decode("utf-8"))))
    assert len(rows) == 3
    assert all(row["score"] == "" and row["status"] == "failed" for row in rows)
    assert {row["pair_id"] for row in rows} == {"0", "1", "2"}


def test_output_refuses_existing_evidence_before_evaluation(case, monkeypatch):
    output = case["root"] / "output/research/existing"
    output.mkdir(parents=True)
    sentinel = output / "report.json"
    sentinel.write_text("preserved", encoding="utf-8")
    calls = []
    monkeypatch.setattr(probe, "build_report", lambda *args: calls.append(True))
    assert (
        probe.main(
            [
                "--root",
                str(case["root"]),
                "--study-plan",
                "missing.json",
                "--output-dir",
                "output/research/existing",
            ]
        )
        == 1
    )
    assert sentinel.read_text("utf-8") == "preserved" and not calls
