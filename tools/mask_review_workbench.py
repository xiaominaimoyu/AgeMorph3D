"""Export a bounded, self-contained, read-only review of frozen mask evidence.

This offline entrypoint rechecks the old pixel gate before embedding original
PNG bytes and exact saved correspondence arrays. It never opens a listener,
infers a model, changes a mask, or accepts human/visual/production quality.
"""

# Standalone offline entrypoint using the already frozen mask/UV validators.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

import cv2
import mask_replay_probe as mask
import numpy as np

uv = mask.uv
PROTOCOL_ID = "agemorph3d-mask-review-workbench-v1"
ROLES = ("protocol", "mask_report", "mask_audit", "uv_report")
SOURCES = (
    *mask.SOURCES,
    "tools/mask_review_workbench.py",
    "frontend/research/mask-review.mjs",
    "frontend/research/mask-review.html",
    "backend/tests/test_mask_review_workbench.py",
    "frontend/tests/mask-review.test.ts",
)
FALSE_FLAGS = (*mask.FALSE_FLAGS, "human_review_completed")
PAGE_LIMIT = 16 * 1024**2
TOTAL_PAGE_LIMIT = 192 * 1024**2
MARKERS = ("__WORKBENCH_DATA__", "__WORKBENCH_SCRIPT__", "__WORKBENCH_SCRIPT_HASH__")
VECTOR_FIELDS = {
    "texel_rows_columns": "rows_columns_i32",
    "face_owner": "face_owner_i32",
    "barycentric": "barycentric_f64",
    "target_xyz": "target_xyz_f64",
    "source_canonical_xyz": "source_canonical_xyz_f64",
    "region_bits": "region_bits_u8",
    "rejection_partition": "rejection_partition_u8",
}
_LOADED_SOURCE_HASHES = {
    name: uv._digest((_ROOT / name).read_bytes())
    for name in SOURCES
    if name.endswith(".py") and "/tests/" not in name
}


def encode_rle(array, *, max_label=255):
    """Encode bounded integer labels as flat [value,count,...] row-major runs."""
    values = np.asarray(array)
    if (
        values.dtype.kind not in "iu"
        or values.ndim not in (1, 2)
        or values.size < 1
        or values.size > uv.PIXEL_LIMIT
        or type(max_label) is not int
        or not 0 <= max_label <= 255
        or np.any(values < 0)
        or np.any(values > max_label)
    ):
        raise ValueError("RLE requires bounded nonempty integer labels in the declared range.")
    flat = values.ravel(order="C")
    boundaries = np.r_[0, np.flatnonzero(flat[1:] != flat[:-1]) + 1, flat.size]
    answer = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        answer.extend((int(flat[start]), int(end - start)))
    return answer


def encode_vectors(vectors):
    """Preserve every saved integer/float byte in little-endian C order."""
    if not isinstance(vectors, dict) or set(vectors) != set(mask.VECTOR_NAMES):
        raise ValueError("Exactly the seven saved correspondence arrays are required.")
    if not isinstance(vectors["face_owner"], np.ndarray) or vectors["face_owner"].ndim != 1:
        raise ValueError("Saved correspondence owners must be a one-dimensional integer array.")
    count = len(vectors["face_owner"])
    if not 0 <= count <= 65536:
        raise ValueError("Correspondence row count exceeds the frozen atlas domain.")
    answer = {"count": count}
    for name, field in VECTOR_FIELDS.items():
        array = vectors[name]
        columns = (
            2
            if name == "texel_rows_columns"
            else 3
            if name in {"barycentric", "target_xyz", "source_canonical_xyz"}
            else None
        )
        shape = (count, columns) if columns else (count,)
        if (
            not isinstance(array, np.ndarray)
            or array.shape != shape
            or array.dtype != mask.VECTOR_DTYPES[name]
            or array.dtype.hasobject
            or array.dtype.kind == "f"
            and not np.isfinite(array).all()
        ):
            raise ValueError("Saved vector shape, dtype or finite-coordinate binding differs.")
        raw = np.ascontiguousarray(array, dtype=mask.VECTOR_DTYPES[name]).tobytes(order="C")
        answer[field] = base64.b64encode(raw).decode("ascii")
    return answer


