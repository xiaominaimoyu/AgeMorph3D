"""Bounded K5 preparation screening; candidates are neither identities nor accepted splits.

python -m preprocessing.duplicate_screening --help
Only pinned, EXIF-normalized preparation PNGs are opened. Originals are not reopened.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import shutil
import sys
import warnings
from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from PIL import Image
from PIL import __version__ as PILLOW_VERSION
from PIL import features as codecs
from tools import near_duplicate_probe as retrieval

from . import archive_preparation as preparation
from . import dataset_manifest as metadata
from . import resource_acquisition as acquisition

SCHEMA = "agemorph3d-duplicate-screening-v1"
MAX_JSON = 4 * 1024**2
MAX_PLAN = 512 * 1024
ALGORITHM_SOURCES = ("tools/near_duplicate_probe.py", "tools/evaluation_readiness_probe.py")
_RUNNING_SOURCES = {
    name: hashlib.sha256((Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest()
    for name in ALGORITHM_SOURCES
}
PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
Error, require, safe = preparation.Error, preparation.require, preparation.safe


def fingerprint_contract():
    """The existing retrieval algorithm, with a distinct K5 input/output protocol."""
    return copy.deepcopy(
        {
            "protocol_id": retrieval.PROTOCOL,
            "algorithm": retrieval.ALGORITHM,
            "limits": retrieval.LIMITS,
            "environment": retrieval.ENVIRONMENT,
        }
    )


def _load(root, pin):
    preparation._pin(pin, MAX_JSON)
    body = acquisition._read(safe(root, pin["path"]), MAX_JSON)
    require(
        len(body) == pin["bytes"] and hashlib.sha256(body).hexdigest() == pin["sha256"],
        "INPUT_PIN_MISMATCH",
    )
    return acquisition._json(body)


def _inputs(root, plan):
    source = _load(root, plan["preparation_report"])
    require(
        type(source) is dict
        and source.get("schema_id") == preparation.SCHEMA
        and source.get("inputs_stable") is True
        and type(source.get("status")) is str
        and source["status"] in {"passed", "failed"}
        and type(source.get("records")) is list
        and 1 <= len(source["records"]) <= preparation.MAX_IMAGES,
        "PREPARATION_REPORT_INVALID",
    )
    require(type(source.get("inputs")) is dict, "PREPARATION_INPUTS_INVALID")
    original_pin = source["inputs"].get("metadata_manifest")
    original = metadata.validate_manifest(_load(root, original_pin))
    prepared = metadata.validate_manifest(_load(root, plan["prepared_manifest"]))
    original["manifest_id"] = prepared["manifest_id"]
    require(len(original["records"]) == len(source["records"]), "SOURCE_RECORD_COUNT_MISMATCH")
    for row, record in zip(source["records"], original["records"], strict=True):
        require(
            type(row) is dict
            and row.get("sample_id") == record["sample_id"]
            and type(row.get("preprocessing_observed")) is bool
            and type(row.get("status")) is str
            and row["status"] in {"decoded", "failed"},
            "SOURCE_RECORD_ORDER_OR_STATUS_MISMATCH",
        )
        if row["preprocessing_observed"]:
            record["exposure"]["preprocessing"] = "yes"
        if row["status"] == "decoded":
            require(row["preprocessing_observed"], "DECODE_WITHOUT_EXPOSURE")
            preparation._pin(row.get("normalized"), preparation.LIMITS["normalized_bytes"])
            require(
                row["normalized"]["path"].startswith("output/research/")
                and row["normalized"]["path"].endswith(".png"),
                "NORMALIZED_PATH_INVALID",
            )
        else:
            require(
                type(row.get("error_code")) is str and bool(row["error_code"]),
                "SOURCE_FAILURE_CODE_MISSING",
            )
    require(original == prepared, "PREPARED_K5_SEMANTICS_CHANGED")
    return source, prepared, original_pin


def _one(root, index, source, record):
    row = {
        "index": index,
        "sample_id": record["sample_id"],
        "k5": copy.deepcopy(record),
        "status": "failed",
        "error_code": None,
        "preparation_status": source["status"],
        "preparation_error_code": source.get("error_code"),
        "normalized": source.get("normalized") if source["status"] == "decoded" else None,
        "initial_pin_verified": False,
        "final_pin_verified": None,
        "read_attempted": False,
    }
    feature = None
    try:
        require(source["status"] == "decoded", "SOURCE_PREPARATION_FAILED")
        pin = row["normalized"]
        require(pin["bytes"] <= retrieval.MAX_IMAGE_BYTES, "FINGERPRINT_BYTE_LIMIT")
        row["read_attempted"] = True
        raw = acquisition._read(safe(root, pin["path"]), retrieval.MAX_IMAGE_BYTES)
        require(
            len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
            "NORMALIZED_PIN_MISMATCH",
        )
        row["initial_pin_verified"] = True
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                require(
                    image.format == "PNG" and getattr(image, "n_frames", 1) == 1,
                    "NORMALIZED_FORMAT_INVALID",
                )
                require(
                    list(image.size) == source.get("normalized_size")
                    and image.mode == source.get("normalized_mode")
                    and image.mode in {"RGB", "RGBA"},
                    "NORMALIZED_RASTER_MISMATCH",
                )
                require(image.getexif().get(274) is None, "NORMALIZED_EXIF_PRESENT")
                require(image.width * image.height <= retrieval.MAX_PIXELS, "IMAGE_PIXEL_LIMIT")
            feature = retrieval._decode(raw)
        row.update(
            status="fingerprinted",
            width=feature["width"],
            height=feature["height"],
            views={
                name: {
                    "horizontal_dhash": f"{view['horizontal']:016x}",
                    "vertical_dhash": f"{view['vertical']:016x}",
                    "pixel_sha256": view["pixel_sha256"],
                }
                for name, view in feature["views"].items()
            },
        )
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        row["error_code"] = "IMAGE_PIXEL_LIMIT"
    except (Error, OSError, ValueError, SyntaxError) as error:
        row["error_code"] = str(error) if isinstance(error, Error) else "IMAGE_DECODE_FAILED"
    return row, feature


def _use_summary(indices, rows):
    uses = sorted({rows[i]["k5"]["use"] for i in indices})
    return {"uses": uses, "cross_assigned_uses": len(set(uses) - {"unassigned"}) > 1}


def _pairs(rows, features):
    ledger, candidates = [], []
    for left, right in combinations(range(len(rows)), 2):
        pair = {"left_index": left, "right_index": right, "candidate_id": None}
        if left not in features or right not in features:
            ledger.append({**pair, "status": "uncomparable"})
            continue
        hits, pixels = retrieval._matches(features[left], features[right])
        same_file = rows[left]["normalized"]["sha256"] == rows[right]["normalized"]["sha256"]
        if hits or pixels or same_file:
            pair["candidate_id"] = len(candidates)
            a, b = rows[left]["k5"], rows[right]["k5"]
            comparable_subjects = (
                a["dataset_id"] == b["dataset_id"]
                and a["subject_id"] is not None
                and b["subject_id"] is not None
            )
            candidates.append(
                {
                    **pair,
                    "sample_ids": [a["sample_id"], b["sample_id"]],
                    **_use_summary([left, right], rows),
                    "same_normalized_file_sha256": same_file,
                    "equal_rgb_pixel_view_pairs": pixels,
                    "matched_view_pairs": hits,
                    "same_declared_local_subject": (
                        a["subject_id"] == b["subject_id"] if comparable_subjects else None
                    ),
                    "same_declared_linked_subject": (
                        a["linked_subject_id"] == b["linked_subject_id"]
                        if a["linked_subject_id"] is not None and b["linked_subject_id"] is not None
                        else None
                    ),
                    "review_status": "pending",
                }
            )
        ledger.append({**pair, "status": "comparable"})
    return ledger, candidates


def _exact_groups(rows, features):
    files, pixels = defaultdict(list), defaultdict(dict)
    for index, feature in features.items():
        files[rows[index]["normalized"]["sha256"]].append(index)
        for name, view in feature["views"].items():
            pixels[view["pixel_sha256"]].setdefault(index, []).append(name)
    result = []
    for kind, groups in (("normalized_file_sha256", files), ("rgb_pixel_sha256", pixels)):
        for digest, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            indices = sorted(members)
            result.append(
                {
                    "kind": kind,
                    "sha256": digest,
                    "image_indices": indices,
                    **_use_summary(indices, rows),
                    "view_members": (
                        [{"index": i, "views": members[i]} for i in indices]
                        if kind == "rgb_pixel_sha256"
                        else None
                    ),
                }
            )
    return result


def screen(root, plan_name, plan_sha256, output):
    root = Path(root).absolute()
    require(root.is_dir() and root == root.resolve(), "INVALID_ROOT")
    require(acquisition._sha(plan_sha256), "INVALID_PLAN_SHA256")
    body = acquisition._read(safe(root, plan_name), MAX_PLAN)
    require(hashlib.sha256(body).hexdigest() == plan_sha256, "PLAN_SHA256_MISMATCH")
    plan = acquisition._json(body)
    acquisition._keys(
        plan,
        (
            "schema_id",
            "plan_id",
            "preparation_report",
            "prepared_manifest",
            "fingerprint_contract",
            "algorithm_sources",
            "reserve_bytes",
        ),
    )
    require(
        plan["schema_id"] == SCHEMA and acquisition._identifier(plan["plan_id"]), "INVALID_PLAN"
    )
    require(acquisition._integer(plan["reserve_bytes"], 0, 64 * 1024**3), "INVALID_RESERVE")
    require(
        json.dumps(plan["fingerprint_contract"], sort_keys=True)
        == json.dumps(fingerprint_contract(), sort_keys=True),
        "FINGERPRINT_CONTRACT_MISMATCH",
    )
    require(
        {"python_version": sys.version.split()[0], "pillow_version": PILLOW_VERSION}
        == retrieval.ENVIRONMENT,
        "FINGERPRINT_ENVIRONMENT_MISMATCH",
    )
    sources = plan["algorithm_sources"]
    require(
        type(sources) is list
        and len(sources) == len(ALGORITHM_SOURCES)
        and all(type(p) is dict for p in sources)
        and {p.get("path") for p in sources} == set(ALGORITHM_SOURCES),
        "ALGORITHM_SOURCE_SET_MISMATCH",
    )
    for pin in sources:
        preparation._pin(pin, MAX_PLAN)
        preparation._verify(root, pin, MAX_PLAN)
        require(pin["sha256"] == _RUNNING_SOURCES[pin["path"]], "RUNNING_ALGORITHM_MISMATCH")
    source, prepared, original_pin = _inputs(root, plan)
    target = safe(root, output)
    require(output.startswith("output/research/") and not target.exists(), "OUTPUT_MUST_BE_NEW")
    require(
        shutil.disk_usage(root).free >= plan["reserve_bytes"] + MAX_JSON,
        "INSUFFICIENT_SPACE",
    )
    target.mkdir(parents=True, exist_ok=False)
    rows, features = [], {}
    for index, (src, record) in enumerate(zip(source["records"], prepared["records"], strict=True)):
        row, feature = _one(root, index, src, record)
        rows.append(row)
        if feature is not None:
            features[index] = feature
    ledger, candidates = _pairs(rows, features)
    before_final_check = len(features)
    stable, changed = True, set()
    # Check after comparisons; stale edges must not survive a late source change.
    for row in rows:
        if not row["read_attempted"]:
            continue
        try:
            preparation._verify(root, row["normalized"], retrieval.MAX_IMAGE_BYTES)
            row["final_pin_verified"] = True
        except (Error, OSError):
            row["final_pin_verified"] = False
            stable = False
        if row["status"] == "fingerprinted" and not row["final_pin_verified"]:
            row.update(status="failed", error_code="SOURCE_CHANGED_AFTER_COMPARISON")
            features.pop(row["index"])
            changed.add(row["index"])
    if changed:
        # Filter saved results only; no second comparison on changed bytes.
        candidates = [c for c in candidates if not changed & {c["left_index"], c["right_index"]}]
        for pair in ledger:
            if changed & {pair["left_index"], pair["right_index"]}:
                pair.update(status="uncomparable", candidate_id=None)
    input_pins = [
        {"path": plan_name, "bytes": len(body), "sha256": plan_sha256},
        plan["preparation_report"],
        plan["prepared_manifest"],
        original_pin,
        *sources,
    ]
    for pin in input_pins:
        try:
            preparation._verify(root, pin, MAX_JSON)
        except (Error, OSError):
            stable = False
    for name, digest in _RUNNING_SOURCES.items():
        try:
            require(
                hashlib.sha256(
                    (Path(__file__).resolve().parents[1] / name).read_bytes()
                ).hexdigest()
                == digest,
                "RUNNING_SOURCE_CHANGED",
            )
        except (Error, OSError):
            stable = False
    comparable = sum(p["status"] == "comparable" for p in ledger)
    report = {
        "schema_id": SCHEMA,
        "plan_id": plan["plan_id"],
        "producer_sha256": PRODUCER_SHA256,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "inputs": input_pins,
        "inputs_stable": stable,
        "research_only": True,
        "fingerprint_contract": fingerprint_contract(),
        "input_limits": {
            "max_prepared_images": preparation.MAX_IMAGES,
            "max_report_bytes": MAX_JSON,
        },
        "codecs": {name: codecs.version(name) for name in ("jpg", "zlib", "webp")},
        "records": rows,
        "pair_ledger": ledger,
        "candidates": candidates,
        "components": retrieval._components(candidates),
        "exact_groups": _exact_groups(rows, features),
        "metadata_audit": metadata.audit_manifest(prepared),
        "summary": {
            "requested_images": len(rows),
            "fingerprinted_images": len(features),
            "failed_images": len(rows) - len(features),
            "images_before_final_check": before_final_check,
            "requested_pairs": len(ledger),
            "comparable_pairs": comparable,
            "uncomparable_pairs": len(ledger) - comparable,
            "candidate_pairs": len(candidates),
            "cross_use_candidate_pairs": sum(c["cross_assigned_uses"] for c in candidates),
        },
        "feature_input": "Pinned preparation PNG, before P02 cropping/resizing",
        "rgb_pixel_semantics": (
            "RGB ignores alpha; mirror equality is reported by view, not identity"
        ),
        "original_binary_integrity_rechecked": False,
        "images_or_thumbnails_written": False,
        "candidate_review_complete": False,
        "cross_source_identity_proven": False,
        "no_leakage_accepted": False,
        "split_assignment_performed": False,
        "model_inference_run": False,
        **acquisition.FLAGS,
    }
    report["status"] = "passed" if stable and len(features) == len(rows) else "failed"
    preparation._write_json(root, output + "/report.json", report)
    return {**report, "receipt": output + "/report.json"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = screen(args.root, args.plan, args.plan_sha256, args.output_dir)
    except (Error, OSError, ValueError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **acquisition.FLAGS}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
