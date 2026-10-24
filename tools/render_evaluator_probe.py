"""Frozen static-render identity and age diagnostics; no production acceptance."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import sys
from contextlib import closing
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "_render_age", Path(__file__).with_name("age_evaluator_probe.py")
)
age = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(age)
identity, metadata, near = age.identity, age.metadata, age.near

PROTOCOL = "agemorph3d-render-domain-v1"
SOURCES = (
    *age.SOURCES,
    "tools/render_evaluator_probe.py",
    "backend/tests/test_render_evaluator_probe.py",
)
CAPTURE_SOURCES = (
    "frontend/tests/render-domain-capture.mjs",
    "frontend/src/viewer.ts",
    "frontend/src/services.ts",
    "frontend/src/contracts.ts",
    "frontend/src/realtime.ts",
    "frontend/src/age.ts",
    "frontend/src/demo-head.ts",
    "frontend/src/research-texture.ts",
    "frontend/package.json",
    "frontend/package-lock.json",
    "docs/render-domain-v1.json",
)
FALSE_FLAGS = tuple(dict.fromkeys((*age.FALSE_FLAGS, "identity_quality_accepted")))
CONFIGURATIONS = tuple(itertools.product(("MASK", "BLEND"), ("front", "side"), ("black", "white")))
CATEGORIES = ("same_age_control", "other_condition", "unknown_source_age")
AGE_METRICS = (
    "age_shift",
    "condition_deviation",
    "static_condition_deviation",
    "absolute_condition_reduction",
)
REPORT_MAX_BYTES = 16 * 1024 * 1024
GEOMETRY_KEYS = (
    "source_positions_sha256",
    "source_normals_sha256",
    "source_indices_sha256",
    "gltf_uv_sha256",
)


def _pin(value):
    metadata._keys(value, {"path", "bytes", "sha256"}, "Render image pin")
    metadata._relative(Path.cwd().resolve(), value["path"])
    metadata._integer(value["bytes"], "Image bytes", 1, near.MAX_IMAGE_BYTES)
    if (
        type(value["sha256"]) is not str
        or len(value["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in value["sha256"])
    ):
        raise ValueError("Image needs a lowercase SHA-256 pin.")
    if not value["path"].startswith("output/research/") or not value["path"].endswith(".png"):
        raise ValueError("Only pinned research render PNGs may be evaluated.")
    return dict(value)


class _Inputs(metadata._Inputs):
    """Allow only explicitly selected report roles to exceed the old 2 MiB bound."""

    def __init__(self, root, large):
        super().__init__(root)
        self.large = set(large)

    def read(self, pin):
        if pin["path"] not in self.large:
            return super().read(pin)
        metadata._keys(pin, {"path", "bytes", "sha256"}, "Report pin")
        path = metadata._relative(self.root, pin["path"])
        metadata._integer(pin["bytes"], "Report bytes", 1, REPORT_MAX_BYTES)
        if path.suffix != ".json" or len(self.pins) >= 128 and pin["path"] not in self.pins:
            raise ValueError("Only bounded JSON reports may use the larger report allowance.")
        with path.open("rb") as stream:
            raw = stream.read(REPORT_MAX_BYTES + 1)
        if len(raw) != pin["bytes"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
            raise ValueError("Report pin mismatch: " + pin["path"])
        if pin["path"] in self.pins and self.pins[pin["path"]] != pin:
            raise ValueError("Conflicting report pins.")
        raw.decode("utf-8")
        metadata._json(raw)
        self.pins[pin["path"]] = dict(pin)
        return raw


def _protocol(value):
    if value.get("protocol_id") != PROTOCOL or value.get("schema_version") != 1:
        raise ValueError("Unsupported render protocol.")
    metadata._false_flags(value["flags"], FALSE_FLAGS, "Render protocol")
    if (
        value["flags"].get("research_only") is not True
        or value["observations"].get("render_domain_model_scores_seen_before_freeze") is not False
    ):
        raise ValueError("Research render predictions require a prospective protocol.")
    capture = value["capture"]
    if (capture["material_modes"], capture["views"], capture["backgrounds"]) != (
        ["MASK", "BLEND"],
        ["front", "side"],
        ["black", "white"],
    ):
        raise ValueError("The complete eight-configuration render matrix is required.")
    for key in ("width", "height"):
        metadata._integer(capture[key], "Render dimensions", 1, 4096)
    if capture["width"] * capture["height"] > age.LIMITS["image_max_pixels"]:
        raise ValueError("Render dimensions exceed the image bound.")
    config = value["evaluation"]["bootstrap"]
    if config["seed"] != 20261023 or config["replicates"] != 1000:
        raise ValueError("Bootstrap differs from the frozen source-unit algorithm.")
    if (
        value["evaluation"]["quality_threshold"] is not None
        or value["cohort"].get("baseline_target_age") is not None
        or value["cohort"].get("held_out_inference") is not False
    ):
        raise ValueError("No quality cutoff, default source age or held-out inference is allowed.")


def requests(n0, registration, source_reset):
    """Reconstruct original assets and every existing SAM condition without a timeline."""
    cases = {
        row["sample_id"]: row for row in n0["bridge_cases"] if row["source_status"] == "passed"
    }
    originals = {row["sample_id"]: row for row in source_reset["records"]}
    if len(originals) != len(source_reset["records"]) or set(originals) != set(cases):
        raise ValueError(
            "Original assets must cover exactly the successful N0 development sources."
        )
    held = [row for row in n0["adult_images"] if row["group"] == "evaluation_research_holdout"]
    held_paths, held_hashes = {row["path"] for row in held}, {row["sha256"] for row in held}
    assets, expected, sources = [], {}, {}
    for source_id, case in cases.items():
        original = originals[source_id]
        label = case["source_age"]["value"]
        if (
            case["group"] != "development"
            or original["group"] != "development"
            or original["status"] != "ok"
            or original["input"] != case["source"]
            or original["subject_id"] != case["subject_id"]
            or original["label_source_age"] != label
            or original["research_source_age"] != case["source_age"]
            or original["source_age"]
            != {"value": None, "method": "unknown", "calibration_id": None}
            or case["source"]["path"] in held_paths
            or case["source"]["sha256"] in held_hashes
        ):
            raise ValueError("Original static source provenance differs from development N0.")
        if label is not None:
            metadata._integer(label, "Research source label", 20, 70)
        geometry = registration["source_geometry_invariants"][source_id]
        metadata._keys(geometry, set(GEOMETRY_KEYS), "Source geometry hashes")
        item = {
            "asset_id": source_id + "--original",
            "source_id": source_id,
            "sample_id": None,
            "role": "original_static_3d",
            "source_age_label": label,
            "target_age": None,
            "category": "baseline",
            "artifacts": original["artifacts"],
            "geometry": geometry,
            "source_frame": original["source_frame"],
        }
        assets.append(item)
        sources[source_id] = original
        outputs = list(case["target_runs"])
        control = case["same_age_control"]
        if control["status"] in {"generated", "reused_existing"}:
            outputs.append({**control["output"], "target_age": control["target_age"]})
        for output in outputs:
            key = source_id, output["target_age"]
            pin = identity._image_pin(output)
            if key in expected and expected[key] != pin:
                raise ValueError("Conflicting SAM target/control pins.")
            expected[key] = pin
    seen, samples = set(), set()
    for row in registration["records"]:
        key = row["source_id"], row["target_age"]
        if key not in expected or key in seen or row["sample_id"] in samples:
            raise ValueError("SAM render assets must retain each existing target exactly once.")
        seen.add(key)
        samples.add(row["sample_id"])
        original = sources[row["source_id"]]
        label = original["label_source_age"]
        if (
            row["input"] != expected[key]
            or row["subject_id"] != original["subject_id"]
            or row["source_age_label"] != label
            or row["source_frame"] != original["source_frame"]
            or row["status"] != "ok"
            or row["asset_mode"] != "static"
            or row["source_age"] != original["source_age"]
            or row["capabilities"] != {"age_morph": False, "age_texture": False}
            or any(
                row[name] != value
                for name, value in registration["source_geometry_invariants"][key[0]].items()
            )
        ):
            raise ValueError("SAM asset changes source geometry, labels or static provenance.")
        target = metadata._integer(row["target_age"], "SAM condition", 20, 70)
        assets.append(
            {
                "asset_id": row["sample_id"],
                "source_id": row["source_id"],
                "sample_id": row["sample_id"],
                "role": "sam_texture_static_3d",
                "source_age_label": label,
                "target_age": target,
                "category": "unknown_source_age"
                if label is None
                else "same_age_control"
                if target == label
                else "other_condition",
                "artifacts": {name: row["artifacts"][name] for name in ("glb", "atlas")},
                "geometry": registration["source_geometry_invariants"][row["source_id"]],
                "source_frame": original["source_frame"],
            }
        )
    if seen != set(expected) or len({a["asset_id"] for a in assets}) != len(assets):
        raise ValueError("The complete original/SAM cohort is required.")
    frames, lookup = [], {}
    for asset in assets:
        for material, view, background in CONFIGURATIONS:
            config = "/".join((material, view, background))
            frame = {
                key: value
                for key, value in asset.items()
                if key not in {"geometry", "artifacts", "source_frame"}
            }
            frame.update(
                frame_id=asset["asset_id"] + "::" + config,
                config_id=config,
                configuration={"material_mode": material, "view": view, "background": background},
            )
            lookup[asset["asset_id"], config] = len(frames)
            frames.append(frame)
    pairs = []
    for asset in assets:
        if asset["role"] == "original_static_3d":
            continue
        for configuration in CONFIGURATIONS:
            config = "/".join(configuration)
            pairs.append(
                {
                    "pair_id": len(pairs),
                    "left_id": lookup[asset["source_id"] + "--original", config],
                    "right_id": lookup[asset["asset_id"], config],
                    "source_id": asset["source_id"],
                    "sample_id": asset["sample_id"],
                    "category": asset["category"],
                    "config_id": config,
                    "target_age": asset["target_age"],
                    "source_age_label": asset["source_age_label"],
                }
            )
    return assets, frames, pairs


def validate_capture(capture, expected_frames):
    if capture.get("protocol_id") != PROTOCOL or capture.get("status") != "passed":
        raise ValueError("Only a successful frozen render capture is eligible.")
    if capture.get("research_only") is not True:
        raise ValueError("Render capture must be explicitly research-only.")
    metadata._false_flags(capture, FALSE_FLAGS, "Capture")
    frames = capture.get("frames")
    if not isinstance(frames, list) or len(frames) != len(expected_frames):
        raise ValueError("Capture must retain the complete frozen frame denominator.")
    images = set()
    for expected, actual in zip(expected_frames, frames, strict=True):
        if any(not identity._same(actual.get(key), value) for key, value in expected.items()):
            raise ValueError(
                "Capture frame provenance/configuration differs from the frozen cohort."
            )
        pin = _pin(actual["image"])
        if actual.get("status") != "ok" or pin["path"] in images:
            raise ValueError("Each successful render frame requires its own pinned PNG.")
        images.add(pin["path"])
    return frames


def _link_capture(capture, assets, plan, protocol):
    """Bind rendered pixels to the exact frozen atlas/geometry/protocol producer."""
    captured_inputs = capture.get("inputs")
    if not isinstance(captured_inputs, list) or len(captured_inputs) > 128:
        raise ValueError("Capture must bind bounded metadata/source inputs.")
    if len({pin["path"] for pin in captured_inputs}) != len(captured_inputs):
        raise ValueError("Duplicate captured metadata pins.")
    if any(pin not in plan["inputs"] for pin in captured_inputs):
        raise ValueError("Every captured metadata/source pin must remain frozen for evaluation.")
    for role in ("protocol", "n0_manifest", "registration_report", "source_reset_report"):
        if plan[role] not in captured_inputs:
            raise ValueError("Capture does not bind the same source/protocol role: " + role)
    source_pins = capture.get("source_pins")
    if (
        not isinstance(source_pins, list)
        or {pin["path"] for pin in source_pins} != set(CAPTURE_SOURCES)
        or len(source_pins) != len(CAPTURE_SOURCES)
    ):
        raise ValueError("Capture must bind the exact eleven producer/dependency sources.")
    if any(pin not in captured_inputs for pin in source_pins):
        raise ValueError("Captured producer sources differ from captured metadata inputs.")
    if (
        capture.get("owned_servers_closed") is not True
        or capture.get("browser_closed") is not True
        or capture.get("interrupted") is not False
        or capture.get("external_requests") != []
        or capture.get("browser_errors") != []
        or capture.get("requested_configuration") != protocol["capture"]
    ):
        raise ValueError("Capture configuration, resource closure or browser isolation failed.")
    captured_assets = capture.get("assets")
    if not isinstance(captured_assets, list) or len(captured_assets) != len(assets):
        raise ValueError("Capture must bind every original and SAM static asset.")
    by_id = {item["asset_id"]: item for item in captured_assets}
    if len(by_id) != len(assets):
        raise ValueError("Duplicate captured asset IDs.")
    expected_pins = []
    for asset in assets:
        item = by_id.get(asset["asset_id"], {})
        descriptive = {
            key: value
            for key, value in asset.items()
            if key not in {"artifacts", "geometry", "source_frame"}
        }
        if (
            any(not identity._same(item.get(key), value) for key, value in descriptive.items())
            or item.get("status") != "captured"
            or item.get("glb") != asset["artifacts"]["glb"]
            or item.get("atlas") != asset["artifacts"]["atlas"]
            or item.get("expected_geometry") != asset["geometry"]
            or item.get("source_frame") != asset["source_frame"]
        ):
            raise ValueError("Captured GLB/atlas/frame provenance differs from source reports.")
        expected_pins.extend(asset["artifacts"].values())
    declared = capture.get("asset_pins")
    if not isinstance(declared, list) or sorted(declared, key=lambda pin: pin["path"]) != sorted(
        expected_pins, key=lambda pin: pin["path"]
    ):
        raise ValueError("Capture binary asset pins differ from the exact source/target assets.")
    for frame in capture["frames"]:
        observed = frame.get("observed", {})
        if observed.get("geometry") != by_id[frame["asset_id"]]["expected_geometry"] or (
            observed.get("png_sha256") != frame["image"]["sha256"]
        ):
            raise ValueError(
                "Captured PNG/geometry observation is not bound to its declared frame."
            )


def _current(record):
    return (
        not record.get("source_changed", False)
        and record.get("initial_source_check", {}).get("matches_declared", True)
        and record.get("final_source_check", {}).get("matches_declared", True)
    )


def score_pairs(pair_requests, records, identity_records=None):
    identity_records = records if identity_records is None else identity_records
    result = []
    for request in pair_requests:
        left, right = (records[request[name]] for name in ("left_id", "right_id"))
        a, b = (identity_records[request[name]] for name in ("left_id", "right_id"))
        valid = _current(left) and _current(right)
        identity_ok = (
            valid
            and a["status"] == b["status"] == "ok"
            and a.get("embedding") is not None
            and b.get("embedding") is not None
        )
        age_ok = (
            valid
            and left["status"] == right["status"] == "ok"
            and left.get("age_estimate") is not None
            and right.get("age_estimate") is not None
        )
        metrics = dict.fromkeys(AGE_METRICS)
        if age_ok:
            deviation, static = (
                right["age_estimate"] - request["target_age"],
                left["age_estimate"] - request["target_age"],
            )
            metrics.update(
                age_shift=right["age_estimate"] - left["age_estimate"],
                condition_deviation=deviation,
                static_condition_deviation=static,
                absolute_condition_reduction=abs(static) - abs(deviation),
            )
        result.append(
            {
                **request,
                "left_status": left["status"],
                "right_status": right["status"],
                "identity_left_status": a["status"],
                "identity_right_status": b["status"],
                "identity_status": "scored" if identity_ok else "failed",
                "identity_cosine": identity.cosine(a["embedding"], b["embedding"])
                if identity_ok
                else None,
                "age_status": "scored"
                if age_ok
                else "failed"
                if "age_estimate" in left
                else "not_evaluated",
                **metrics,
            }
        )
    return result


def _summary(rows, key, metrics, protocol, squared_metric=None):
    bridge = {"statistics": {"bootstrap": protocol["evaluation"]["bootstrap"]}}
    return age.summarize(rows, key, metrics, bridge, squared_metric=squared_metric)


def aggregate_pairs(pairs, protocol):
    summaries = []
    for configuration in CONFIGURATIONS:
        config = "/".join(configuration)
        for category in CATEGORIES:
            rows = [
                pair
                for pair in pairs
                if pair["config_id"] == config and pair["category"] == category
            ]
            key = f"paired/{config}/{category}"
            summaries.append(
                {
                    "config_id": config,
                    "category": category,
                    "identity": _summary(
                        [
                            (
                                row["source_id"],
                                {"identity_cosine": row["identity_cosine"]}
                                if row["identity_status"] == "scored"
                                else None,
                            )
                            for row in rows
                        ],
                        key,
                        ("identity_cosine",),
                        protocol,
                    ),
                    "age": _summary(
                        [
                            (
                                row["source_id"],
                                {name: row[name] for name in AGE_METRICS}
                                if row["age_status"] == "scored"
                                else None,
                            )
                            for row in rows
                        ],
                        key,
                        AGE_METRICS,
                        protocol,
                    ),
                }
            )
    return summaries


def aggregate_originals(records, protocol):
    summaries = []
    for configuration in CONFIGURATIONS:
        config = "/".join(configuration)
        original = [
            row
            for row in records
            if row["role"] == "original_static_3d" and row["config_id"] == config
        ]
        rows = []
        for row in original:
            label, estimate = row["source_age_label"], row.get("age_estimate")
            scored = row["status"] == "ok" and label is not None and estimate is not None
            rows.append((row["source_id"], age._error_vector(estimate - label) if scored else None))
        known = sum(row["source_age_label"] is not None for row in original)
        summaries.append(
            {
                "config_id": config,
                "known_label_requests": known,
                "unknown_label_requests": len(original) - known,
                "known_label_eligible_units": known,
                **_summary(rows, f"original/{config}", ("mae", "bias", "mse"), protocol, "mse"),
            }
        )
    return summaries


def _environment(stage):
    if stage == "age":
        return age._environment()
    import cv2
    import numpy
    import PIL

    return {
        "python_version": sys.version.split()[0],
        "pillow_version": PIL.__version__,
        "opencv_version": cv2.__version__,
        "numpy_version": numpy.__version__,
    }


def _load(root, plan_path, stage):
    root, plan_path = Path(root).resolve(strict=True), Path(plan_path).resolve(strict=True)
    if not plan_path.is_relative_to(root) or plan_path.suffix != ".json":
        raise ValueError("Study plan must be workspace JSON.")
    raw = metadata._read(plan_path)
    plan = metadata._json(raw)
    roles = [
        "protocol",
        "capture_report",
        "age_protocol",
        "n0_manifest",
        "registration_report",
        "source_reset_report",
        "environment",
    ]
    roles += (
        ["model_manifest"]
        if stage == "identity"
        else ["identity_report", "source_acquisition", "model_acquisition"]
    )
    metadata._keys(plan, {"protocol_id", "inputs", *roles}, "Render study plan")
    if plan["protocol_id"] != PROTOCOL or len({plan[name]["path"] for name in roles}) != len(roles):
        raise ValueError("Render protocol or metadata roles differ.")
    inputs = _Inputs(
        root, [plan[name]["path"] for name in ("capture_report", "identity_report") if name in plan]
    )
    inputs.read(
        {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    listed = set()
    for pin in metadata._list(plan["inputs"], "Render inputs", 128):
        if pin["path"] in listed:
            raise ValueError("Duplicate render input pin.")
        listed.add(pin["path"])
        inputs.read(pin)
    if any(plan[name] not in plan["inputs"] for name in roles):
        raise ValueError("Every named metadata role must be in the frozen input list.")
    actual_root = Path(__file__).resolve().parents[1]
    for name in SOURCES:
        if (
            name not in inputs.pins
            or hashlib.sha256(metadata._read(actual_root / name)).hexdigest()
            != inputs.pins[name]["sha256"]
        ):
            raise ValueError("Every loaded implementation source and its tests must match its pin.")
    values = {name: metadata._json(inputs.read(plan[name])) for name in roles}
    protocol = values["protocol"]
    _protocol(protocol)
    n0 = values["n0_manifest"]
    metadata._n0(values["age_protocol"], n0, n0.get("summary"), plan["age_protocol"])
    for name, report_protocol in (
        ("registration_report", "agemorph3d-target-uv-v1"),
        ("source_reset_report", "agemorph3d-source-reset-v1"),
    ):
        report = values[name]
        if (
            report.get("protocol_id") != report_protocol
            or report.get("research_only") is not True
            or report["inputs"]["protocol_manifest"] != plan["n0_manifest"]
        ):
            raise ValueError("Render assets must bind the same N0 manifest.")
        metadata._false_flags(
            report, ("service_ready", "g3_complete", "holdout_age_results_opened"), "Source report"
        )
    assets, expected, pair_requests = requests(
        n0, values["registration_report"], values["source_reset_report"]
    )
    actual = {
        "original_assets": sum(a["role"] == "original_static_3d" for a in assets),
        "sam_assets": sum(a["role"] == "sam_texture_static_3d" for a in assets),
        "source_age_labels_known": sum(
            a["role"] == "original_static_3d" and a["source_age_label"] is not None for a in assets
        ),
        "source_age_labels_unknown": sum(
            a["role"] == "original_static_3d" and a["source_age_label"] is None for a in assets
        ),
        "unique_frames": len(expected),
        "paired_comparisons": len(pair_requests),
        **{
            category + "_assets": sum(a["category"] == category for a in assets)
            for category in CATEGORIES
        },
    }
    if any(protocol["cohort"].get(key) != count for key, count in actual.items()):
        raise ValueError("Asset/frame/pair counts differ from the frozen render protocol.")
    frames = validate_capture(values["capture_report"], expected)
    _link_capture(values["capture_report"], assets, plan, protocol)
    for frame in frames:
        metadata._relative(root, frame["image"]["path"])
    if not identity._same(_environment(stage), values["environment"]):
        raise ValueError("Render evaluator environment differs from its pin.")
    return root, plan, inputs, values, frames, pair_requests, actual


def _cached(frames, report, capture_pin):
    if (
        report.get("protocol_id") != PROTOCOL
        or report.get("stage") != "identity"
        or report.get("research_only") is not True
        or report.get("integrity_status") != "passed"
        or capture_pin not in report.get("inputs", [])
    ):
        raise ValueError("Age requires fresh render identity metadata from this exact capture.")
    metadata._false_flags(report, FALSE_FLAGS, "Render identity report")
    if (
        report.get("models_closed") is not True
        or report.get("holdout_predictions_extracted") is not False
        or report.get("images_or_crops_written") is not False
    ):
        raise ValueError("Cached identity inference scope or resource closure differs.")
    model_pins = metadata._list(report.get("model_pins"), "Cached identity models", 2)
    actual_models = sorted(
        (Path(pin["path"]).name, pin["bytes"], pin["sha256"]) for pin in model_pins
    )
    expected_models = sorted(
        (model["filename"], model["bytes"], model["sha256"]) for model in identity.MODELS.values()
    )
    if actual_models != expected_models:
        raise ValueError("Cached embeddings must come from the fixed identity/detector models.")
    cached = report.get("frames")
    if not isinstance(cached, list) or len(cached) != len(frames):
        raise ValueError("Frozen render identity frame count differs.")
    for frame, record in zip(frames, cached, strict=True):
        if any(
            not identity._same(record.get(key), value)
            for key, value in frame.items()
            if key != "status"
        ):
            raise ValueError("Frozen identity frame provenance differs.")
        expected = {**frame["image"], "verification": "verified", "matches_declared": True}
        if (
            record.get("initial_source_check") != expected
            or record.get("final_source_check") != expected
            or record.get("source_changed") is not False
        ):
            raise ValueError("Frozen render identity input integrity failed.")
        if record["status"] == "ok":
            identity.map_face(
                record["face"],
                (record["width"], record["height"]),
                (record["width"], record["height"]),
            )
            identity.embedding(record["embedding"])
    return cached


def _build(root, plan_path, stage, factory):
    root, plan, inputs, values, frames, pair_requests, counts = _load(root, plan_path, stage)
    policy, environment = values["protocol"], values["environment"]
    if stage == "identity":
        argument, model_pins, document_pins = identity._models(root, values["model_manifest"])
        cached = None
    else:
        cached = _cached(frames, values["identity_report"], plan["capture_report"])
        argument, model, sources, pointer = age._artifacts(
            root, values["source_acquisition"], values["model_acquisition"]
        )
        model_pins, document_pins = [model], [*sources, pointer]
    evaluator, records = None, []
    settings = identity.Settings(
        max_image_bytes=age.LIMITS["image_max_bytes"],
        max_image_pixels=age.LIMITS["image_max_pixels"],
    )
    try:
        evaluator = factory(argument)
        if not identity._same(evaluator.environment, environment):
            raise ValueError("Actual evaluator environment differs from the frozen plan.")
        for index, frame in enumerate(frames):
            initial, snapshot = near._snapshot(root, frame["image"])
            record = {
                **frame,
                "image_id": index,
                "source": frame["image"],
                "status": initial["verification"],
                "initial_source_check": initial,
            }
            if stage == "identity":
                record["embedding"] = None
            else:
                record.update(
                    age_estimate=None,
                    raw_age_estimate=None,
                    reused_detection_status=cached[index]["status"],
                )
            if snapshot is not None:
                if stage == "age" and cached[index]["status"] != "ok":
                    record["status"] = cached[index]["status"]
                else:
                    try:
                        with closing(identity.decode_image(snapshot, "image/png", settings)) as rgb:
                            if rgb.size != (
                                policy["capture"]["width"],
                                policy["capture"]["height"],
                            ):
                                raise age.EvaluationFailure("RENDER_DIMENSIONS_DIFFER")
                            if stage == "identity":
                                result = evaluator.evaluate(rgb)
                                face = identity.map_face(result["face"], rgb.size, rgb.size)
                                if result["aligned_size"] != [112, 112]:
                                    raise identity.EvaluationFailure("INVALID_ALIGNMENT")
                                record.update(
                                    status="ok",
                                    width=rgb.width,
                                    height=rgb.height,
                                    face=face,
                                    embedding=identity.embedding(result["embedding"]),
                                    **{
                                        key: result[key]
                                        for key in (
                                            "detector_input_size",
                                            "detector_to_original_scale_xy",
                                            "aligned_size",
                                        )
                                    },
                                )
                            else:
                                detection = cached[index]
                                if rgb.size != (detection["width"], detection["height"]):
                                    raise age.EvaluationFailure("CACHED_DIMENSIONS_DIFFER")
                                bounds = age.crop_bounds(detection["face"], rgb.width, rgb.height)
                                with closing(rgb.crop(tuple(bounds))) as crop:
                                    result = age.prediction(evaluator.predict(crop))
                                record.update(
                                    status="ok",
                                    width=rgb.width,
                                    height=rgb.height,
                                    crop_bounds=bounds,
                                    **result,
                                )
                    except identity.ApiError as error:
                        record["status"] = error.code
                    except (identity.EvaluationFailure, age.EvaluationFailure) as error:
                        record["status"] = str(error)
                    except (RuntimeError, TypeError, ValueError, OverflowError, OSError) as error:
                        record.update(status="EVALUATOR_FAILED", failure_type=type(error).__name__)
            records.append(record)

        def statistics():
            pairs = score_pairs(pair_requests, records, cached)
            return (
                pairs,
                aggregate_pairs(pairs, policy),
                aggregate_originals(records, policy) if stage == "age" else [],
            )

        pairs, summaries, originals = statistics()
        integrity = True
        for _ in range(len(records) + 1):
            changed = False
            for record in records:
                final, _ = near._snapshot(root, record["source"])
                record["final_source_check"] = final
                record["source_changed"] = (
                    record.get("source_changed", False) or final != record["initial_source_check"]
                )
                if record["source_changed"] and record["status"] != "source_changed":
                    record["status_before_source_change"] = record["status"]
                    record["status"] = "source_changed"
                    if stage == "identity":
                        record["embedding"] = None
                    else:
                        record.update(age_estimate=None, raw_age_estimate=None)
                    changed = True
                integrity &= (
                    final["matches_declared"]
                    and record["initial_source_check"]["matches_declared"]
                    and not record["source_changed"]
                )
            if not changed:
                break
            pairs, summaries, originals = statistics()
        if stage == "identity":
            identity._models(root, values["model_manifest"])
        else:
            age._artifacts(root, values["source_acquisition"], values["model_acquisition"])
        inputs.verify()
        for name in SOURCES:
            if (
                hashlib.sha256(
                    metadata._read(Path(__file__).resolve().parents[1] / name)
                ).hexdigest()
                != inputs.pins[name]["sha256"]
            ):
                raise ValueError("Loaded implementation changed during render scoring.")
        if not identity._same(_environment(stage), environment) or not identity._same(
            evaluator.environment, environment
        ):
            raise ValueError("Render evaluator environment changed during scoring.")
    finally:
        if evaluator is not None:
            evaluator.close()
    successful = sum(record["status"] == "ok" for record in records)
    pair_counts = {}
    for kind in ("identity", "age"):
        scored = sum(pair[kind + "_status"] == "scored" for pair in pairs)
        pair_counts[kind] = (
            {"requested": len(pairs), "scored": scored, "failed": len(pairs) - scored}
            if stage == "age" or kind == "identity"
            else None
        )
    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL,
        "stage": stage,
        "research_only": True,
        **dict.fromkeys(FALSE_FLAGS, False),
        "quality_threshold": None,
        "integrity_status": "passed" if integrity else "failed",
        "execution_status": "complete"
        if successful == len(records) and integrity
        else "completed_with_failures",
        "frames": records,
        "pairs": pairs,
        "paired_summaries": summaries,
        "original_age_summaries": originals,
        "cohort_counts": counts,
        "frame_counts": {
            "requested": len(records),
            "successful": successful,
            "failed": len(records) - successful,
        },
        "pair_counts": pair_counts,
        "environment": environment,
        "inputs": [inputs.pins[name] for name in sorted(inputs.pins)],
        "model_pins": model_pins,
        "model_document_pins": document_pins,
        "images_or_crops_written": False,
        "models_closed": True,
        "holdout_predictions_extracted": False,
        "demographic_classification_exported": False,
        "final_source_check_phase": "after_all_inference_pair_scoring_macro_and_bootstrap",
        "limits": [
            "Fixed source geometry; target ages are conditions, not age truth.",
            "Coverage, material, background, pose and render-domain effects remain confounded.",
            (
                "Cached identity evaluation failures include detection/alignment/feature failures; "
                "age does not redetect."
            ),
            (
                "Source-macro intervals condition on scored development sources "
                "and are not independent validation."
            ),
        ],
    }


def build_identity_report(root, plan_path, evaluator_factory=identity.CpuEvaluator):
    return _build(root, plan_path, "identity", evaluator_factory)


def build_age_report(root, plan_path, evaluator_factory=age.CpuAgePredictor):
    return _build(root, plan_path, "age", evaluator_factory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("identity", "age"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        output = metadata._relative(root, args.output_dir)
        allowed = (root / "output/research").resolve()
        if (
            output == allowed
            or not output.is_relative_to(allowed)
            or not allowed.is_relative_to(root)
        ):
            raise ValueError("Output must be a new research descendant.")
        if output.exists():
            raise FileExistsError("Output already exists; previous evidence is preserved.")
        plan = (
            args.study_plan
            if args.study_plan.is_absolute()
            else metadata._relative(root, args.study_plan.as_posix())
        )
        report = (build_identity_report if args.stage == "identity" else build_age_report)(
            root, plan
        )
        raw = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode(
            "utf-8"
        )
        if len(raw) > REPORT_MAX_BYTES:
            raise ValueError("Render evaluation report exceeds its 16 MiB bound.")
        output.mkdir(parents=True, exist_ok=False)
        with (output / "report.json").open("xb") as stream:
            stream.write(raw)
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "stage",
                        "integrity_status",
                        "execution_status",
                        "frame_counts",
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