def embedded_json(value):
    """JSON is data even when an observation contains an HTML closing tag."""
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_case_document(payload, template, script):
    """Bind exact module bytes to CSP and reject ambiguous template expansion."""
    if not isinstance(template, str) or not isinstance(script, str):
        raise ValueError("Template and app must be exact UTF-8 text snapshots.")
    if "\r" in script:
        raise ValueError("App source must use LF endings so HTML parsing preserves its CSP bytes.")
    if any(template.count(marker) != 1 for marker in MARKERS):
        raise ValueError("Every workbench template marker must appear exactly once.")
    if re.search(r"</script|<!--", script, re.IGNORECASE):
        raise ValueError("App source contains an HTML closing-script fragment.")
    if "sha256-__WORKBENCH_SCRIPT_HASH__" not in template:
        raise ValueError("Template must authorize the exact inline module with its CSP hash.")
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    replacements = (embedded_json(payload), script, digest)
    # A single substitution pass prevents untrusted data being treated as a marker.
    mapping = dict(zip(MARKERS, replacements, strict=True))
    document = re.sub("|".join(map(re.escape, MARKERS)), lambda match: mapping[match[0]], template)
    encoded = document.encode("utf-8")
    if len(encoded) > PAGE_LIMIT:
        raise ValueError("Self-contained case exceeds its sixteen-MiB page budget.")
    return encoded


def derive_input_pins(metadata):
    """Inherit every old pin, report/plan binding and independent audit source."""
    primary, audit = metadata["mask_report"], metadata["mask_audit"]
    pins = {}
    for value in [*primary["inputs"], primary["study_plan"], audit["independent_script"]]:
        pin = uv._pin(value)
        if pin["path"] in pins and pins[pin["path"]] != pin:
            raise ValueError("Conflicting inherited mask evidence pins.")
        pins[pin["path"]] = pin
    return list(pins.values())


def _closed_flags(value, flags):
    return value.get("research_only") is True and all(value.get(key) is False for key in flags)


def _protocol(protocol):
    if (
        protocol.get("schema_version") != 1
        or protocol.get("protocol_id") != PROTOCOL_ID
        or protocol["cohort"]["sources"] != uv.COHORT
        or protocol["cohort"]["expected_targets"] != 12
        or protocol["cohort"]["group"] != "development"
        or protocol["cohort"]["api_source_age"] != uv.UNKNOWN_AGE
        or protocol["quality_threshold"] is not None
        or protocol["flags"] != {"research_only": True, **dict.fromkeys(FALSE_FLAGS, False)}
        or protocol["delivery"]["limits"]
        != {
            "page_bytes": PAGE_LIMIT,
            "total_page_bytes": TOTAL_PAGE_LIMIT,
            "targets": 12,
            "vector_rows": 65536,
            "image_pixels": uv.PIXEL_LIMIT,
        }
    ):
        raise ValueError("Unsupported workbench protocol, cohort, bounds or closed flags.")


