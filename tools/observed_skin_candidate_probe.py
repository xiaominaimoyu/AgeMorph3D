"""Publish frozen, separately versioned observed-forehead masks without inference.

The extension is explicit observed skin outside protected envelopes. It need not
be inside the historical landmark hull. Original pixels and other33 review rows
remain unchanged; AI development observation never grants quality acceptance.
"""

# Offline entrypoint; imported validators do not run inference or registration.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

import conservative_mask_probe as prior
import cv2
import numpy as np

uv = prior.uv
PROTOCOL_ID = "agemorph3d-observed-skin-candidate-v1"
ANNOTATION_ID = "agemorph3d-observed-skin-annotations-v1"
ROLES = ("protocol", "parent_review", "annotations", "parent_annotations")
FOCUS_IDS = prior.FOCUS_IDS
SOURCES = (
    *prior.SOURCES,
    "tools/observed_skin_candidate_probe.py",
    "backend/tests/test_observed_skin_candidate_probe.py",
    ".gitignore",
)
FALSE_FLAGS = (*prior.FALSE_FLAGS, "years_calibrated", "legal_permission_established")
LABELS = {"unchanged_other": 0, "newly_allowed": 1, "protected_margin": 2, "old_occluded": 3}
TOTAL_LIMIT = 96 * 1024**2
_LOADED_SOURCE_HASHES = {
    name: uv._digest((_ROOT / name).read_bytes())
    for name in SOURCES
    if name.endswith(".py") and "/tests/" not in name
}
runtime_fingerprint = uv.runtime_fingerprint


