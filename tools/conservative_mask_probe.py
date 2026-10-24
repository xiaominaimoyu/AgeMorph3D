"""Create separately versioned conservative masks from explicit AI skin polygons.

Only annotated skin inside an old excluded band may be released. Protected
glasses envelopes, a fixed safety margin and unreviewed band pixels remain
excluded. This is development evidence, never human or quality acceptance.
"""

# Offline entrypoint; no model loading, registration, service or Git operations.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import copy
import io
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

import cv2
import mask_replay_probe as mask
import mask_review_workbench as workbench
import numpy as np
from PIL import Image

uv = mask.uv
PROTOCOL_ID = "agemorph3d-conservative-mask-v1"
ROLES = ("protocol", "mask_report", "mask_audit", "uv_report", "annotations")
SOURCES = (
    *mask.SOURCES,
    "tools/mask_review_workbench.py",
    "tools/conservative_mask_probe.py",
    "backend/tests/test_conservative_mask_probe.py",
)
FALSE_FLAGS = (*workbench.FALSE_FLAGS, "usable_mask_candidate_accepted")
FOCUS_IDS = tuple(f"fgnet-004a63--sam-{age:03d}" for age in uv.COHORT["fgnet-004a63"])
LABELS = {
    "outside_old_occluded": 0,
    "released_skin": 1,
    "protected_margin": 2,
    "unreviewed_old_occluded": 3,
}
MARGIN = 12
TOTAL_LIMIT = 96 * 1024**2
_LOADED_SOURCE_HASHES = {
    name: uv._digest((_ROOT / name).read_bytes())
    for name in SOURCES
    if name.endswith(".py") and "/tests/" not in name
}


def _protocol(protocol):
    if (
        protocol.get("schema_version") != 1
        or protocol.get("protocol_id") != PROTOCOL_ID
        or protocol["cohort"]["sources"] != uv.COHORT
        or protocol["cohort"]["expected_targets"] != 12
        or protocol["cohort"]["group"] != "development"
        or protocol["cohort"]["api_source_age"] != uv.UNKNOWN_AGE
        or protocol["cohort"]["review_target_count"] != 37
        or protocol["cohort"]["annotation_count"] != 4
        or protocol["rasterization"]["fill"] != "LINE_8 shift0 per-polygon union"
        or type(protocol["rasterization"]["margin_pixels"]) is not int
        or protocol["rasterization"]["margin_pixels"] != MARGIN
        or protocol["rasterization"]["dilation_kernel"] != 25
        or protocol["rasterization"]["border_value"] != 0
        or protocol["refinement"]["release"] != "old_occluded & skin & ~protected_margin"
        or protocol["refinement"]["allowed"] != "old_allowed | release"
        or protocol["refinement"]["occluded"] != "old_occluded & ~release"
        or protocol["refinement"]["labels"] != LABELS
        or protocol["observations"]["historical_mask_results_seen_before_freeze"] is not True
        or protocol["observations"]["remove_B_upper_bound_seen_before_freeze"] is not True
        or protocol["observations"]["candidate_mask_results_seen_before_freeze"] is not False
        or protocol["quality_threshold"] is not None
        or protocol["flags"] != {"research_only": True, **dict.fromkeys(FALSE_FLAGS, False)}
    ):
        raise ValueError("Unsupported conservative-mask recipe, cohort or research boundary.")