def validate_evidence(inputs, roles, metadata):
    """Require the whole old cohort and its exact independent arithmetic audit."""
    primary, audit = metadata["mask_report"], metadata["mask_audit"]
    if (
        primary.get("schema_version") != 1
        or primary.get("protocol_id") != mask.PROTOCOL_ID
        or not _closed_flags(primary, mask.FALSE_FLAGS)
        or len(primary["inputs"]) != 130
        or primary["runtime"] != uv.runtime_fingerprint()
        or primary["roles"]["uv_report"] != roles["uv_report"]
        or primary["summary"]["requested_targets"] != 12
        or primary["summary"]["all_masks_pixel_equal"] is not True
        or primary["summary"]["all_requested_verified"] is not True
        or primary["summary"]["decomposition_targets"] != 12
        or primary["integrity"]
        != {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
            "verified_input_count": 130,
        }
    ):
        raise ValueError("The complete successful frozen 130-input mask replay is required.")
    if (
        audit.get("schema_version") != 1
        or audit.get("audit_protocol") != "independent-mask-replay-audit-v1"
        or audit.get("status") != "passed"
        or not _closed_flags(audit, mask.FALSE_FLAGS)
        or audit["primary_report"] != roles["mask_report"]
        or audit["study_plan"] != primary["study_plan"]
        or audit["runtime"] != primary["runtime"]
        or audit["verified_input_count"] != 130
        or audit["imports_project_implementation"] is not False
        or audit["all_masks_pixel_equal"] is not True
        or audit["all_primary_diagnostics_equal"] is not True
        or audit["decomposition_targets"] != 12
        or audit["source_age_defaults_introduced"] != 0
        or audit["integrity"]
        != {
            "all_inputs_unchanged_before_publication": True,
            "plan_report_script_unchanged_before_publication": True,
            "runtime_unchanged_before_publication": True,
        }
    ):
        raise ValueError("Independent audit must bind this exact complete mask report and runtime.")
    old_plan = uv._json(inputs.read(primary["study_plan"], uv.META_LIMIT))
    if (
        old_plan.get("schema_version") != 1
        or old_plan.get("protocol_id") != mask.PROTOCOL_ID
        or old_plan["inputs"] != primary["inputs"]
        or old_plan["roles"] != primary["roles"]
        or old_plan["runtime"] != primary["runtime"]
    ):
        raise ValueError("The original study plan must bind all130 exact pins, roles and runtime.")
    old_metadata = {
        name: uv._json(inputs.read(primary["roles"][name], uv.META_LIMIT)) for name in mask.ROLES
    }
    if old_metadata["uv_report"] != metadata["uv_report"]:
        raise ValueError("The UV report was reassigned after the mask replay.")
    mask._protocol(old_metadata["protocol"])
    selected, old_records = mask._selected(inputs, primary["roles"], old_metadata)
    primary_rows, audit_rows = uv._indexed(primary["records"]), uv._indexed(audit["records"])
    expected = {item["registration"]["sample_id"] for item in selected}
    if len(expected) != 12 or set(primary_rows) != expected or set(audit_rows) != expected:
        raise ValueError("Mask evidence and audit must retain the exact twelve-target denominator.")
    for item in selected:
        row = item["registration"]
        saved, independent = primary_rows[row["sample_id"]], audit_rows[row["sample_id"]]
        if (
            saved["status"] != "ok"
            or saved["source_id"] != row["source_id"]
            or saved["target_age_condition"] != row["target_age"]
            or saved["source_age_label"] != row["source_age_label"]
            or saved["source_age"] != uv.UNKNOWN_AGE
            or saved["pixel_comparison"]["exact"] is not True
            or independent["primary_diagnostics_equal"] is not True
            or independent["independent_partition_region_count_check"] is not True
            or any(
                independent[name] != saved[name]
                for name in ("pixel_comparison", "layer_pixel_counts", "decomposition")
            )
        ):
            raise ValueError("Target pixel, age, stage or independent diagnostic binding differs.")
    return selected, old_records