def _encode(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()


def _json(data):
    """Reject JSON exponent overflow as well as explicit NaN/Infinity constants."""
    value = uv._json(data)

    def check(item, depth=0):
        if depth > 64:
            raise ValueError("Metadata nesting exceeds its bounded schema.")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Non-finite JSON number, including exponent overflow.")
        if isinstance(item, dict):
            for nested in item.values():
                check(nested, depth + 1)
        elif isinstance(item, list):
            for nested in item:
                check(nested, depth + 1)

    check(value)
    return value


def _bounded(path, count):
    with path.open("rb") as stream:
        return stream.read(count + 1)


class Inputs(uv.Inputs):
    """Read and recheck at most the declared positive length plus one byte."""

    def read(self, value, max_bytes=uv.BINARY_LIMIT):
        pin = uv._pin(value)
        if self.pins.get(pin["path"]) != pin or pin["bytes"] > max_bytes:
            raise ValueError("Input is absent from the closed freeze or exceeds its byte bound.")
        if pin["path"] not in self.snapshots:
            data = _bounded(uv._relative(self.root, pin["path"]), pin["bytes"])
            if len(data) != pin["bytes"] or uv._digest(data) != pin["sha256"]:
                raise ValueError("Input pin mismatch: " + pin["path"])
            self.snapshots[pin["path"]] = data
        return self.snapshots[pin["path"]]

    def recheck(self):
        for pin in self.pins.values():
            data = _bounded(uv._relative(self.root, pin["path"]), pin["bytes"])
            if len(data) != pin["bytes"] or uv._digest(data) != pin["sha256"]:
                raise ValueError("Input drift after calculation: " + pin["path"])


def derive_input_pins(metadata):
    """Return only the four focus image/fit/old-mask pins actually read here.

    Callers must also freeze all four role pins and SOURCES. Descendant pins in
    inherited33 review objects are preserved as evidence, never recursively read.
    """
    rows = uv._indexed(metadata["parent_review"]["target_records"])
    if len(rows) != 37 or not set(FOCUS_IDS) <= rows.keys():
        raise ValueError("The exact full37 parent review with all four focus targets is required.")
    pins = {}
    for sample in FOCUS_IDS:
        for name in ("input", "target_fit", "allowed_mask", "occluded_mask"):
            pin = uv._pin(rows[sample][name])
            if pin["path"] in pins and pins[pin["path"]] != pin:
                raise ValueError("Conflicting focus input pins.")
            pins[pin["path"]] = pin
    return list(pins.values())


def _protocol(value):
    cohort = value["cohort"]
    if (
        value.get("schema_version") != 1
        or value.get("protocol_id") != PROTOCOL_ID
        or cohort["focus"] != list(FOCUS_IDS)
        or cohort["targets"] != 37
        or cohort["sources"] != 10
        or cohort["source_age_api"] != uv.UNKNOWN_AGE
        or cohort["new_sam_or_fit"] is not False
        or cohort["heldout_opened"] is not False
        or value["annotations"]["protocol_id"] != ANNOTATION_ID
        or value["annotations"]["reviewer_kind"] != "ai"
        or value["freezing"]["roles"] != list(ROLES)
        or value["composition"]["allowed"]
        != "old_conservative_allowed OR (explicit_forehead_skin AND NOT dilated_protected)"
        or value["composition"]["occluded"] != "old_conservative_occluded AND NOT newly_allowed"
        or value["flags"].get("research_only") is not True
        or any(flag is not False for key, flag in value["flags"].items() if key != "research_only")
        or not {
            "human_review_completed",
            "usable_mask_candidate_accepted",
            "g3_complete",
            "service_ready",
            "production_enabled",
            "years_calibrated",
        }
        <= value["flags"].keys()
    ):
        raise ValueError(
            "Unsupported observed-skin protocol, cohort, composition or quality scope."
        )


def validate_annotations(metadata):
    parent, bundle, inherited = (
        metadata[name] for name in ("parent_review", "annotations", "parent_annotations")
    )
    if (
        parent.get("schema_version") != 1
        or parent.get("protocol_id") != "agemorph3d-target-uv-v1"
        or parent.get("candidate_protocol_id") != prior.PROTOCOL_ID
        or bundle.get("schema_version") != 1
        or bundle.get("protocol_id") != ANNOTATION_ID
        or bundle.get("reviewer_kind") != "ai"
        or bundle.get("human_review_completed") is not False
        or bundle.get("before_new_mask_and_atlas") is not True
        or bundle.get("historical_results_seen") is not True
        or inherited.get("schema_version") != 1
        or inherited.get("protocol_id") != "agemorph3d-conservative-mask-annotations-v1"
    ):
        raise ValueError("Annotation lineage, development scope or parent protocol differs.")
    rows, annotations, old = (
        uv._indexed(value)
        for value in (parent["target_records"], bundle["records"], inherited["records"])
    )
    if len(rows) != 37 or set(annotations) != set(FOCUS_IDS) or set(old) != set(FOCUS_IDS):
        raise ValueError("Exactly four annotations and the complete37 parent review are required.")
    for sample, annotation in annotations.items():
        if (
            annotation.get("input") != rows[sample]["input"]
            or annotation.get("target_fit") != rows[sample]["target_fit"]
            or annotation.get("input") != old[sample]["target_image"]
            or annotation.get("protected_polygons") != old[sample]["protected_polygons"]
            or old[sample].get("margin_pixels") != 12
            or annotation.get("source_age_api") != uv.UNKNOWN_AGE
            or annotation.get("reviewer_kind") != "ai"
            or annotation.get("reviewer") != "codex-root-native-target-observation"
        ):
            raise ValueError("Focus image/fit, unknown age or inherited protection was reassigned.")
    return annotations


def rasterize(annotation, width, height):
    """Union validated native integer polygons with the inherited12 pixel margin."""
    prior.mask._dimensions(width, height)
    groups = [annotation.get(name) for name in ("skin_polygons", "protected_polygons")]
    if any(not isinstance(group, list) or not 1 <= len(group) <= 64 for group in groups):
        raise ValueError("Each category requires1..64 explicit polygons.")
    if sum(len(p) if isinstance(p, list) else 4097 for group in groups for p in group) > 4096:
        raise ValueError("The annotation exceeds its4096 vertex budget.")
    layers = []
    for group in groups:
        polygons = [prior._polygon(points, width, height) for points in group]
        pixels = np.zeros((height, width), np.uint8)
        for polygon in polygons:
            cv2.fillPoly(pixels, [polygon], 1, lineType=cv2.LINE_8, shift=0)
        layers.append(pixels != 0)
    return {"skin": layers[0], "protected": layers[1], "protected_margin": prior._dilate(layers[1])}


def extend_masks(old_allowed, old_occluded, layers):
    """Add explicit unprotected skin even outside both historical masks."""
    uv._masks(old_allowed, old_occluded)
    if (
        not isinstance(layers, dict)
        or set(layers) != {"skin", "protected", "protected_margin"}
        or any(
            not isinstance(a, np.ndarray) or a.dtype != np.bool_ or a.shape != old_allowed.shape
            for a in layers.values()
        )
        or not np.array_equal(layers["protected_margin"], prior._dilate(layers["protected"]))
    ):
        raise ValueError(
            "The three boolean annotation layers require the exact native frame/margin."
        )
    skin, margin = layers["skin"], layers["protected_margin"]
    added = skin & ~margin & ~old_allowed
    allowed, occluded = old_allowed | added, old_occluded & ~added
    uv._masks(allowed, occluded)
    labels = np.zeros(old_allowed.shape, np.uint8)
    labels[old_occluded] = LABELS["old_occluded"]
    labels[margin] = LABELS["protected_margin"]
    labels[added] = LABELS["newly_allowed"]
    return {
        "allowed": allowed,
        "occluded": occluded,
        "labels": labels,
        "counts": {
            "old_allowed_pixels": int(old_allowed.sum()),
            "old_occluded_pixels": int(old_occluded.sum()),
            "skin_pixels": int(skin.sum()),
            "protected_pixels": int(layers["protected"].sum()),
            "protected_margin_pixels": int(margin.sum()),
            "newly_allowed_pixels": int(added.sum()),
            "newly_allowed_outside_old_occluded_pixels": int(
                np.count_nonzero(added & ~old_occluded)
            ),
            "newly_allowed_protected_pixels": int(np.count_nonzero(added & margin)),
            "inherited_allowed_protected_pixels": int(np.count_nonzero(old_allowed & margin)),
            "new_allowed_pixels": int(allowed.sum()),
            "new_occluded_pixels": int(occluded.sum()),
            "label_pixels": {str(code): int(np.count_nonzero(labels == code)) for code in range(4)},
        },
    }


def build_review(parent, refinements, roles, plan_pin):
    """Keep other33 whole objects and isolate all inherited approval metadata."""
    if set(refinements) != set(FOCUS_IDS):
        raise ValueError("All four refinements are required before building a full review.")
    review = {"target_records": copy.deepcopy(parent["target_records"])}
    rows = uv._indexed(review["target_records"])
    if len(rows) != 37:
        raise ValueError("The compatible full37 review is required.")
    for sample in FOCUS_IDS:
        row, result = rows[sample], refinements[sample]
        inherited_row = copy.deepcopy(row)
        for name in ("label_mask", "refinement_counts", "prior_mask_evidence"):
            row.pop(name, None)
        row.update(
            allowed_mask=result["artifacts"]["allowed"],
            occluded_mask=result["artifacts"]["occluded"],
            allowed_pixels=result["refinement"]["new_allowed_pixels"],
            excluded_occluder_pixels=result["refinement"]["new_occluded_pixels"],
            # These two exact compatibility values are required by target_uv's validator.
            reviewer="codex_visual_review",
            status="reviewed_conservative_exclusion",
            reviewer_kind="ai",
            annotation_reviewer="codex-root-native-target-observation",
            annotation_package=roles["annotations"],
            method="AI observed forehead-skin extension; explicit LINE8 polygons outside inherited "
            "protected glasses/lens/frame/bridge plus12 native-pixel margin; "
            "original allowed retained",
            notes=[
                "Development revision after seeing historical results, before new candidate "
                "outcomes. Skin may extend outside the old landmark hull or B band; "
                "no lens-visible eye release.",
                "Compatibility reviewer/status identify the offline validator contract, not human "
                "approval. Unknown pixels are not filled and all quality acceptance remains false.",
            ],
            exclusions=[
                {
                    "kind": "inherited_occlusion_except_explicit_unprotected_forehead",
                    "annotation_package": roles["annotations"],
                    "margin_pixels": 12,
                    "rule": "old_occluded AND NOT newly_allowed",
                    "prior_exclusions": inherited_row["exclusions"],
                }
            ],
            label_mask=result["artifacts"]["labels"],
            observed_skin_counts=result["refinement"],
            inherited_parent_review=inherited_row,
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
        before_candidate_registration=True,
        before_atlas_outcomes=False,
        mask_overlays_reviewed=False,
        mask_overlay_reviewed_before_atlas_outcomes=False,
        candidate_visual_qa_pending=True,
        review_is_independent_human_quality_acceptance=False,
        candidate_files_created=True,
        annotation_package=roles["annotations"],
        study_plan=plan_pin,
        producer_protocol=roles["protocol"],
        parent_review=roles["parent_review"],
        inherited_parent_metadata={
            key: copy.deepcopy(value) for key, value in parent.items() if key != "target_records"
        },
        saved_asset_semantics="Only separately versioned candidate files are new; no original "
        "asset is overwritten. New overlays await separate AI observation, not human acceptance.",
        research_only=True,
        **dict.fromkeys(FALSE_FLAGS, False),
    )
    return review


def publish_batch(output, payloads, audit):
    """Stage a complete batch, verify again, rename once; roll back only our files."""
    output = Path(output)
    if (
        output.exists()
        or not payloads
        or any(
            Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name
            for name in payloads
        )
    ):
        raise ValueError("Publication requires a fresh output and bounded relative artifact names.")
    if sum(len(data) for data in payloads.values()) > TOTAL_LIMIT:
        raise ValueError("Candidate artifacts exceed the total byte budget.")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=output.name + ".preparing-", dir=output.parent))
    published = False
    try:
        audit()
        for name, data in payloads.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(data)
        audit()
        if output.exists():
            raise ValueError("Another output appeared before atomic publication.")
        os.rename(temporary, output)
        published = True
        audit()
    except BaseException:
        # Both directories are exclusively owned by this invocation, never inherited assets.
        shutil.rmtree(output if published else temporary)
        raise