def _pins(value, *, depth=0):
    if depth > 64:
        raise ValueError("Annotation evidence nesting exceeds its bounded schema.")
    if isinstance(value, dict):
        if {"path", "bytes", "sha256"} <= value.keys():
            yield uv._pin({key: value[key] for key in ("path", "bytes", "sha256")})
        for item in value.values():
            yield from _pins(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _pins(item, depth=depth + 1)


def derive_input_pins(metadata):
    """Bind all old37 image/fit/mask rows and every annotation evidence pin."""
    inherited = workbench.derive_input_pins(metadata)
    review = metadata["original_review"]
    if len(review["target_records"]) != 37:
        raise ValueError("The original complete37 target review is required.")
    values = [*inherited, *_pins(metadata["annotations"]), *_pins(review)]
    values.extend(
        row[key]
        for row in review["target_records"]
        for key in ("input", "target_fit", "allowed_mask", "occluded_mask")
    )
    pins = {}
    for value in values:
        pin = uv._pin(value)
        if pin["path"] in pins and pins[pin["path"]] != pin:
            raise ValueError("Conflicting inherited full-review or annotation-evidence pins.")
        pins[pin["path"]] = pin
    return list(pins.values())


def _annotation_header(annotation):
    if (
        not isinstance(annotation, dict)
        or annotation.get("schema_version") != 1
        or not isinstance(annotation.get("sample_id"), str)
        or re.fullmatch(r"[a-z0-9-]{1,128}", annotation["sample_id"]) is None
        or annotation.get("source_age_api") != uv.UNKNOWN_AGE
        or annotation.get("reviewer_kind") != "ai"
        or annotation.get("reviewer") != "codex-root-visual-observation"
        or annotation.get("human_review_completed") is not False
        or type(annotation.get("margin_pixels")) is not int
        or annotation["margin_pixels"] != MARGIN
    ):
        raise ValueError("Annotations require exact target identity, unknown API age and AI scope.")
    uv._pin(annotation["target_image"])


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, point):
    return (
        _cross(a, b, point) == 0
        and min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])
    )


def _intersects(a, b, c, d):
    first, second, third, fourth = (
        _cross(a, b, c),
        _cross(a, b, d),
        _cross(c, d, a),
        _cross(c, d, b),
    )
    return (
        first * second < 0
        and third * fourth < 0
        or _on_segment(a, b, c)
        or _on_segment(a, b, d)
        or _on_segment(c, d, a)
        or _on_segment(c, d, b)
    )


def _polygon(points, width, height):
    if (
        not isinstance(points, list)
        or not 3 <= len(points) <= 128
        or any(
            not isinstance(point, list)
            or len(point) != 2
            or any(type(value) is not int for value in point)
            or not 0 <= point[0] < width
            or not 0 <= point[1] < height
            for point in points
        )
    ):
        raise ValueError("Polygons require bounded integer native-image vertices.")
    vertices = [tuple(point) for point in points]
    if len(set(vertices)) != len(vertices):
        raise ValueError("Repeated polygon vertices, including explicit closure, are forbidden.")
    count = len(vertices)
    area = sum(
        vertices[index][0] * vertices[(index + 1) % count][1]
        - vertices[(index + 1) % count][0] * vertices[index][1]
        for index in range(count)
    )
    if area == 0:
        raise ValueError("Degenerate polygons cannot define reviewed skin or protection.")
    for index, current in enumerate(vertices):
        previous, following = vertices[index - 1], vertices[(index + 1) % count]
        if _cross(previous, current, following) == 0 and (
            (current[0] - previous[0]) * (following[0] - current[0])
            + (current[1] - previous[1]) * (following[1] - current[1])
            < 0
        ):
            raise ValueError("Adjacent polygon edges cannot reverse over one another.")
        for other in range(index + 1, count):
            if other == index + 1 or index == 0 and other == count - 1:
                continue
            if _intersects(current, following, vertices[other], vertices[(other + 1) % count]):
                raise ValueError("Polygons cannot self-intersect or touch nonadjacent edges.")
    return np.asarray(points, np.int32)