def _image_uri(data):
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _case_payload(inputs, item, old, primary, provenance, navigation):
    row, fit = item["registration"], item["fit"]
    candidate, comparison = mask._pixel_record(inputs, item)
    if (
        comparison["exact"] is not True
        or comparison != primary["pixel_comparison"]
        or candidate["pixel_counts"] != primary["layer_pixel_counts"]
        or row["mask_review"]["exclusions"] != primary["reviewed_exclusions"]
    ):
        raise ValueError("Original masks or reconstructed stage totals differ from frozen replay.")
    decomposition = mask._decompose(inputs, item, old, candidate["reason"])
    if decomposition != primary["decomposition"]:
        raise ValueError("Recomputed vector contribution totals differ from the frozen replay.")
    vectors = mask.load_vectors(
        inputs.read(old["correspondence"]), old["counts"]["all_unique_correspondence"]["requested"]
    )
    classification = uv._png(inputs.read(row["artifacts"]["classification"]), "L", (256, 256))
    saved = uv.safe_npz(inputs.read(row["artifacts"]["samples"]), uv.SAMPLE_NAMES)
    if not np.array_equal(classification, saved["classification"]):
        raise ValueError("Saved classification PNG/NPZ bytes disagree.")
    width, height = fit["image_size"]
    image_pins = {
        "target": row["input"],
        "allowed": row["mask_review"]["allowed_mask"],
        "occluded": row["mask_review"]["occluded_mask"],
        "atlas": row["artifacts"]["atlas"],
    }
    image_bytes = {name: inputs.read(pin) for name, pin in image_pins.items()}
    uv._png(image_bytes["target"], "RGB", (width, height))
    atlas = uv._png(image_bytes["atlas"], "RGBA", (256, 256))
    if not np.array_equal(atlas, saved["rgba"]):
        raise ValueError("Original atlas PNG differs from its saved NPZ pixels.")
    landmarks, rounded = mask._landmarks(np.asarray(fit["projected_landmarks"])[:, :2])
    return {
        "schemaVersion": 1,
        "protocolId": PROTOCOL_ID,
        "sampleId": row["sample_id"],
        "sourceId": row["source_id"],
        "targetAgeCondition": row["target_age"],
        "sourceAgeApi": dict(uv.UNKNOWN_AGE),
        "sourceAgeLabel": row["source_age_label"],
        "width": width,
        "height": height,
        "landmarksXY": landmarks.tolist(),
        "roundedLandmarksXY": rounded.tolist(),
        "regionBoxes": old["region_boxes_xyxy"],
        "regionBitOrder": list(uv.REGIONS),
        "classificationCodes": uv.REASONS,
        "pixelReasonCodes": mask.PIXEL_REASONS,
        "rejectionPartitionCodes": uv.REJECTION_CODES,
        "classificationRLE": encode_rle(classification, max_label=6),
        "reasonRLE": encode_rle(candidate["reason"], max_label=4),
        "images": {name: _image_uri(data) for name, data in image_bytes.items()},
        "vectors": encode_vectors(vectors),
        "provenance": {
            **provenance,
            "images": image_pins,
            "correspondence": old["correspondence"],
            "sourceFrame": row["source_frame"],
        },
        "navLinks": navigation,
        "indexHref": "../index.html",
        "flags": {"research_only": True, **dict.fromkeys(FALSE_FLAGS, False)},
    }


def render_index(records):
    links = "".join(
        '<li><a href="cases/'
        + html.escape(row["sample_id"], quote=True)
        + '.html">'
        + html.escape(row["sample_id"])
        + "</a></li>"
        for row in records
    )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; connect-src 'none'\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>冻结遮罩审查工作台</title>"
        "<style>body{max-width:60rem;margin:3rem auto;padding:1rem;background:#0a0e1a;"
        "color:#e9eef6;font:16px/1.7 'Segoe UI','Microsoft YaHei',sans-serif}"
        "a{color:#35d3c0}li{margin:.6rem 0}</style>"
        "<h1>冻结遮罩审查工作台</h1>"
        "<p>12个开发目标的本地只读证据。未知源龄保持未知，目标年龄仅为生成条件。</p>"
        "<p>页面导出成功不代表人工审查完成、真实遮挡确认或质量、服务、G3验收。</p>"
        "<ul>" + links + "</ul></html>"
    ).encode("utf-8")


def _invalidate(report, error):
    for row in report["records"]:
        row.update(
            status="invalidated_input_drift",
            error_code="INPUT_DRIFT",
            detail=str(error),
            artifacts={},
        )
    report["summary"].update(
        statuses={"invalidated_input_drift": len(report["records"])},
        all_requested_verified=False,
        artifact_pages=0,
        invalidated=len(report["records"]),
    )
    report["artifacts"] = {}
    report["integrity"] = {"all_inputs_unchanged": False, "detail": str(error)}


def _encode(report):
    return mask._encode(report)


