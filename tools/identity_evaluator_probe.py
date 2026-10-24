"""Bounded CPU identity diagnostics; no identity decision or quality acceptance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import sys
from contextlib import closing
from itertools import combinations
from pathlib import Path

from PIL import __version__ as pillow_version

_NEAR_PATH = Path(__file__).with_name("near_duplicate_probe.py")
_SPEC = importlib.util.spec_from_file_location("_identity_snapshot", _NEAR_PATH)
near = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(near)
metadata = near.metadata
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/src"))
from agemorph3d.config import Settings  # noqa: E402
from agemorph3d.errors import ApiError  # noqa: E402
from agemorph3d.images import decode_image  # noqa: E402

PROTOCOL = "agemorph3d-identity-evaluator-v1"
REVISION = "48b10fa505aeb51fbd127fc60a5c660040e823b7"
SOURCES = (
    *near.SOURCES,
    "tools/identity_evaluator_probe.py",
    "backend/tests/test_identity_evaluator_probe.py",
    "backend/src/agemorph3d/images.py",
    "backend/src/agemorph3d/config.py",
    "backend/src/agemorph3d/errors.py",
    "backend/src/agemorph3d/__init__.py",
)
MODELS = {
    "identity": {
        "filename": "face_recognition_sface_2021dec.onnx",
        "folder": "face_recognition_sface",
        "bytes": 38696353,
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    },
    "detector": {
        "filename": "face_detection_yunet_2023mar.onnx",
        "folder": "face_detection_yunet",
        "bytes": 232589,
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    },
}
LIMITS = {
    "image_max_bytes": 10485760,
    "image_max_pixels": 16000000,
    "model_max_bytes": 67108864,
    "report_max_bytes": 2097152,
}
EVALUATOR = {
    "revision": REVISION,
    "backend": "CPU",
    "threads": 1,
    "detector": {
        "model": "yunet_2023mar",
        "score_threshold": 0.9,
        "nms_threshold": 0.3,
        "top_k": 5000,
        "max_side": 320,
        "downscale_only": True,
        "resample": "INTER_AREA",
        "mapping": "actual resized width/height ratios back to original",
        "resize_rounding": "max(1, round(dimension * min(1, 320 / max(width, height))))",
        "multiple_faces": "Fail the image; never select the largest or highest-scoring face.",
    },
    "recognizer": "sface_2021dec",
    "embedding_dimensions": 128,
    "aligned_size": [112, 112],
    "score": "normalized_dot_no_threshold",
    "alignment": (
        "Map detector bbox and all five landmarks by actual axis ratios, "
        "then FaceRecognizerSF.alignCrop on the original EXIF-corrected BGR image."
    ),
}
FALSE_FLAGS = (
    "identity_quality_accepted",
    "independent_evaluation",
    "training_overlap_excluded",
    "legal_permission_established",
    "service_ready",
    "production_enabled",
    "g3_complete",
)
PAIR_FIELDS = (
    "pair_id",
    "type",
    "group",
    "category",
    "unit",
    "left_id",
    "right_id",
    "left_status",
    "right_status",
    "status",
    "score",
    "label_age_difference",
)


class EvaluationFailure(ValueError):
    pass


def _same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _protocol(value):
    metadata._keys(
        value,
        {
            "schema_version",
            "protocol_id",
            "frozen_on",
            "scope",
            "observations",
            "cohort",
            "evaluator",
            "limits",
            "accounting",
            "quality_threshold",
            "flags",
        },
        "Identity protocol",
    )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["protocol_id"] != PROTOCOL
        or value["quality_threshold"] is not None
    ):
        raise ValueError("Unsupported identity protocol or quality threshold.")
    if not _same(value["evaluator"], EVALUATOR) or not _same(value["limits"], LIMITS):
        raise ValueError("Evaluator algorithm or resource limits differ.")
    metadata._keys(value["flags"], {"research_only", *FALSE_FLAGS}, "Protocol flags")
    metadata._false_flags(value["flags"], FALSE_FLAGS, "Identity protocol")
    if value["flags"]["research_only"] is not True:
        raise ValueError("Research scope is required.")
    cohort = value["cohort"]
    metadata._keys(
        cohort,
        {
            "groups",
            "expected_originals",
            "expected_generated",
            "expected_sources",
            "expected_unique_images",
            "expected_original_pairs",
            "expected_source_generated_pairs",
        },
        "Cohort",
    )
    if cohort["groups"] != ["development", "calibration_research"]:
        raise ValueError("Only N0 development/calibration originals may be scored.")
    for key, count in cohort.items():
        if key != "groups":
            metadata._integer(count, key, 0, 124750 if key.endswith("pairs") else 500)
    observations = value["observations"]
    metadata._keys(
        observations,
        {
            "historical_preprocessing_exposed",
            "development_sam_outputs_previously_viewed",
            "synthetic_cpu_model_selfcheck_completed",
            "real_identity_scores_seen_before_freeze",
            "training_cohort_overlap",
        },
        "Observations",
    )
    if (
        any(
            observations[key] is not True
            for key in (
                "historical_preprocessing_exposed",
                "development_sam_outputs_previously_viewed",
                "synthetic_cpu_model_selfcheck_completed",
            )
        )
        or observations["real_identity_scores_seen_before_freeze"] is not False
    ):
        raise ValueError("Prospective score freeze and prior exposure must be explicit.")
    metadata._text(observations["training_cohort_overlap"], "Training overlap")
    metadata._keys(
        value["accounting"],
        {
            "original_pairs",
            "generated_pairs",
            "upstream_source_failures",
            "macro",
            "failures",
            "integrity",
            "output",
        },
        "Accounting",
    )
    for text in [value["scope"], value["frozen_on"], *value["accounting"].values()]:
        metadata._text(text, "Protocol explanation")


def _image_pin(value):
    return {key: value[key] for key in ("path", "sha256", "bytes")}


def _stream_pin(root, pin, limit, *, document=False):
    metadata._keys(pin, {"path", "sha256", "bytes"}, "Artifact pin")
    path = metadata._relative(root, pin["path"])
    metadata._integer(pin["bytes"], "Artifact bytes", 1, limit)
    if (
        type(pin["sha256"]) is not str
        or len(pin["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in pin["sha256"])
    ):
        raise ValueError("Artifact needs a lowercase SHA-256.")
    digest, count, parts = hashlib.sha256(), 0, []
    with path.open("rb") as stream:
        while chunk := stream.read(min(1048576, limit + 1 - count)):
            count += len(chunk)
            if count > limit or count > pin["bytes"]:
                raise ValueError("Artifact exceeds its declared size or resource bound.")
            digest.update(chunk)
            if document:
                parts.append(chunk)
    if count != pin["bytes"] or digest.hexdigest() != pin["sha256"]:
        raise ValueError(f"Artifact pin mismatch: {pin['path']}")
    if document:
        b"".join(parts).decode("utf-8")
    return path


def _models(root, manifest):
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or manifest.get("revision") != REVISION
    ):
        raise ValueError("Only the pinned official OpenCV Zoo revision is supported.")
    metadata._false_flags(
        manifest,
        ("production_enabled", "g3_complete", "legal_permission_established"),
        "Acquisition manifest",
    )
    models, artifacts = {}, []
    for item in metadata._list(manifest.get("models"), "Models", 2):
        role = item.get("role")
        if role not in MODELS or role in models:
            raise ValueError("Exactly one detector and identity model are required.")
        expected = MODELS[role]
        artifact = item.get("artifact")
        metadata._keys(
            artifact, {"url", "resolved_url", "path", "bytes", "sha256"}, "Model artifact"
        )
        if any(
            not _same(item.get(key), expected[key])
            for key in ("filename", "folder", "bytes", "sha256")
        ) or any(not _same(artifact[key], expected[key]) for key in ("bytes", "sha256")):
            raise ValueError("Model filename, size or known official hash differs.")
        url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{REVISION}/models/{expected['folder']}/{expected['filename']}"
        if (
            artifact["url"] != url
            or artifact["resolved_url"] != url
            or Path(artifact["path"]).name != expected["filename"]
        ):
            raise ValueError("Model source does not match its fixed official release.")
        model_pin = _image_pin(artifact)
        models[role] = _stream_pin(root, model_pin, LIMITS["model_max_bytes"])
        artifacts.append(model_pin)
    if set(models) != set(MODELS):
        raise ValueError("Both fixed models are required before loading.")
    documents, names = [], set()
    for item in metadata._list(manifest.get("documents"), "Model documents", 6):
        metadata._keys(item, {"url", "resolved_url", "path", "bytes", "sha256"}, "Model document")
        name = Path(item["path"]).name
        if name in names or not any(
            name == f"{role}-{suffix}"
            for role in ("identity", "detector")
            for suffix in ("README.md", "LICENSE", "model-lfs-pointer.txt")
        ):
            raise ValueError("Model source documents must be the six distinct release references.")
        names.add(name)
        for url in (item["url"], item["resolved_url"]):
            metadata._https(url)
            if not url.startswith(
                f"https://raw.githubusercontent.com/opencv/opencv_zoo/{REVISION}/models/"
            ):
                raise ValueError("Model document source revision differs.")
        doc_pin = _image_pin(item)
        _stream_pin(root, doc_pin, metadata.MAX_BYTES, document=True)
        documents.append(doc_pin)
    if len(names) != 6:
        raise ValueError("All release readmes, licenses and LFS references are required.")
    return models, artifacts, documents


def detector_size(width, height):
    ratio = min(1, 320 / max(width, height))
    return max(1, round(width * ratio)), max(1, round(height * ratio))


def map_face(row, detector_dimensions, original_dimensions):
    if (
        type(row) not in {list, tuple}
        or len(row) != 15
        or any(type(value) not in {int, float} or not math.isfinite(value) for value in row)
    ):
        raise EvaluationFailure("INVALID_FACE")
    dw, dh = detector_dimensions
    width, height = original_dimensions
    sx, sy = width / dw, height / dh
    mapped = [float(value) for value in row]
    for index in (0, 2, 4, 6, 8, 10, 12):
        mapped[index] *= sx
    for index in (1, 3, 5, 7, 9, 11, 13):
        mapped[index] *= sy
    if (
        mapped[2] <= 0
        or mapped[3] <= 0
        or not 0 <= mapped[14] <= 1
        or mapped[0] >= width
        or mapped[1] >= height
        or mapped[0] + mapped[2] <= 0
        or mapped[1] + mapped[3] <= 0
    ):
        raise EvaluationFailure("INVALID_FACE")
    points = list(zip(mapped[4:14:2], mapped[5:14:2], strict=True))
    if any(not (0 <= x < width and 0 <= y < height) for x, y in points) or len(set(points)) != 5:
        raise EvaluationFailure("INVALID_LANDMARKS")
    if (
        abs(
            (points[1][0] - points[0][0]) * (points[2][1] - points[0][1])
            - (points[1][1] - points[0][1]) * (points[2][0] - points[0][0])
        )
        <= 1e-8
    ):
        raise EvaluationFailure("INVALID_LANDMARKS")
    return mapped


def one_face(rows, detector_dimensions, original_dimensions):
    if rows is None or len(rows) == 0:
        raise EvaluationFailure("NO_FACE")
    if len(rows) != 1:
        raise EvaluationFailure("MULTI_FACE")
    return map_face(rows[0], detector_dimensions, original_dimensions)


def embedding(values):
    if (
        type(values) not in {list, tuple}
        or len(values) != 128
        or any(type(value) not in {int, float} or not math.isfinite(value) for value in values)
        or not any(values)
    ):
        raise EvaluationFailure("INVALID_EMBEDDING")
    return [float(value) for value in values]


def cosine(left, right):
    def normalized(values):
        values = embedding(values)
        scale = max(abs(value) for value in values)
        scaled = [value / scale for value in values]
        norm = math.sqrt(math.fsum(value * value for value in scaled))
        return [value / norm for value in scaled]

    return max(
        -1,
        min(1, math.fsum(a * b for a, b in zip(normalized(left), normalized(right), strict=True))),
    )


class CpuEvaluator:
    def __init__(self, model_paths):
        import cv2
        import numpy as np

        self.cv, self.np = cv2, np
        self.prior_threads = cv2.getNumThreads()
        self.detector = self.recognizer = None
        try:
            cv2.setNumThreads(1)
            self.detector = cv2.FaceDetectorYN_create(
                str(model_paths["detector"]),
                "",
                (320, 320),
                0.9,
                0.3,
                5000,
                cv2.dnn.DNN_BACKEND_OPENCV,
                cv2.dnn.DNN_TARGET_CPU,
            )
            self.recognizer = cv2.FaceRecognizerSF_create(
                str(model_paths["identity"]), "", cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU
            )
            self.environment = {
                "python_version": sys.version.split()[0],
                "pillow_version": pillow_version,
                "opencv_version": cv2.__version__,
                "numpy_version": np.__version__,
            }
        except Exception:
            self.close()
            raise

    def evaluate(self, rgb):
        cv, np = self.cv, self.np
        bgr = np.asarray(rgb, dtype=np.uint8)[:, :, ::-1].copy()
        width, height = rgb.size
        dimensions = detector_size(width, height)
        resized = (
            bgr
            if dimensions == rgb.size
            else cv.resize(bgr, dimensions, interpolation=cv.INTER_AREA)
        )
        self.detector.setInputSize(dimensions)
        _, detected = self.detector.detect(resized)
        face = one_face(None if detected is None else detected.tolist(), dimensions, rgb.size)
        crop = self.recognizer.alignCrop(bgr, np.asarray(face, dtype=np.float32))
        if crop.shape != (112, 112, 3):
            raise EvaluationFailure("INVALID_ALIGNMENT")
        feature = self.recognizer.feature(crop)
        if feature.shape not in {(1, 128), (128,)}:
            raise EvaluationFailure("INVALID_EMBEDDING")
        return {
            "face": face,
            "detector_input_size": list(dimensions),
            "detector_to_original_scale_xy": [width / dimensions[0], height / dimensions[1]],
            "aligned_size": [112, 112],
            "embedding": embedding(feature.reshape(-1).tolist()),
        }

    def close(self):
        self.detector = self.recognizer = None
        self.cv.setNumThreads(self.prior_threads)


def _requests(root, n0, registration, n0_pin, cohort):
    if (
        registration.get("protocol_id") != "agemorph3d-target-uv-v1"
        or registration.get("inputs", {}).get("protocol_manifest") != n0_pin
    ):
        raise ValueError("N4 must bind the same frozen N0 manifest.")
    metadata._false_flags(
        registration,
        (
            "service_ready",
            "g3_complete",
            "identity_quality_accepted",
            "holdout_age_results_opened",
            "training",
        ),
        "N4 report",
    )
    holdout = [row for row in n0["adult_images"] if row["group"] == "evaluation_research_holdout"]
    held_paths, held_hashes = {row["path"] for row in holdout}, {row["sha256"] for row in holdout}
    images, by_path, original_ids, sources, expected_outputs = [], {}, [], {}, {}

    def add(pin, role, subject, group, label):
        metadata._relative(root, pin["path"])
        metadata._integer(pin["bytes"], "Image bytes", 1, 1024**3)
        if pin["path"] in held_paths or pin["sha256"] in held_hashes:
            raise ValueError("A requested image overlaps a research-holdout original.")
        if pin["path"] in by_path:
            index = by_path[pin["path"]]
            if images[index]["source"] != pin:
                raise ValueError("Conflicting image pins share a path.")
            if role == "generated":
                raise ValueError(
                    "Generated requests must have distinct paths, "
                    "separate from originals and anchors."
                )
            images[index]["roles"].append(role)
            return index
        index = len(images)
        images.append(
            {
                "image_id": index,
                "source": pin,
                "roles": [role],
                "subject_id": subject,
                "group": group,
                "source_age_label": label,
            }
        )
        by_path[pin["path"]] = index
        return index

    for row in n0["adult_images"]:
        if row["group"] in cohort["groups"]:
            original_ids.append(
                add(_image_pin(row), "original", row["subject_id"], row["group"], row["source_age"])
            )
    for case in n0["bridge_cases"]:
        if case["source_status"] != "passed":
            continue
        source_id, label = case["sample_id"], case["source_age"]["value"]
        index = add(_image_pin(case["source"]), "source", case["subject_id"], "development", label)
        if (
            images[index]["group"] != "development"
            or images[index]["subject_id"] != case["subject_id"]
            or images[index]["source_age_label"] != label
            or source_id in sources
        ):
            raise ValueError("Source anchor identity, age or development provenance differs.")
        sources[source_id] = (index, label)
        outputs = list(case.get("target_runs", []))
        control = case["same_age_control"]
        if control["status"] in {"generated", "reused_existing"}:
            outputs.append({**control["output"], "target_age": control["target_age"]})
        for output in outputs:
            target = metadata._integer(output["target_age"], "SAM target condition", 20, 70)
            key, pin = (source_id, target), _image_pin(output)
            if key in expected_outputs and expected_outputs[key] != pin:
                raise ValueError("Conflicting N0 source target outputs.")
            expected_outputs[key] = pin
    pair_requests = []
    for group in cohort["groups"]:
        for left, right in combinations(
            (index for index in original_ids if images[index]["group"] == group), 2
        ):
            a, b = images[left], images[right]
            same_identity, same_age = (
                a["subject_id"] == b["subject_id"],
                a["source_age_label"] == b["source_age_label"],
            )
            unit = (
                a["subject_id"]
                if same_identity
                else ":".join(sorted((a["subject_id"], b["subject_id"])))
            )
            identity_category = "same_identity" if same_identity else "different_identity"
            age_category = "same_age" if same_age else "cross_age"
            category = f"{identity_category}_{age_category}"
            pair_requests.append(
                {
                    "type": "original_comparison",
                    "group": group,
                    "category": category,
                    "unit": unit,
                    "left_id": left,
                    "right_id": right,
                    "label_age_difference": abs(a["source_age_label"] - b["source_age_label"]),
                }
            )
    original_pair_count = len(pair_requests)
    seen = set()
    for row in metadata._list(registration.get("records"), "N4 generated records", 500):
        source_id, target = row.get("source_id"), row.get("target_age")
        metadata._integer(target, "N4 target", 20, 70)
        key = (source_id, target)
        if (
            key not in expected_outputs
            or key in seen
            or row.get("input") != expected_outputs[key]
            or row.get("source_age_label") != sources[source_id][1]
            or row.get("subject_id") != images[sources[source_id][0]]["subject_id"]
        ):
            raise ValueError(
                "N4 generated requests differ from existing N0 outputs or source labels."
            )
        seen.add(key)
        left, label = sources[source_id]
        right = add(row["input"], "generated", images[left]["subject_id"], "development", label)
        category = (
            "unknown_source_age"
            if label is None
            else "same_age_control"
            if label == target
            else "other_condition"
        )
        images[right].update(source_id=source_id, target_condition=target)
        pair_requests.append(
            {
                "type": "source_generated_comparison",
                "group": "development",
                "category": category,
                "unit": source_id,
                "left_id": left,
                "right_id": right,
                "label_age_difference": None if label is None else abs(label - target),
            }
        )
    actual = {
        "expected_originals": len(original_ids),
        "expected_generated": len(seen),
        "expected_sources": len(sources),
        "expected_unique_images": len(images),
        "expected_original_pairs": original_pair_count,
        "expected_source_generated_pairs": len(pair_requests) - original_pair_count,
    }
    if seen != set(expected_outputs) or any(actual[key] != cohort[key] for key in actual):
        raise ValueError("Requested cohort or pair counts differ from the frozen protocol.")
    for index, request in enumerate(pair_requests):
        request["pair_id"] = index
    return images, pair_requests, actual


def score_pairs(requests, records):
    pairs = []
    for request in requests:
        left, right = records[request["left_id"]], records[request["right_id"]]
        score = (
            cosine(left["embedding"], right["embedding"])
            if left["status"] == right["status"] == "ok"
            else None
        )
        pairs.append(
            {
                **request,
                "left_status": left["status"],
                "right_status": right["status"],
                "status": "scored" if score is not None else "failed",
                "score": score,
            }
        )
    return pairs


def aggregate(pairs):
    # Keep zero-request strata explicit; combined negatives are a second view of
    # the same requests, not additional pairs in the global denominator.
    strata = {
        ("original_comparison", group, category): {}
        for group in ("development", "calibration_research")
        for category in (
            "same_identity_same_age",
            "same_identity_cross_age",
            "different_identity_same_age",
            "different_identity_cross_age",
            "different_identity",
        )
    }
    strata.update(
        {
            ("source_generated_comparison", "development", category): {}
            for category in ("same_age_control", "other_condition", "unknown_source_age")
        }
    )
    for pair in pairs:
        categories = [pair["category"]]
        if pair["type"] == "original_comparison" and pair["category"].startswith(
            "different_identity_"
        ):
            categories.append("different_identity")
        for category in categories:
            key = (pair["type"], pair["group"], category)
            unit = strata.setdefault(key, {}).setdefault(
                pair["unit"], {"requested": 0, "scores": []}
            )
            unit["requested"] += 1
            if pair["score"] is not None:
                unit["scores"].append(pair["score"])
    results = []
    for (kind, group, category), units in sorted(strata.items()):
        details = [
            {
                "unit": key,
                "requested": item["requested"],
                "scored": len(item["scores"]),
                "null": item["requested"] - len(item["scores"]),
                "mean": math.fsum(item["scores"]) / len(item["scores"]) if item["scores"] else None,
            }
            for key, item in sorted(units.items())
        ]
        means = [item["mean"] for item in details if item["mean"] is not None]
        results.append(
            {
                "type": kind,
                "group": group,
                "category": category,
                "aggregation_scope": "all_requested_ages"
                if category == "different_identity"
                else "category",
                "requested": sum(item["requested"] for item in details),
                "scored": sum(item["scored"] for item in details),
                "null": sum(item["null"] for item in details),
                "eligible_units": len(details),
                "effective_units": len(means),
                "macro_mean": math.fsum(means) / len(means) if means else None,
                "units": details,
            }
        )
    return results


def build_report(root: Path, plan_path: Path, evaluator_factory=CpuEvaluator):
    root, plan_path = Path(root).resolve(strict=True), Path(plan_path).resolve(strict=True)
    if not plan_path.is_relative_to(root) or plan_path.suffix != ".json":
        raise ValueError("Study plan must be workspace JSON metadata.")
    raw = metadata._read(plan_path)
    plan = metadata._json(raw)
    metadata._keys(
        plan,
        {
            "protocol_id",
            "protocol",
            "age_protocol",
            "n0_manifest",
            "registration_report",
            "model_manifest",
            "source_files",
            "environment",
        },
        "Study plan",
    )
    if plan["protocol_id"] != PROTOCOL:
        raise ValueError("Unsupported identity study plan.")
    metadata._keys(
        plan["environment"],
        {"python_version", "pillow_version", "opencv_version", "numpy_version"},
        "Environment",
    )
    for value in plan["environment"].values():
        metadata._text(value, "Environment version", 100)
    inputs = metadata._Inputs(root)
    inputs.read(
        {
            "path": plan_path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    )
    roles = ("protocol", "age_protocol", "n0_manifest", "registration_report", "model_manifest")
    values = {role: metadata._json(inputs.read(plan[role])) for role in roles}
    if len({plan[role]["path"] for role in roles}) != len(roles):
        raise ValueError("Input metadata roles must be distinct.")
    inputs.many(plan["source_files"], "Source files")
    source_pins = {pin["path"]: pin for pin in plan["source_files"]}
    if set(source_pins) != set(SOURCES):
        raise ValueError("The exact ten implementation and dependency sources must be pinned.")
    actual_root = Path(__file__).resolve().parents[1]
    for name in SOURCES:
        if (
            source_pins[name]["sha256"]
            != hashlib.sha256(metadata._read(actual_root / name)).hexdigest()
        ):
            raise ValueError("Study plan differs from the running source/dependency files.")
    _protocol(values["protocol"])
    n0 = values["n0_manifest"]
    metadata._n0(values["age_protocol"], n0, n0.get("summary"), plan["age_protocol"])
    images, requests, counts = _requests(
        root, n0, values["registration_report"], plan["n0_manifest"], values["protocol"]["cohort"]
    )
    model_paths, model_pins, doc_pins = _models(root, values["model_manifest"])
    records, evaluator = [], None
    settings = Settings(
        max_image_bytes=LIMITS["image_max_bytes"], max_image_pixels=LIMITS["image_max_pixels"]
    )
    try:
        evaluator = evaluator_factory(model_paths)
        if not _same(evaluator.environment, plan["environment"]):
            raise ValueError("Running evaluator environment differs from the frozen plan.")
        for image in images:
            initial, snapshot = near._snapshot(root, image["source"])
            record = {
                **image,
                "status": initial["verification"],
                "initial_source_check": initial,
                "embedding": None,
            }
            if snapshot is not None:
                try:
                    suffix = Path(image["source"]["path"]).suffix.lower()
                    media = {
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".png": "image/png",
                        ".webp": "image/webp",
                    }[suffix]
                    with closing(decode_image(snapshot, media, settings)) as rgb:
                        result = evaluator.evaluate(rgb)
                        face = map_face(result["face"], rgb.size, rgb.size)
                        if result["aligned_size"] != [112, 112]:
                            raise EvaluationFailure("INVALID_ALIGNMENT")
                        record.update(
                            status="ok",
                            width=rgb.width,
                            height=rgb.height,
                            **{
                                key: result[key]
                                for key in (
                                    "detector_input_size",
                                    "detector_to_original_scale_xy",
                                    "aligned_size",
                                )
                            },
                            face=face,
                            embedding=embedding(result["embedding"]),
                        )
                except ApiError as error:
                    record["status"] = error.code
                except EvaluationFailure as error:
                    record["status"] = str(error)
                except Exception as error:
                    record["status"] = "EVALUATOR_FAILED"
                    record["failure_type"] = type(error).__name__
            records.append(record)
        pairs = score_pairs(requests, records)
        summaries = aggregate(pairs)
        changed, integrity = False, True
        for record in records:
            final, _ = near._snapshot(root, record["source"])
            record["final_source_check"] = final
            record["source_changed"] = final != record["initial_source_check"]
            if record["source_changed"]:
                record["status_before_source_change"] = record["status"]
                record.update(status="source_changed", embedding=None)
                changed = True
            integrity &= (
                final["matches_declared"]
                and record["initial_source_check"]["matches_declared"]
                and not record["source_changed"]
            )
        if changed:
            pairs = score_pairs(requests, records)
            summaries = aggregate(pairs)
        _models(root, values["model_manifest"])
        inputs.verify()
        environment = dict(evaluator.environment)
    finally:
        if evaluator is not None:
            evaluator.close()
    successful = sum(record["status"] == "ok" for record in records)
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL,
        "integrity_status": "passed" if integrity else "failed",
        "execution_status": "complete"
        if successful == len(records) and integrity
        else "completed_with_failures",
        "research_only": True,
        **dict.fromkeys(FALSE_FLAGS, False),
        "quality_threshold": None,
        "images_or_crops_written": False,
        "holdout_embeddings_extracted": False,
        "models_closed": True,
        "environment": environment,
        "inputs": [inputs.pins[path] for path in sorted(inputs.pins)],
        "model_pins": model_pins,
        "model_document_pins": doc_pins,
        "cohort_counts": counts,
        "image_counts": {
            "requested": len(records),
            "successful": successful,
            "failed": len(records) - successful,
        },
        "pair_counts": {
            "requested": len(pairs),
            "scored": sum(pair["score"] is not None for pair in pairs),
            "failed": sum(pair["score"] is None for pair in pairs),
        },
        "records": records,
        "aggregates": summaries,
        "upstream_source_failures": [
            {
                "sample_id": case["sample_id"],
                "source_status": case["source_status"],
                "error_code": case.get("error_code"),
            }
            for case in n0["bridge_cases"]
            if case["source_status"] != "passed"
        ],
        "final_source_check_phase": "after_all_pair_scoring_and_aggregation",
        "source_age_semantics": (
            "Research filename/source labels only; unknown remains null; no API SourceAge created."
        ),
        "summary_verification": (
            "Recomputed from pinned N0 manifest metadata, without a separate summary report pin."
        ),
        "limits": [
            "No threshold, FAR/EER, identity decision, age truth or G3 acceptance.",
            "Training cohort overlap, domain validity and legal permission remain unestablished.",
        ],
    }
    return report, pairs


def csv_bytes(pairs):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=PAIR_FIELDS, lineterminator="\n")
    writer.writeheader()
    for pair in pairs:
        row = {key: pair[key] for key in PAIR_FIELDS}
        row["score"] = "" if pair["score"] is None else format(pair["score"], ".17g")
        writer.writerow(row)
    return stream.getvalue().encode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        output = metadata._relative(root, args.output_dir)
        allowed = (root / "output/research").resolve()
        if (
            not output.is_relative_to(allowed)
            or output == allowed
            or not allowed.is_relative_to(root)
        ):
            raise ValueError("Output must be a new descendant of workspace output/research.")
        if output.exists():
            raise FileExistsError("Output already exists; prior evidence is preserved.")
        plan = (
            args.study_plan
            if args.study_plan.is_absolute()
            else metadata._relative(root, args.study_plan.as_posix())
        )
        report, pairs = build_report(root, plan)
        encoded_pairs = csv_bytes(pairs)
        report["pairs_csv"] = {
            "path": (output / "pairs.csv").relative_to(root).as_posix(),
            "bytes": len(encoded_pairs),
            "sha256": hashlib.sha256(encoded_pairs).hexdigest(),
        }
        encoded_report = (
            json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        ).encode("utf-8")
        if len(encoded_report) > LIMITS["report_max_bytes"]:
            raise ValueError("Report exceeds the frozen 2 MiB limit; nothing was published.")
        output.mkdir(parents=True, exist_ok=False)
        for name, raw in (("pairs.csv", encoded_pairs), ("report.json", encoded_report)):
            with (output / name).open("xb") as stream:
                stream.write(raw)
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "integrity_status",
                        "execution_status",
                        "image_counts",
                        "pair_counts",
                    )
                }
            )
        )
        return 0 if report["execution_status"] == "complete" else 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