def _dilate(protected):
    return (
        cv2.dilate(
            protected.astype(np.uint8),
            np.ones((2 * MARGIN + 1, 2 * MARGIN + 1), np.uint8),
            anchor=(-1, -1),
            iterations=1,
            borderType=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        != 0
    )


def rasterize_annotations(annotation, width, height):
    """Union simple LINE8 polygons and apply a fixed square protection margin."""
    mask._dimensions(width, height)
    _annotation_header(annotation)
    groups = (annotation.get("skin_polygons"), annotation.get("protected_polygons"))
    if any(not isinstance(group, list) or not 1 <= len(group) <= 64 for group in groups):
        raise ValueError(
            "Both skin and protected envelopes require bounded nonempty polygon lists."
        )
    if (
        sum(
            len(points) if isinstance(points, list) else 4097
            for group in groups
            for points in group
        )
        > 4096
    ):
        raise ValueError("Annotation vertex count exceeds its fixed budget.")
    polygons = [[_polygon(points, width, height) for points in group] for group in groups]
    layers = []
    for group in polygons:
        pixels = np.zeros((height, width), np.uint8)
        for points in group:
            # Separate fills are a union, avoiding fillPoly's inter-polygon even/odd holes.
            cv2.fillPoly(pixels, [points], 1, lineType=cv2.LINE_8, shift=0)
        layers.append(pixels != 0)
    skin, protected = layers
    return {"skin": skin, "protected": protected, "protected_margin": _dilate(protected)}


def refine_masks(old_allowed, old_occluded, layers):
    """Release reviewed skin only from the old band; protection has priority."""
    uv._masks(old_allowed, old_occluded)
    if (
        not isinstance(layers, dict)
        or set(layers) != {"skin", "protected", "protected_margin"}
        or any(
            not isinstance(layer, np.ndarray)
            or layer.dtype != np.bool_
            or layer.shape != old_allowed.shape
            for layer in layers.values()
        )
    ):
        raise ValueError("Annotation layers must be bounded booleans in the exact old pixel frame.")
    skin, protected, margin = (layers[name] for name in ("skin", "protected", "protected_margin"))
    if not np.array_equal(margin, _dilate(protected)):
        raise ValueError("The protected margin must equal the fixed12 pixel square dilation.")
    release = old_occluded & skin & ~margin
    allowed, occluded = old_allowed | release, old_occluded & ~release
    if (
        np.any(allowed & occluded)
        or not np.array_equal(allowed | occluded, old_allowed | old_occluded)
        or np.any(release & margin)
        or np.any(old_allowed & ~allowed)
    ):
        raise ValueError(
            "Conservative refinement changed the old base or released protected pixels."
        )
    labels = np.zeros(old_allowed.shape, np.uint8)
    labels[old_occluded] = LABELS["unreviewed_old_occluded"]
    labels[old_occluded & margin] = LABELS["protected_margin"]
    labels[release] = LABELS["released_skin"]
    return {
        "allowed": allowed,
        "occluded": occluded,
        "labels": labels,
        "counts": {
            "old_allowed_pixels": int(old_allowed.sum()),
            "old_occluded_pixels": int(old_occluded.sum()),
            "skin_pixels": int(skin.sum()),
            "protected_pixels": int(protected.sum()),
            "protected_margin_pixels": int(margin.sum()),
            "released_pixels": int(release.sum()),
            "protected_old_occluded_pixels": int(np.count_nonzero(old_occluded & margin)),
            "remaining_old_occluded_pixels": int(np.count_nonzero(labels == 3)),
            "new_allowed_pixels": int(allowed.sum()),
            "new_occluded_pixels": int(occluded.sum()),
            "label_pixels": {str(code): int(np.count_nonzero(labels == code)) for code in range(4)},
        },
    }


def _validate_original_review(inputs, metadata):
    primary = metadata["mask_report"]
    review = metadata["original_review"]
    registration = uv._json(inputs.read(primary["roles"]["registration_report"], uv.META_LIMIT))
    if (
        review.get("schema_version") != 1
        or review.get("protocol_id") != "agemorph3d-target-uv-v1"
        or registration["inputs"]["mask_review"] != primary["roles"]["mask_review"]
    ):
        raise ValueError("Original full-review role was reassigned after the frozen mask replay.")
    rows, registered = uv._indexed(review["target_records"]), uv._indexed(registration["records"])
    if len(rows) != 37 or set(rows) != set(registered) or not set(FOCUS_IDS) <= rows.keys():
        raise ValueError(
            "The full37 historical review must retain every original target exactly once."
        )
    if any(row != registered[sample]["mask_review"] for sample, row in rows.items()):
        raise ValueError(
            "A full-review target differs from its exact historical registration evidence."
        )
    return review


def _validate_annotations(bundle, original_review):
    if bundle.get("schema_version") != 1 or not isinstance(bundle.get("records"), list):
        raise ValueError("A bounded versioned annotation package is required.")
    annotations = uv._indexed(bundle["records"])
    if len(annotations) != 4 or set(annotations) != set(FOCUS_IDS):
        raise ValueError("Annotations must cover exactly the four historical focus-band targets.")
    originals = uv._indexed(original_review["target_records"])
    for sample, annotation in annotations.items():
        _annotation_header(annotation)
        if annotation["target_image"] != originals[sample]["input"]:
            raise ValueError("An annotation was reassigned to another target image.")
    return annotations


def _baseline_record(inputs, item, old, primary):
    row = item["registration"]
    candidate, comparison = mask._pixel_record(inputs, item)
    if (
        comparison["exact"] is not True
        or comparison != primary["pixel_comparison"]
        or candidate["pixel_counts"] != primary["layer_pixel_counts"]
        or row["mask_review"]["exclusions"] != primary["reviewed_exclusions"]
        or mask._decompose(inputs, item, old, candidate["reason"]) != primary["decomposition"]
    ):
        raise ValueError(
            "The old mask pixels, stages or contributor decomposition no longer match."
        )
    vectors = mask.load_vectors(
        inputs.read(old["correspondence"]), old["counts"]["all_unique_correspondence"]["requested"]
    )
    classification = uv._png(inputs.read(row["artifacts"]["classification"]), "L", (256, 256))
    return candidate, classification, vectors


def _png(array):
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format="PNG")
    data = stream.getvalue()
    if len(data) > uv.BINARY_LIMIT:
        raise ValueError("A candidate PNG exceeds its bounded artifact size.")
    return data