def publish_pages(output, pages, report, audit):
    """Publish an all-cohort batch; drift removes only pages this call created."""
    output = Path(output)
    if output.exists():
        raise ValueError("Refusing to overwrite an existing workbench output directory.")
    if not isinstance(pages, dict) or any(
        not isinstance(name, str)
        or re.fullmatch(r"(?:index\.html|cases/[a-z0-9-]+\.html)", name) is None
        or not isinstance(data, bytes)
        or len(data) > PAGE_LIMIT
        for name, data in pages.items()
    ):
        raise ValueError("Page paths and bytes must stay within the fixed self-contained layout.")
    if sum(map(len, pages.values())) > TOTAL_PAGE_LIMIT:
        raise ValueError("The complete page batch exceeds its 192-MiB budget.")
    if pages:
        expected = {"cases/" + row["sample_id"] + ".html" for row in report["records"]}
        if (
            len(report["records"]) != 12
            or len(expected) != 12
            or set(pages) != expected | {"index.html"}
            or any(row["status"] != "ok" for row in report["records"])
            or report["summary"]["all_requested_verified"] is not True
        ):
            raise ValueError(
                "Publication requires the index and all twelve bound successful cases."
            )
    elif report["summary"]["all_requested_verified"] is not False:
        raise ValueError("An empty page batch cannot claim successful cohort publication.")
    created, initial_error = [], None
    try:
        audit()
    except (OSError, ValueError) as error:
        initial_error = error
    output.mkdir(parents=True, exist_ok=False)
    destination = output / "report.json"
    report_created = False

    def clean_pages():
        for path in reversed(created):
            path.unlink(missing_ok=True)
        cases = output / "cases"
        if cases.is_dir() and not any(cases.iterdir()):
            cases.rmdir()

    try:
        if initial_error is not None:
            raise initial_error
        for name, data in pages.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                created.append(path)
                stream.write(data)
        audit()
        report["integrity"] = {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
            "verified_input_count": len(report.get("inputs", [])),
        }
        with destination.open("xb") as stream:
            report_created = True
            stream.write(_encode(report))
        audit()
    except (OSError, ValueError) as error:
        clean_pages()
        _invalidate(report, error)
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
        raise ValueError("Study plan exceeds the metadata byte budget.")
    plan, runtime = uv._json(plan_bytes), uv.runtime_fingerprint()
    if (
        plan.get("schema_version") != 1
        or plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("runtime") != runtime
        or set(plan["roles"]) != set(ROLES)
    ):
        raise ValueError("Plan protocol, roles or exact runtime fingerprint differs.")
    inputs, roles = uv.Inputs(root, plan["inputs"]), plan["roles"]
    metadata = {name: uv._json(inputs.read(roles[name], uv.META_LIMIT)) for name in ROLES}
    _protocol(metadata["protocol"])
    inherited = derive_input_pins(metadata)
    for pin in inherited:
        if inputs.pins.get(pin["path"]) != pin:
            raise ValueError("Freeze omits or changes an inherited mask/audit input.")
    required = {pin["path"] for pin in inherited} | {pin["path"] for pin in roles.values()}
    required |= set(SOURCES)
    if not required <= inputs.pins.keys():
        raise ValueError("Freeze omits required evidence, app, template, builder or test sources.")
    if any(
        Path(name).suffix.lower()
        not in {".py", ".json", ".md", ".toml", ".lock", ".js", ".mjs", ".ts", ".html"}
        for name in inputs.pins.keys() - required
    ):
        raise ValueError("Arbitrary new binary inputs outside the inherited cohort are forbidden.")
    for name, digest in _LOADED_SOURCE_HASHES.items():
        if inputs.pins[name]["sha256"] != digest:
            raise ValueError("Loaded Python implementation differs from the frozen source bytes.")
    selected, old_records = validate_evidence(inputs, roles, metadata)
    # Snapshot the entire declared closure before decoding any PNG or NPZ payload.
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
    template = inputs.read(inputs.pins["frontend/research/mask-review.html"], uv.META_LIMIT).decode(
        "utf-8"
    )
    script = inputs.read(inputs.pins["frontend/research/mask-review.mjs"], uv.META_LIMIT).decode(
        "utf-8"
    )
    plan_pin = {
        "path": plan_path.relative_to(root).as_posix(),
        "bytes": len(plan_bytes),
        "sha256": uv._digest(plan_bytes),
    }
    provenance = {
        "studyPlan": plan_pin,
        **roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
    }
    navigation = [
        {
            "sampleId": item["registration"]["sample_id"],
            "href": item["registration"]["sample_id"] + ".html",
        }
        for item in selected
    ]
    pages, records = {}, []
    for item in selected:
        row = item["registration"]
        record = {
            "sample_id": row["sample_id"],
            "source_id": row["source_id"],
            "target_age_condition": row["target_age"],
            "source_age_label": row["source_age_label"],
            "source_age": dict(uv.UNKNOWN_AGE),
            "status": "failed",
            "artifacts": {},
        }
        try:
            if snapshot_error is not None:
                raise ValueError(
                    "Verified full-cohort input snapshot unavailable: " + str(snapshot_error)
                )
            payload = _case_payload(
                inputs,
                item,
                old_records[row["sample_id"]],
                primary_rows[row["sample_id"]],
                provenance,
                navigation,
            )
            document = render_case_document(payload, template, script)
            name = "cases/" + row["sample_id"] + ".html"
            if sum(map(len, pages.values())) + len(document) > TOTAL_PAGE_LIMIT:
                raise ValueError("Prepared page batch exceeds its total byte budget.")
            pages[name] = document
            record.update(
                status="ok",
                artifacts={
                    "page": {
                        "path": (output / name).relative_to(root).as_posix(),
                        "bytes": len(document),
                        "sha256": uv._digest(document),
                    }
                },
            )
        except (OSError, ValueError, KeyError, TypeError, IndexError, cv2.error) as error:
            record.update(
                error_code="WORKBENCH_PREPARATION_FAILED",
                error_type=type(error).__name__,
                detail=str(error),
            )
        records.append(record)
        print(f"Workbench {len(records)}/12: {row['sample_id']} {record['status']}", flush=True)
    all_prepared = len(records) == 12 and all(row["status"] == "ok" for row in records)
    if all_prepared:
        pages["index.html"] = render_index(records)
        if sum(map(len, pages.values())) > TOTAL_PAGE_LIMIT:
            all_prepared = False
            for row in records:
                row.update(
                    status="failed",
                    error_code="PAGE_BATCH_BUDGET_EXCEEDED",
                    detail="Case pages plus index exceed the frozen total page byte budget.",
                )
    if not all_prepared:
        pages.clear()
        for row in records:
            row["artifacts"] = {}
            if row["status"] == "ok":
                row.update(
                    status="prepared_publication_blocked", error_code="COHORT_PREPARATION_FAILED"
                )
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **metadata["protocol"]["flags"],
        "study_plan": plan_pin,
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "records": records,
        "artifacts": {},
        "summary": {
            "requested_targets": 12,
            "requested_sources": 3,
            "statuses": dict(Counter(row["status"] for row in records)),
            "all_requested_verified": all_prepared,
            "artifact_pages": len(pages),
        },
        "interpretation": "Read-only engineering export only; human review remains incomplete. "
        "No mask, anatomical occlusion, identity, age, visual or production acceptance.",
    }
    if all_prepared:
        index = pages["index.html"]
        report["artifacts"]["index"] = {
            "path": (output / "index.html").relative_to(root).as_posix(),
            "bytes": len(index),
            "sha256": uv._digest(index),
        }

    def audit():
        inputs.recheck()
        with plan_path.open("rb") as stream:
            current = stream.read(uv.META_LIMIT + 1)
        if current != plan_bytes or uv.runtime_fingerprint() != runtime:
            raise ValueError("Study plan, frozen sources/inputs or exact runtime drifted.")

    return publish_pages(output, pages, report, audit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args)
        print(_encode(report["summary"]).decode("utf-8").strip())
        return 0 if report["summary"]["all_requested_verified"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