def run(args):
    root = Path(args.root).resolve()
    output = uv._output_path(root, args.output_dir)
    plan_name = Path(args.study_plan)
    plan_path = (plan_name if plan_name.is_absolute() else root / plan_name).resolve()
    if root not in plan_path.parents:
        raise ValueError("Study plan must stay inside the workspace.")
    plan_bytes = _bounded(plan_path, uv.META_LIMIT)
    if len(plan_bytes) > uv.META_LIMIT:
        raise ValueError("Study plan exceeds the JSON byte budget.")
    plan, runtime = _json(plan_bytes), runtime_fingerprint()
    if (
        plan.get("schema_version") != 1
        or plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("runtime") != runtime
        or set(plan["roles"]) != set(ROLES)
    ):
        raise ValueError("Study plan protocol, roles or current runtime differs.")
    inputs, roles = Inputs(root, plan["inputs"]), plan["roles"]
    metadata = {name: _json(inputs.read(roles[name], uv.META_LIMIT)) for name in ROLES}
    _protocol(metadata["protocol"])
    if roles["parent_review"]["path"] != metadata["protocol"]["cohort"]["parent_review"]:
        raise ValueError("Parent review was reassigned away from the declared lineage.")
    annotations = validate_annotations(metadata)
    if metadata["parent_review"].get("annotation_package") != roles["parent_annotations"] or any(
        row.get("annotation_package") != roles["parent_annotations"]
        for row in metadata["parent_review"]["target_records"]
        if row["sample_id"] in FOCUS_IDS
    ):
        raise ValueError("Inherited protection must bind the parent's exact annotation package.")
    required = {pin["path"]: pin for pin in [*roles.values(), *derive_input_pins(metadata)]}
    if set(inputs.pins) != set(required) | set(SOURCES):
        raise ValueError(
            "Freeze must exactly close roles, focus assets and implementation/test sources."
        )
    if any(inputs.pins[name] != pin for name, pin in required.items()):
        raise ValueError("A required metadata or focus input pin differs.")
    if any(inputs.pins[name]["sha256"] != digest for name, digest in _LOADED_SOURCE_HASHES.items()):
        raise ValueError("Loaded implementation differs from its frozen source bytes.")
    if sum(pin["bytes"] for pin in inputs.pins.values()) > TOTAL_LIMIT:
        raise ValueError("Declared input set exceeds the total byte budget.")
    for pin in inputs.pins.values():
        limit = uv.BINARY_LIMIT if Path(pin["path"]).suffix in {".png", ".npz"} else uv.META_LIMIT
        inputs.read(pin, limit)
    plan_pin = {
        "path": plan_path.relative_to(root).as_posix(),
        "bytes": len(plan_bytes),
        "sha256": uv._digest(plan_bytes),
    }
    rows = uv._indexed(metadata["parent_review"]["target_records"])
    payloads, refinements, records = {}, {}, []
    for sample in FOCUS_IDS:
        row = rows[sample]
        image = uv._png(inputs.read(row["input"]), "RGB", (1024, 1024))
        masks = [
            uv._png(inputs.read(row[name]), "L", (1024, 1024))
            for name in ("allowed_mask", "occluded_mask")
        ]
        if any(not np.all((pixels == 0) | (pixels == 255)) for pixels in masks):
            raise ValueError("Historical masks must be binary native1024 PNGs.")
        old_allowed, old_occluded = [pixels == 255 for pixels in masks]
        if row["allowed_pixels"] != int(old_allowed.sum()) or row[
            "excluded_occluder_pixels"
        ] != int(old_occluded.sum()):
            raise ValueError("Historical review counts differ from verified mask pixels.")
        layers = rasterize(annotations[sample], 1024, 1024)
        result = extend_masks(old_allowed, old_occluded, layers)
        overlay = image.copy()
        added = result["allowed"] & ~old_allowed
        for selection, color in (
            (layers["protected_margin"], [255, 60, 60]),
            (added, [60, 255, 100]),
        ):
            overlay[selection] = np.rint(
                overlay[selection].astype(np.float64) * 0.5 + np.asarray(color) * 0.5
            ).astype(np.uint8)
        arrays = {name: result[name] for name in ("allowed", "occluded", "labels")}
        arrays.update(layers, overlay=overlay)
        artifacts = {}
        for name, pixels in arrays.items():
            if pixels.dtype == np.bool_:
                pixels = pixels.astype(np.uint8) * 255
            relative = f"masks/{sample}-{name.replace('_', '-')}.png"
            data = prior._png(pixels)
            payloads[relative] = data
            artifacts[name] = {
                "path": (output / relative).relative_to(root).as_posix(),
                "bytes": len(data),
                "sha256": uv._digest(data),
            }
        refinements[sample] = {"refinement": result["counts"], "artifacts": artifacts}
        records.append(
            {
                "sample_id": sample,
                "status": "ok",
                "input": row["input"],
                "target_fit": row["target_fit"],
                **refinements[sample],
            }
        )
    review = build_review(metadata["parent_review"], refinements, roles, plan_pin)
    payloads["mask-review.json"] = _encode(review)
    if len(payloads["mask-review.json"]) > uv.META_LIMIT:
        raise ValueError("Full37 review exceeds the metadata byte budget.")
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "study_plan": plan_pin,
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "records": records,
        "label_codes": LABELS,
        "label_priority": "0 then old_occluded3 then all protected_margin2 then newly_allowed1; "
        "diagnostic labels do not remove inherited allowed pixels",
        "summary": {
            "requested_targets": 4,
            "statuses": {"ok": 4},
            "published_mask_sets": 4,
            "unchanged_review_rows": 33,
            "full_review_targets": 37,
            "all_requested_verified": True,
        },
        "artifacts": {
            "mask_review": {
                "path": (output / "mask-review.json").relative_to(root).as_posix(),
                "bytes": len(payloads["mask-review.json"]),
                "sha256": uv._digest(payloads["mask-review.json"]),
            }
        },
        "candidate_files_created": True,
        "candidate_visual_qa_pending": True,
        "integrity": {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
            "verified_input_count": len(inputs.pins),
        },
        "research_only": True,
        **dict.fromkeys(FALSE_FLAGS, False),
    }
    payloads["report.json"] = _encode(report)

    def audit():
        inputs.recheck()
        if _bounded(plan_path, len(plan_bytes)) != plan_bytes:
            raise ValueError("Study plan drift before publication.")
        if runtime_fingerprint() != runtime:
            raise ValueError("Runtime drift before publication.")

    publish_batch(output, payloads, audit)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(_ROOT))
    parser.add_argument("--study-plan", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    report = run(args)
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