def _prepare_refinement(inputs, item, annotation, annotation_pin):
    row = item["registration"]
    width, height = item["fit"]["image_size"]
    old_allowed = (
        uv._png(inputs.read(row["mask_review"]["allowed_mask"]), "L", (width, height)) == 255
    )
    old_occluded = (
        uv._png(inputs.read(row["mask_review"]["occluded_mask"]), "L", (width, height)) == 255
    )
    layers = rasterize_annotations(annotation, width, height)
    refined = refine_masks(old_allowed, old_occluded, layers)
    payloads = {
        f"masks/{row['sample_id']}-{name}.png": _png(
            refined[name] if name == "labels" else refined[name].astype(np.uint8) * 255
        )
        for name in ("allowed", "occluded", "labels")
    }
    return refined, payloads


def _build_review(
    original_review,
    refinements,
    annotation_pin,
    output,
    root,
    roles,
    plan_pin,
    original_review_pin=None,
):
    if set(refinements) != set(FOCUS_IDS):
        raise ValueError("A full review can be prepared only from all four focus refinements.")
    historical = {
        "metadata": copy.deepcopy(
            {name: value for name, value in original_review.items() if name != "target_records"}
        ),
    }
    if original_review_pin is not None:
        historical["source"] = uv._pin(original_review_pin)
    review = {"target_records": copy.deepcopy(original_review["target_records"])}
    rows = uv._indexed(review["target_records"])
    if len(rows) != 37 or not set(FOCUS_IDS) <= rows.keys():
        raise ValueError("All37 original review rows must survive the candidate preparation.")
    for sample in FOCUS_IDS:
        row, result = rows[sample], refinements[sample]
        counts, artifacts = result["refinement"]["counts"], result["artifacts"]
        if set(artifacts) != {"allowed", "occluded", "labels"}:
            raise ValueError("Each refined target needs exactly three new mask artifacts.")
        for name, pin in artifacts.items():
            uv._pin(pin)
            if (
                pin["path"]
                != (Path(output) / f"masks/{sample}-{name}.png").relative_to(root).as_posix()
            ):
                raise ValueError("A new mask artifact was reassigned outside its candidate output.")
        prior = {
            key: copy.deepcopy(row[key])
            for key in ("allowed_mask", "occluded_mask", "exclusions", "method", "notes")
        }
        notes = [
            "AI development refinement: release only annotated skin inside the old band; "
            "protect glasses/lenses/frame/bridge envelopes plus a12 pixel square margin. "
            "All remaining old-band pixels remain excluded.",
            "This is not independent human quality acceptance or segmentation ground truth. "
            "Original saved masks, source geometry, target image and fit remain unchanged.",
        ]
        row.update(
            allowed_mask=artifacts["allowed"],
            occluded_mask=artifacts["occluded"],
            allowed_pixels=counts["new_allowed_pixels"],
            excluded_occluder_pixels=counts["new_occluded_pixels"],
            method="AI-reviewed explicit skin polygons within old B; protected-envelope12 pixel "
            "square margin; unreviewed old-band pixels remain excluded",
            notes=notes,
            exclusions=[
                {
                    "kind": "protected_and_unreviewed_old_band",
                    "annotation_package": annotation_pin,
                    "margin_pixels": MARGIN,
                    "prior_exclusions": prior["exclusions"],
                    "rule": "old_occluded & ~(skin & ~protected_margin)",
                }
            ],
            reviewer="codex_visual_review",
            status="reviewed_conservative_exclusion",
            reviewer_kind="ai",
            annotation_reviewer="codex-root-visual-observation",
            annotation_package=annotation_pin,
            label_mask=artifacts["labels"],
            prior_mask_evidence=prior,
            refinement_counts=counts,
            research_only=True,
            **dict.fromkeys(FALSE_FLAGS, False),
        )
    review.update(
        schema_version=1,
        protocol_id="agemorph3d-target-uv-v1",
        candidate_protocol_id=PROTOCOL_ID,
        recorded_at_utc=datetime.now(UTC).isoformat(),
        reviewer="codex_visual_review",
        reviewer_kind="ai",
        before_atlas_outcomes=False,
        before_candidate_registration=True,
        inherited_original_review_metadata=historical,
        mask_overlays_reviewed=False,
        mask_overlay_reviewed_before_atlas_outcomes=False,
        candidate_visual_qa_pending=True,
        mask_overlay_review_scope="New candidate overlays have not been viewed. Original review "
        "contacts and approvals describe only the inherited historical masks.",
        review_is_independent_human_quality_acceptance=False,
        candidate_files_created=True,
        saved_asset_semantics="Only separately versioned candidate PNGs are new; original saved "
        "masks remain unchanged. AI observations are not human or quality acceptance.",
        annotation_package=annotation_pin,
        study_plan=plan_pin,
        producer_protocol=roles["protocol"],
        parent_mask_report=roles["mask_report"],
        parent_mask_audit=roles["mask_audit"],
        research_only=True,
        **dict.fromkeys(FALSE_FLAGS, False),
    )
    return review, mask._encode(review)


