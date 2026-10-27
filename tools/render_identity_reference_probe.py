"""Inspect a frozen photo identity reference on saved original-static render features."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ID = "agemorph3d-render-identity-reference-v1"
ROLES = (
    "protocol",
    "n0_manifest",
    "photo_report",
    "reference_report",
    "reference_verification",
    "render_report",
    "render_verification",
    "capture_report",
    "source_reset_report",
)
SOURCES = (
    "tools/render_identity_reference_probe.py",
    "backend/tests/test_render_identity_reference_probe.py",
    "tools/identity_calibration_probe.py",
)
CONFIGURATIONS = tuple(
    f"{material}/{view}/{background}"
    for material in ("MASK", "BLEND")
    for view in ("front", "side")
    for background in ("black", "white")
)
LIMIT = 8 * 1024**2
MAX_FILES = 32
MAX_RECORDS = 1000
MAX_PAIRS = 32768
REPLICATES = 1000
SEED = 20261027
COMMON_CLOSED = (
    "identity_quality_accepted",
    "independent_evaluation",
    "training_overlap_excluded",
    "legal_permission_established",
    "service_ready",
    "production_enabled",
    "g3_complete",
)
FLAGS = {
    "research_only": True,
    **dict.fromkeys(
        (
            "new_model_inference",
            "reference_threshold_reselected",
            "render_threshold_calibrated",
            "holdout_embeddings_extracted",
            "human_review_completed",
            "identity_quality_accepted",
            "age_quality_accepted",
            "independent_evaluation",
            "training_overlap_excluded",
            "legal_permission_established",
            "service_ready",
            "production_enabled",
            "g3_complete",
        ),
        False,
    ),
}


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _loaded_hash(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("Implementation exceeds its byte bound.")
    return _hash(raw)


LOADED_CODE_SHA256 = _loaded_hash(__file__)
_spec = importlib.util.spec_from_file_location("_render_reference_integrity", ROOT / SOURCES[2])
integrity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(integrity)
runtime_fingerprint = integrity.runtime_fingerprint


def _json(raw):
    value = integrity._json(raw)
    pending, visited = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if depth > 64 or visited > 1_000_000:
            raise ValueError("Metadata structure exceeds its bound.")
        if isinstance(item, dict):
            pending.extend((x, depth + 1) for x in item.values())
        elif isinstance(item, list):
            pending.extend((x, depth + 1) for x in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Nonfinite metadata number.")
    return value


def _list(value, maximum=MAX_RECORDS):
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(not isinstance(item, dict) for item in value)
    ):
        raise ValueError("Invalid bounded object list.")
    return value


def _pin(value):
    """Validate a reference only; large model/GLB references are never opened."""
    if not isinstance(value, dict) or not {"path", "bytes", "sha256"} <= value.keys():
        raise ValueError("Missing metadata reference pin.")
    name = integrity._text(value["path"], 2048)
    if (
        "\\" in name
        or ":" in name
        or Path(name).is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("Pinned path must be workspace relative.")
    size = integrity._integer(value["bytes"], 0, 1024**3)
    if (
        not isinstance(value["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise ValueError("Invalid SHA256 reference.")
    return {"path": name, "bytes": size, "sha256": value["sha256"]}


class Inputs:
    """Exact metadata/source read closure with explicit eight-MiB per-file budget."""

    def __init__(self, root, pins):
        self.root, self.pins = Path(root).resolve(), {}
        for value in _list(pins, MAX_FILES):
            pin = _pin(value)
            if pin["bytes"] > LIMIT or pin["path"] in self.pins:
                raise ValueError("Duplicate or oversized frozen input.")
            integrity._path(self.root, pin["path"])
            self.pins[pin["path"]] = pin
        if sum(pin["bytes"] for pin in self.pins.values()) > 64 * 1024**2:
            raise ValueError("Total frozen metadata budget exceeded.")

    def read(self, value):
        pin = _pin(value)
        if self.pins.get(pin["path"]) != pin:
            raise ValueError("Input is outside the exact freeze.")
        with integrity._path(self.root, pin["path"]).open("rb") as stream:
            raw = stream.read(pin["bytes"] + 1)
        if len(raw) != pin["bytes"] or _hash(raw) != pin["sha256"]:
            raise ValueError("Frozen input changed: " + pin["path"])
        return raw

    def recheck(self):
        for pin in self.pins.values():
            self.read(pin)


def _contains(values, pin):
    return _pin(pin) in [_pin(row) for row in _list(values)]


def _closed(value, keys=COMMON_CLOSED, quality=True):
    if not isinstance(value, dict) or value.get("research_only") is not True:
        raise ValueError("Evidence must be explicitly research-only.")
    if any(value.get(key) is not False for key in keys):
        raise ValueError("Evidence cannot grant qualification.")
    if quality and value.get("quality_threshold", 1) is not None:
        raise ValueError("Quality qualification threshold must remain null.")
    if any(
        item is not False
        for key, item in value.items()
        if (key.endswith("_accepted") or key in {"years_calibrated", "human_review_completed"})
    ):
        raise ValueError("Historical evidence contains an open qualification flag.")


def _feature(value):
    if not isinstance(value, list) or len(value) != 128:
        raise ValueError("Saved embedding must have 128 values.")
    if any(type(x) not in {int, float} or abs(x) > 1e300 or not math.isfinite(x) for x in value):
        raise ValueError("Invalid finite saved embedding.")
    return integrity._embed(value)


def _scored_record(record):
    status = integrity._text(record.get("status"), 100)
    if status == "ok":
        embedding = _feature(record.get("embedding"))
    else:
        if record.get("embedding") is not None:
            raise ValueError("Failed embedding must remain null.")
        embedding = None
    source = _pin(record.get("source"))
    if record.get("source_changed") is not False:
        raise ValueError("Changed source evidence is prohibited.")
    for phase in ("initial_source_check", "final_source_check"):
        if record.get(phase) != {**source, "verification": "verified", "matches_declared": True}:
            raise ValueError("Historical image integrity evidence differs.")
    return embedding


def validate_protocol(protocol):
    reference, cohort = protocol.get("reference", {}), protocol.get("cohort", {})
    bootstrap = protocol.get("bootstrap", {})
    threshold = reference.get("threshold")
    if (
        protocol.get("schema_version") != 1
        or protocol.get("protocol_id") != PROTOCOL_ID
        or protocol.get("roles") != list(ROLES)
        or reference.get("policy_id") != "saved-photo-threshold-no-retuning-v1"
        or type(threshold) not in {float, int}
        or not -1 <= threshold <= 1
        or cohort.get("configurations") != list(CONFIGURATIONS)
        or cohort.get("group") != "development"
        or protocol.get("statistics", {}).get("policy_id") != "directed-render-photo-comparisons-v1"
        or bootstrap.get("policy_id") != "full-subject-multiplicity-v1"
        or bootstrap.get("replicates") != REPLICATES
        or bootstrap.get("seed") != SEED
        or bootstrap.get("metrics") != list(integrity.METRICS)
        or protocol.get("quality_threshold", 1) is not None
    ):
        raise ValueError("Unsupported fixed reference/statistics protocol.")
    flags = protocol.get("flags")
    if not isinstance(flags, dict) or any(
        flags.get(key) is not value for key, value in FLAGS.items()
    ):
        raise ValueError("Protocol research qualification flags differ.")
    return float(threshold)


def _n0(n0):
    _closed(n0, ("training_use", "service_ready", "g3_complete"), quality=False)
    if n0.get("protocol_id") != "agemorph3d-age-research-v1":
        raise ValueError("Unsupported N0 manifest.")
    identities, originals, hash_groups = {}, {}, {}
    for item in _list(n0.get("identities")):
        subject, group = integrity._subject(item.get("subject_id")), item.get("group")
        if subject in identities or group not in {
            "development",
            "calibration_research",
            "evaluation_research_holdout",
        }:
            raise ValueError("Duplicate or cross-group N0 identity.")
        identities[subject] = group
    held_paths, held_hashes = set(), set()
    for item in _list(n0.get("adult_images")):
        pin, subject = _pin(item), integrity._subject(item.get("subject_id"))
        group = item.get("group")
        label = integrity._integer(item.get("source_age"), 20, 70)
        if identities.get(subject) != group or pin["path"] in originals:
            raise ValueError("N0 source identity/group or unique path differs.")
        if hash_groups.setdefault(pin["sha256"], group) != group:
            raise ValueError("Exact image hash leaks across groups.")
        originals[pin["path"]] = {
            "source": pin,
            "subject_id": subject,
            "group": group,
            "source_age_label": label,
        }
        if group == "evaluation_research_holdout":
            held_paths.add(pin["path"])
            held_hashes.add(pin["sha256"])
    cases, case_ids = {}, set()
    for case in _list(n0.get("bridge_cases")):
        source_id = integrity._subject(case.get("sample_id"))
        if source_id in case_ids:
            raise ValueError("Duplicate N0 source case.")
        case_ids.add(source_id)
        if case.get("source_status") == "passed":
            cases[source_id] = case
    return originals, held_paths, held_hashes, cases


def _reject_holdout(pin, held_paths, held_hashes):
    if pin["path"] in held_paths or pin["sha256"] in held_hashes:
        raise ValueError("Held-out image or alias cannot enter saved predictions.")


def _photos(report, originals, held_paths, held_hashes):
    _closed(report)
    if (
        report.get("protocol_id") != "agemorph3d-identity-evaluator-v1"
        or report.get("integrity_status") != "passed"
        or report.get("models_closed") is not True
        or report.get("holdout_embeddings_extracted") is not False
    ):
        raise ValueError("Photo report is not closed, intact identity evidence.")
    photos, ids, paths, successful = {}, set(), set(), 0
    records = _list(report.get("records"))
    for record in records:
        pin = _pin(record.get("source"))
        _reject_holdout(pin, held_paths, held_hashes)
        image_id = integrity._integer(record.get("image_id"), 0, MAX_RECORDS)
        if (
            image_id in ids
            or pin["path"] in paths
            or record.get("group") not in {"development", "calibration_research"}
        ):
            raise ValueError("Duplicate photo record or invalid group.")
        ids.add(image_id)
        paths.add(pin["path"])
        roles = record.get("roles")
        if (
            not isinstance(roles, list)
            or set(roles) not in ({"original"}, {"original", "source"}, {"source"}, {"generated"})
            or len(roles) != len(set(roles))
        ):
            raise ValueError("Unsupported saved photo role.")
        feature = _scored_record(record)
        successful += feature is not None
        if "original" in roles:
            expected = originals.get(pin["path"])
            if (
                expected is None
                or expected["group"] == "evaluation_research_holdout"
                or any(record.get(key) != value for key, value in expected.items())
            ):
                raise ValueError("Original photo is not bound to N0.")
            photos[pin["path"]] = {**record, "feature": feature}
        elif pin["path"] in originals:
            raise ValueError("N0 photo cannot be relabelled as generated/source-only.")
    allowed = {
        name for name, item in originals.items() if item["group"] != "evaluation_research_holdout"
    }
    if (
        set(photos) != allowed
        or ids != set(range(len(records)))
        or report.get("image_counts")
        != {
            "requested": len(records),
            "successful": successful,
            "failed": len(records) - successful,
        }
    ):
        raise ValueError("Photo requested/failed inventory differs.")
    return photos


def _reference(metadata, roles, threshold):
    report, verification = metadata["reference_report"], metadata["reference_verification"]
    _closed(report)
    if (
        report.get("protocol_id") != "agemorph3d-identity-calibration-v1"
        or report.get("development_candidate_threshold") != threshold
        or report.get("development_selection", {}).get("threshold") != threshold
        or report.get("calibration_curve_computed") is not False
        or report.get("calibration_threshold_retuned") is not False
        or report.get("roles", {}).get("identity_report") != roles["photo_report"]
        or report.get("roles", {}).get("n0_manifest") != roles["n0_manifest"]
        or any(
            not _contains(report.get("inputs"), roles[key])
            for key in ("photo_report", "n0_manifest")
        )
        or verification.get("status") != "passed"
        or not _contains(verification.get("artifacts"), roles["reference_report"])
        or any(
            not _contains(verification.get("inputs"), roles[key])
            for key in ("photo_report", "n0_manifest")
        )
    ):
        raise ValueError("Saved fixed reference or verification binding differs.")
    for key in (
        "identity_quality_accepted",
        "independent_evaluation",
        "production_enabled",
        "g3_complete",
    ):
        if verification.get(key) is not False:
            raise ValueError("Reference verification cannot grant qualification.")


def _sources(reset, cases, originals, photos, held_paths, held_hashes):
    _closed(
        reset,
        (
            "service_ready",
            "g3_complete",
            "identity_quality_accepted",
            "new_model_inference",
            "holdout_age_results_opened",
        ),
        quality=False,
    )
    if reset.get("protocol_id") != "agemorph3d-source-reset-v1":
        raise ValueError("Unsupported source-reset provenance.")
    records, sources, all_sources, subjects = _list(reset.get("records")), {}, {}, set()
    for record in records:
        source_id = integrity._subject(record.get("sample_id"))
        case = cases.get(source_id)
        pin = _pin(record.get("input"))
        _reject_holdout(pin, held_paths, held_hashes)
        if (
            source_id in all_sources
            or case is None
            or record.get("status") != "ok"
            or any(
                record.get(key) != case.get(case_key)
                for key, case_key in (
                    ("input", "source"),
                    ("subject_id", "subject_id"),
                    ("group", "group"),
                )
            )
            or record.get("source_age")
            != {"value": None, "method": "unknown", "calibration_id": None}
        ):
            raise ValueError("Original static source is not bound to its N0 case.")
        if record.get("label_source_age") != case.get("source_age", {}).get("value") or record.get(
            "research_source_age"
        ) != case.get("source_age"):
            raise ValueError("Research source label differs.")
        all_sources[source_id] = record
        if record.get("label_source_age") is None:
            continue
        expected = originals.get(pin["path"])
        if (
            expected is None
            or expected["source"] != pin
            or expected["group"] != "development"
            or (
                expected["subject_id"] != record.get("subject_id")
                or expected["source_age_label"] != record.get("label_source_age")
            )
        ):
            raise ValueError("Known render source must be an exact N0 development original.")
        subject = expected["subject_id"]
        if subject in subjects:
            raise ValueError("Multiple source photos for one identity are outside this protocol.")
        subjects.add(subject)
        sources[source_id] = {"subject_id": subject, "photo": photos[pin["path"]], "reset": record}
    if set(all_sources) != set(cases) or len(sources) < 2:
        raise ValueError("Complete original-source inventory and distinct identities are required.")
    return sources, all_sources


def _frames(metadata, roles, sources, all_sources, held_paths, held_hashes):
    capture, report, verification = (
        metadata[key] for key in ("capture_report", "render_report", "render_verification")
    )
    _closed(capture)
    _closed(report)
    if (
        capture.get("protocol_id") != "agemorph3d-render-domain-v1"
        or capture.get("status") != "passed"
        or capture.get("input_integrity") != "passed"
        or report.get("protocol_id") != "agemorph3d-render-domain-v1"
        or report.get("stage") != "identity"
        or report.get("integrity_status") != "passed"
        or report.get("models_closed") is not True
        or report.get("holdout_predictions_extracted") is not False
        or verification.get("status") != "passed"
        or any(
            not _contains(verification.get("artifacts"), roles[key])
            for key in ("render_report", "capture_report")
        )
        or any(
            not _contains(report.get("inputs"), roles[key])
            for key in ("capture_report", "n0_manifest", "source_reset_report")
        )
        or any(
            not _contains(capture.get("inputs"), roles[key])
            for key in ("n0_manifest", "source_reset_report")
        )
    ):
        raise ValueError("Render/capture historical evidence bindings differ.")
    if any(verification.get(key) is not False for key in ("production_enabled", "g3_complete")):
        raise ValueError("Render verification cannot grant qualification.")
    assets = {}
    for asset in _list(capture.get("assets")):
        asset_id = integrity._text(asset.get("asset_id"), 180)
        if asset_id in assets:
            raise ValueError("Duplicate captured asset.")
        assets[asset_id] = asset
        if asset.get("role") == "original_static_3d":
            source_id = asset.get("source_id")
            source = all_sources.get(source_id)
            if (
                source is None
                or asset_id != source_id + "--original"
                or (
                    asset.get("target_age") is not None
                    or asset.get("category") != "baseline"
                    or asset.get("source_age_label") != source.get("label_source_age")
                    or asset.get("glb") != source.get("artifacts", {}).get("glb")
                    or asset.get("atlas") != source.get("artifacts", {}).get("atlas")
                    or not isinstance(source.get("source_frame"), dict)
                    or not source["source_frame"]
                    or asset.get("source_frame") != source["source_frame"]
                )
            ):
                raise ValueError("Captured original assets differ from source-reset provenance.")
        elif asset.get("role") != "sam_texture_static_3d":
            raise ValueError("Unsupported captured asset role.")
        elif asset.get("source_id") not in all_sources:
            raise ValueError("SAM inventory contains an unknown source.")
    if {
        asset["source_id"] for asset in assets.values() if asset["role"] == "original_static_3d"
    } != set(all_sources):
        raise ValueError("Capture must retain every original source, including excluded sources.")
    captured = {}
    for frame in _list(capture.get("frames")):
        key = integrity._text(frame.get("frame_id"), 256)
        if key in captured or frame.get("asset_id") not in assets or frame.get("status") != "ok":
            raise ValueError("Duplicate, failed or unknown captured frame.")
        asset = assets[frame["asset_id"]]
        if (
            frame.get("config_id") not in CONFIGURATIONS
            or any(
                frame.get(name) != asset.get(name)
                for name in (
                    "asset_id",
                    "source_id",
                    "sample_id",
                    "role",
                    "source_age_label",
                    "target_age",
                    "category",
                )
            )
            or key != frame["asset_id"] + "::" + frame["config_id"]
        ):
            raise ValueError("Capture frame/asset/configuration binding differs.")
        material, view, background = frame["config_id"].split("/")
        if frame.get("configuration") != {
            "material_mode": material,
            "view": view,
            "background": background,
        }:
            raise ValueError("Captured configuration differs from its ID.")
        if (
            not isinstance(frame.get("observed"), dict)
            or frame["observed"].get("png_sha256") != _pin(frame.get("image"))["sha256"]
        ):
            raise ValueError("Captured PNG observation differs from its image pin.")
        captured[key] = frame
    expected_keys = {asset_id + "::" + config for asset_id in assets for config in CONFIGURATIONS}
    if set(captured) != expected_keys:
        raise ValueError("Every captured asset requires exactly eight frames.")
    frames, seen_ids, seen_keys, successful = {}, set(), set(), 0
    report_frames = _list(report.get("frames"))
    for record in report_frames:
        key = record.get("frame_id")
        image_id = integrity._integer(record.get("image_id"), 0, MAX_RECORDS)
        expected = captured.get(key)
        if (
            key in seen_keys
            or image_id in seen_ids
            or expected is None
            or any(
                record.get(name) != value for name, value in expected.items() if name != "status"
            )
            or record.get("source") != record.get("image")
        ):
            raise ValueError("Saved render score differs from its exact captured frame.")
        seen_keys.add(key)
        seen_ids.add(image_id)
        _reject_holdout(_pin(record.get("source")), held_paths, held_hashes)
        feature = _scored_record(record)
        successful += feature is not None
        if record.get("role") == "original_static_3d" and record.get("source_id") in sources:
            frames[key] = {**record, "feature": feature}
    if (
        seen_keys != set(captured)
        or seen_ids != set(range(len(report_frames)))
        or report.get("frame_counts")
        != {
            "requested": len(report_frames),
            "successful": successful,
            "failed": len(report_frames) - successful,
        }
        or capture.get("frame_counts")
        != {"requested": len(captured), "captured": len(captured), "failed": 0}
    ):
        raise ValueError("Render requested/failed inventory differs.")
    expected_selected = {
        source_id + "--original::" + c for source_id in sources for c in CONFIGURATIONS
    }
    if set(frames) != expected_selected:
        raise ValueError("Known-source original render inventory differs.")
    expected_sam = metadata["protocol"]["cohort"]["sam_asset_count"]
    if sum(
        asset["role"] == "sam_texture_static_3d" for asset in assets.values()
    ) != expected_sam or sum(
        frame["role"] == "sam_texture_static_3d" for frame in report_frames
    ) != expected_sam * len(CONFIGURATIONS):
        raise ValueError("Actual excluded SAM asset/frame inventory differs.")
    return frames, assets, report_frames


def parse_metadata(metadata, roles):
    threshold = validate_protocol(metadata["protocol"])
    _reference(metadata, roles, threshold)
    originals, held_paths, held_hashes, cases = _n0(metadata["n0_manifest"])
    photos = _photos(metadata["photo_report"], originals, held_paths, held_hashes)
    reset = metadata["source_reset_report"]
    if reset.get("inputs", {}).get("protocol_manifest") != roles["n0_manifest"]:
        raise ValueError("Source-reset N0 binding differs.")
    sources, all_sources = _sources(reset, cases, originals, photos, held_paths, held_hashes)
    frames, assets, report_frames = _frames(
        metadata, roles, sources, all_sources, held_paths, held_hashes
    )
    photo, render = metadata["photo_report"], metadata["render_report"]
    if (
        photo.get("model_pins") != render.get("model_pins")
        or photo.get("environment") != render.get("environment")
        or not isinstance(photo.get("environment"), dict)
        or not photo["environment"]
    ):
        raise ValueError("Saved photo/render model or environment versions differ.")
    model_pins = [_pin(row) for row in _list(photo.get("model_pins"), 8)]
    if len(model_pins) != 2 or len({row["path"] for row in model_pins}) != 2:
        raise ValueError("Both fixed face detector and recognition models are required.")
    if len(sources) ** 2 * len(CONFIGURATIONS) > MAX_PAIRS:
        raise ValueError("Directed comparison budget exceeded before pair construction.")
    pairs = []
    for config in CONFIGURATIONS:
        for source_id, own in sorted(sources.items()):
            frame = frames[source_id + "--original::" + config]
            for photo_source, reference in sorted(sources.items()):
                positive = own["subject_id"] == reference["subject_id"]
                left, right = frame["feature"], reference["photo"]["feature"]
                score = (
                    integrity._cosine(left, right)
                    if left is not None and right is not None
                    else None
                )
                subject, photo_subject = own["subject_id"], reference["subject_id"]
                pairs.append(
                    {
                        "pair_id": frame["frame_id"] + "::photo/" + photo_source,
                        "config_id": config,
                        "frame_id": frame["frame_id"],
                        "render_source_id": source_id,
                        "photo_source_id": photo_source,
                        "render_subject": subject,
                        "photo_subject": photo_subject,
                        "photo_image_id": reference["photo"]["image_id"],
                        "category": "positive" if positive else "different_identity_render_photo",
                        "unit": subject if positive else f"render/{subject}/photo/{photo_subject}",
                        "subjects": [subject] if positive else [subject, photo_subject],
                        "score": score,
                        "render_status": frame["status"],
                        "photo_status": reference["photo"]["status"],
                    }
                )
    accounting = {
        "known_sources": len(sources),
        "known_subjects": len(sources),
        "known_original_frames": len(frames),
        "known_original_scored": sum(f["feature"] is not None for f in frames.values()),
        "known_original_failed": sum(f["feature"] is None for f in frames.values()),
        "excluded_external_original_frames": (len(all_sources) - len(sources))
        * len(CONFIGURATIONS),
        "excluded_sam_frames": sum(
            frame["role"] != "original_static_3d" for frame in report_frames
        ),
        "all_saved_frames": len(report_frames),
        "all_captured_assets": len(assets),
        "heldout_metadata_excluded": len(held_paths),
        "pairs_requested": len(pairs),
        "pairs_scored": sum(pair["score"] is not None for pair in pairs),
        "pairs_failed": sum(pair["score"] is None for pair in pairs),
        "positive_requested": sum(pair["category"] == "positive" for pair in pairs),
        "negative_requested": sum(pair["category"] != "positive" for pair in pairs),
    }
    cohort = metadata["protocol"]["cohort"]
    for field, count in (
        ("source_count", len(sources)),
        ("external_source_count", len(all_sources) - len(sources)),
        ("sam_asset_count", len(assets) - len(all_sources)),
    ):
        if type(cohort.get(field)) is not int or cohort[field] != count:
            raise ValueError("Declared diagnostic source/asset denominator differs.")
    return pairs, sorted(source["subject_id"] for source in sources.values()), accounting, threshold


def summarize_pairs(pairs, subjects, threshold):
    if subjects != sorted(set(subjects)) or not 2 <= len(subjects) <= 100:
        raise ValueError("Distinct sorted source identities are required.")
    summaries = []
    for config in CONFIGURATIONS:
        selected = [pair for pair in pairs if pair["config_id"] == config]
        for pair in selected:
            if pair["category"] not in {"positive", "different_identity_render_photo"} or (
                len(pair["subjects"]) != (1 if pair["category"] == "positive" else 2)
                or any(s not in subjects for s in pair["subjects"])
                or (len(pair["subjects"]) == 2 and pair["subjects"][0] == pair["subjects"][1])
            ):
                raise ValueError("Invalid directed comparison subject units.")
            score = pair["score"]
            if score is not None and (type(score) not in {float, int} or not -1 <= score <= 1):
                raise ValueError("Invalid saved comparison score.")
        positive = integrity.unit_metrics(selected, "positive", threshold)
        negative = integrity.unit_metrics(selected, "negative", threshold)
        seed = SEED + int(_hash(("reference/" + config).encode())[:16], 16)
        summaries.append(
            {
                "config_id": config,
                "positive": integrity.class_summary(positive),
                "negative": integrity.class_summary(negative),
                "bootstrap": integrity.bootstrap(positive, negative, subjects, seed, REPLICATES),
            }
        )
    return summaries


def _output(root, name):
    name = name.as_posix() if isinstance(name, Path) else str(name)
    _pin({"path": name, "bytes": 0, "sha256": "0" * 64})
    output = integrity._path(root, name)
    research = (root / "output/research").resolve()
    if root not in research.parents or research not in output.parents or output.exists():
        raise ValueError("Output must be a fresh directory inside ignored output/research.")
    return output


def run(args):
    root = Path(args.root).resolve(strict=True)
    output = _output(root, args.output_dir)
    plan_path = Path(args.study_plan)
    plan_path = (plan_path if plan_path.is_absolute() else root / plan_path).resolve()
    if root not in plan_path.parents or plan_path.suffix.lower() != ".json":
        raise ValueError("Study plan must be workspace JSON metadata.")
    with plan_path.open("rb") as stream:
        plan_raw = stream.read(LIMIT + 1)
    if len(plan_raw) > LIMIT:
        raise ValueError("Study plan exceeds its byte bound.")
    plan, runtime = _json(plan_raw), runtime_fingerprint()
    if (
        plan.get("schema_version") != 1
        or plan.get("protocol_id") != PROTOCOL_ID
        or set(plan.get("roles", {})) != set(ROLES)
        or plan.get("runtime") != runtime
    ):
        raise ValueError("Frozen roles, schema or Python runtime differ.")
    roles = {key: _pin(value) for key, value in plan["roles"].items()}
    if any(
        Path(pin["path"]).suffix.lower() != ".json"
        or integrity._path(root, pin["path"]).suffix.lower() != ".json"
        for pin in roles.values()
    ):
        raise ValueError("Each metadata role must name a workspace JSON file.")
    inputs = Inputs(root, plan.get("inputs"))
    required = {pin["path"] for pin in roles.values()} | set(SOURCES)
    if len(required) != len(ROLES) + len(SOURCES) or set(inputs.pins) != required:
        raise ValueError("Freeze must contain exactly nine metadata and three source inputs.")
    for source in SOURCES:
        inputs.read(inputs.pins[source])
    if (
        inputs.pins[SOURCES[0]]["sha256"] != LOADED_CODE_SHA256
        or inputs.pins[SOURCES[2]]["sha256"] != integrity.LOADED_CODE_SHA256
    ):
        raise ValueError("Loaded CLI/helper differs from its pinned source.")
    metadata = {key: _json(inputs.read(pin)) for key, pin in roles.items()}
    pairs, subjects, accounting, threshold = parse_metadata(metadata, roles)
    configurations = summarize_pairs(pairs, subjects, threshold)

    def recheck():
        inputs.recheck()
        with plan_path.open("rb") as stream:
            current = stream.read(len(plan_raw) + 1)
        if current != plan_raw or runtime_fingerprint() != runtime:
            raise ValueError("Study plan or Python runtime drift after calculation.")

    recheck()
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **FLAGS,
        "quality_threshold": None,
        "diagnostic_reference_threshold": threshold,
        "study_plan": {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(plan_raw),
            "sha256": _hash(plan_raw),
        },
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "accounting": accounting,
        "subjects": subjects,
        "pairs": pairs,
        "configurations": configurations,
        "integrity": {
            "all_inputs_unchanged": True,
            "plan_unchanged": True,
            "runtime_unchanged": True,
        },
        "limitations": metadata["protocol"].get("observations", []),
        "bootstrap_scope": metadata["protocol"]["bootstrap"].get("limitations"),
    }
    raw = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > 2 * LIMIT:
        raise ValueError("Output report exceeds its byte bound.")
    recheck()
    output.mkdir(parents=True, exist_ok=False)
    pending = output / "pending-report.json"
    try:
        with pending.open("xb") as stream:
            stream.write(raw)
        recheck()
        pending.rename(output / "report.json")
    except BaseException:
        pending.unlink(missing_ok=True)
        if not any(output.iterdir()):
            output.rmdir()
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    try:
        result = run(parser.parse_args(argv))
        print(
            json.dumps(
                {
                    "diagnostic_reference_threshold": result["diagnostic_reference_threshold"],
                    "accounting": result["accounting"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