def _invalidate(report, error):
    for row in report["records"]:
        row.pop("baseline", None)
        row.update(
            status="invalidated_input_drift",
            error_code="INPUT_DRIFT",
            detail=str(error),
            refinement=None,
            artifacts={},
        )
    report["artifacts"] = {}
    report["candidate_files_created"] = False
    report["summary"].update(
        statuses={"invalidated_input_drift": len(report["records"])},
        baseline_targets=0,
        all_baselines_verified=False,
        candidate_targets=0,
        published_mask_sets=0,
        unchanged_review_rows=0,
        all_requested_verified=False,
    )
    report["integrity"] = {"all_inputs_unchanged": False, "detail": str(error)}


def _encode(report):
    encoded = mask._encode(report)
    if len(encoded) > uv.META_LIMIT:
        raise ValueError("Candidate report exceeds its bounded JSON byte budget.")
    return encoded


def publish_batch(output, payloads, report, audit):
    """Publish an all-cohort candidate batch and remove only its own drifted files."""
    output = Path(output)
    expected = {"mask-review.json"} | {
        f"masks/{sample}-{name}.png"
        for sample in FOCUS_IDS
        for name in ("allowed", "occluded", "labels")
    }
    if (
        output.exists()
        or not isinstance(payloads, dict)
        or payloads
        and set(payloads) != expected
        or any(
            not isinstance(data, bytes)
            or len(data) > (uv.META_LIMIT if name.endswith(".json") else uv.BINARY_LIMIT)
            for name, data in payloads.items()
        )
        or sum(map(len, payloads.values())) > TOTAL_LIMIT
    ):
        raise ValueError(
            "Candidate output must be new, complete and within the fixed artifact layout."
        )
    if (
        payloads
        and (
            len(report["records"]) != 12
            or len({row["sample_id"] for row in report["records"]}) != 12
            or any(row["status"] != "ok" for row in report["records"])
            or report["summary"]["all_requested_verified"] is not True
        )
        or not payloads
        and report["summary"]["all_requested_verified"] is not False
    ):
        raise ValueError(
            "All12 baseline and preparation records must pass before publishing masks."
        )
    output.mkdir(parents=True, exist_ok=False)
    created = []
    destination = output / "report.json"
    report_created = False

    def invalidate(error):
        _invalidate(report, error)
        for path in created:
            path.unlink(missing_ok=True)

    try:
        audit()
        for name, data in payloads.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                created.append(path)
                stream.write(data)
        report["integrity"] = {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
            "verified_input_count": len(report["inputs"]),
        }
        with destination.open("xb") as stream:
            report_created = True
            stream.write(_encode(report))
        audit()
    except (OSError, ValueError) as error:
        invalidate(error)
        if report_created:
            destination.unlink()
        with destination.open("xb") as stream:
            stream.write(_encode(report))
    return report


def run(args):
    root = Path(args.root).resolve()
    output = uv._output_path(root, args.output_dir)
    plan_name = Path(args.study_plan)
    plan_path = (plan_name if plan_name.is_absolute() else root / plan_name).resolve()
    if root not in plan_path.parents:
        raise ValueError("Study plan must stay within the workspace.")
    with plan_path.open("rb") as stream:
        plan_bytes = stream.read(uv.META_LIMIT + 1)
    if len(plan_bytes) > uv.META_LIMIT:
        raise ValueError("Study plan exceeds its bounded JSON byte budget.")
    plan, runtime = uv._json(plan_bytes), uv.runtime_fingerprint()
    if (
        plan.get("schema_version") != 1
        or plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("runtime") != runtime
        or set(plan["roles"]) != set(ROLES)
    ):
        raise ValueError("Plan protocol, required roles or runtime fingerprint differs.")
    inputs, roles = uv.Inputs(root, plan["inputs"]), plan["roles"]
    metadata = {name: uv._json(inputs.read(roles[name], uv.META_LIMIT)) for name in ROLES}
    _protocol(metadata["protocol"])
    metadata["original_review"] = uv._json(
        inputs.read(metadata["mask_report"]["roles"]["mask_review"], uv.META_LIMIT)
    )
    inherited = derive_input_pins(metadata)
    if any(inputs.pins.get(pin["path"]) != pin for pin in inherited):
        raise ValueError("Freeze omits or changes a full37 review or annotation evidence pin.")
    required = (
        {pin["path"] for pin in inherited} | {pin["path"] for pin in roles.values()} | set(SOURCES)
    )
    if not required <= inputs.pins.keys():
        raise ValueError(
            "Freeze omits required baseline, candidate implementation or test sources."
        )
    if any(
        Path(name).suffix.lower() not in {".py", ".json", ".md", ".toml", ".lock"}
        for name in inputs.pins.keys() - required
    ):
        raise ValueError("New binary inputs must belong to the exact full-review/evidence closure.")
    if any(inputs.pins[name]["sha256"] != digest for name, digest in _LOADED_SOURCE_HASHES.items()):
        raise ValueError("Loaded Python implementation differs from its frozen source bytes.")
    selected, old_records = workbench.validate_evidence(inputs, roles, metadata)
    original_review = _validate_original_review(inputs, metadata)
    annotations = _validate_annotations(metadata["annotations"], original_review)
    snapshot_error = None
    try:
        for pin in inputs.pins.values():
            limit = (
                uv.BINARY_LIMIT
                if Path(pin["path"]).suffix.lower() in {".png", ".npz"}
                else uv.META_LIMIT
            )
            inputs.read(pin, limit)
    except (OSError, ValueError, KeyError, TypeError) as error:
        snapshot_error = error
    primary_rows = uv._indexed(metadata["mask_report"]["records"])
    records = []
    for item in selected:
        row = item["registration"]
        record = {
            "sample_id": row["sample_id"],
            "source_id": row["source_id"],
            "target_age_condition": row["target_age"],
            "source_age_label": row["source_age_label"],
            "source_age": dict(uv.UNKNOWN_AGE),
            "status": "failed",
            "refinement": None,
            "artifacts": {},
            "target_input": row["input"],
            "target_fit": row["target_fit"],
            "source_frame": row["source_frame"],
            "correspondence": old_records[row["sample_id"]]["correspondence"],
        }
        try:
            if snapshot_error is not None:
                raise ValueError(
                    "Complete verified input snapshot unavailable: " + str(snapshot_error)
                )
            primary = primary_rows[row["sample_id"]]
            _baseline_record(inputs, item, old_records[row["sample_id"]], primary)
            record.update(
                status="baseline_verified",
                baseline={
                    name: primary[name]
                    for name in ("pixel_comparison", "layer_pixel_counts", "decomposition")
                },
            )
        except (OSError, ValueError, KeyError, TypeError, IndexError, cv2.error) as error:
            record.update(
                error_code="BASELINE_VERIFICATION_FAILED",
                error_type=type(error).__name__,
                detail=str(error),
            )
        records.append(record)
        print(
            f"Conservative baseline {len(records)}/12: {row['sample_id']} {record['status']}",
            flush=True,
        )
    all_baselines = len(records) == 12 and all(
        row["status"] == "baseline_verified" for row in records
    )
    plan_pin = {
        "path": plan_path.relative_to(root).as_posix(),
        "bytes": len(plan_bytes),
        "sha256": uv._digest(plan_bytes),
    }
    payloads, refinements = {}, {}
    if all_baselines:
        for item, record in zip(selected, records, strict=True):
            sample = record["sample_id"]
            if sample not in annotations:
                record["status"] = "ok"
                continue
            try:
                refined, pngs = _prepare_refinement(
                    inputs, item, annotations[sample], roles["annotations"]
                )
                artifacts = {
                    name: {
                        "path": (output / f"masks/{sample}-{name}.png")
                        .relative_to(root)
                        .as_posix(),
                        "bytes": len(pngs[f"masks/{sample}-{name}.png"]),
                        "sha256": uv._digest(pngs[f"masks/{sample}-{name}.png"]),
                    }
                    for name in ("allowed", "occluded", "labels")
                }
                refinements[sample] = {
                    "refinement": {"counts": refined["counts"]},
                    "artifacts": artifacts,
                }
                payloads.update(pngs)
                record.update(status="ok", refinement=refined["counts"], artifacts=artifacts)
            except (OSError, ValueError, KeyError, TypeError, IndexError, cv2.error) as error:
                record.update(
                    status="refinement_failed",
                    error_code="CANDIDATE_PREPARATION_FAILED",
                    error_type=type(error).__name__,
                    detail=str(error),
                )
    complete = (
        all_baselines and len(refinements) == 4 and all(row["status"] == "ok" for row in records)
    )
    review_artifact = None
    if complete:
        try:
            _, review_bytes = _build_review(
                original_review,
                refinements,
                roles["annotations"],
                output,
                root,
                roles,
                plan_pin,
                original_review_pin=metadata["mask_report"]["roles"]["mask_review"],
            )
            if len(review_bytes) > uv.META_LIMIT:
                raise ValueError(
                    "The complete compatible37-row review exceeds its JSON byte budget."
                )
            payloads["mask-review.json"] = review_bytes
            review_artifact = {
                "path": (output / "mask-review.json").relative_to(root).as_posix(),
                "bytes": len(review_bytes),
                "sha256": uv._digest(review_bytes),
            }
        except (OSError, ValueError, KeyError, TypeError) as error:
            complete = False
            for row in records:
                row.update(
                    status="review_preparation_failed",
                    error_code="FULL_REVIEW_PREPARATION_FAILED",
                    detail=str(error),
                )
    if not complete:
        payloads.clear()
        for row in records:
            row.update(refinement=None, artifacts={})
            if row["status"] in {"baseline_verified", "ok"}:
                row.update(
                    status="baseline_verified_candidate_blocked", error_code="COHORT_GATE_FAILED"
                )
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **metadata["protocol"]["flags"],
        "candidate_files_created": complete,
        "study_plan": plan_pin,
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "records": records,
        "artifacts": {"mask_review": review_artifact} if complete else {},
        "label_codes": LABELS,
        "summary": {
            "requested_targets": 12,
            "requested_sources": 3,
            "review_targets": 37,
            "statuses": dict(Counter(row["status"] for row in records)),
            "baseline_targets": sum("baseline" in row for row in records),
            "all_baselines_verified": all_baselines,
            "candidate_targets": len(refinements) if complete else 0,
            "published_mask_sets": 4 if complete else 0,
            "all_requested_verified": complete,
            "unchanged_review_rows": 33 if complete else 0,
        },
        "interpretation": "Separately versioned AI conservative development candidate. "
        "Only annotated skin within old B may be released; protection and unreviewed pixels "
        "remain excluded. Original saved masks remain unchanged. No human, segmentation, age, "
        "identity, seam, G3 or production acceptance.",
    }

    def audit():
        inputs.recheck()
        with plan_path.open("rb") as stream:
            current = stream.read(uv.META_LIMIT + 1)
        if current != plan_bytes or uv.runtime_fingerprint() != runtime:
            raise ValueError("Study plan, frozen sources/inputs or exact runtime drifted.")

    return publish_batch(output, payloads, report, audit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args)
        print(mask._encode(report["summary"]).decode("utf-8").strip())
        return 0 if report["summary"]["all_requested_verified"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
