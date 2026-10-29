"""Read-only P04 declaration precheck; never assigns splits or accepts real identities.

python -m preprocessing.split_freeze --help
Only bounded metadata is read; image pins remain historical P03 observations.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import combinations, product
from pathlib import Path

from . import archive_preparation as preparation
from . import dataset_manifest as metadata
from . import duplicate_screening as screening
from . import resource_acquisition as acquisition

SCHEMA = "agemorph3d-split-freeze-precheck-v1"
BASIS_SCHEMA = "agemorph3d-split-basis-v1"
FROZEN_SCHEMA = "agemorph3d-split-frozen-inputs-v1"
MAX_JSON = 4 * 1024**2
MAX_PLAN = 512 * 1024
MAX_INPUTS = 64
MAX_TOTAL_METADATA = 32 * 1024**2
VIEWS = ("original", "mirror")
ORIGINS = {"official", "human", "synthetic", "ai", "unknown"}
DECISIONS = {"pending", "uncertain", "same_content", "different_content"}
Error, require, safe = preparation.Error, preparation.require, preparation.safe
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = {
    name: hashlib.sha256((_SOURCE_ROOT / name).read_bytes()).hexdigest()
    for name in (
        "preprocessing/split_freeze.py",
        "preprocessing/duplicate_screening.py",
        "preprocessing/dataset_manifest.py",
    )
}
PRODUCER_SHA256 = _SOURCES["preprocessing/split_freeze.py"]
FLAGS = {
    **acquisition.FLAGS,
    "split_assignment_performed": False,
    "human_review_verified": False,
    "cross_source_identity_proven": False,
    "candidate_review_complete": False,
    "freeze_authorized": False,
    "images_or_models_read": False,
    "image_pins_rechecked": False,
}


def _same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


class _Inputs:
    def __init__(self, root):
        self.root, self.pins, self.bodies, self.total = root, {}, {}, 0

    def read(self, pin, *, suffixes=(".json",), maximum=MAX_JSON):
        preparation._pin(pin, maximum)
        name = pin["path"]
        require(Path(name).suffix.lower() in suffixes, "METADATA_SUFFIX_REQUIRED")
        if name in self.pins:
            require(self.pins[name] == pin, "CONFLICTING_INPUT_PIN")
            return self.bodies[name]
        require(len(self.pins) < MAX_INPUTS, "METADATA_INPUT_COUNT_LIMIT")
        require(self.total + pin["bytes"] <= MAX_TOTAL_METADATA, "METADATA_TOTAL_BYTE_LIMIT")
        body = acquisition._read(safe(self.root, name), maximum)
        require(
            len(body) == pin["bytes"] and hashlib.sha256(body).hexdigest() == pin["sha256"],
            "INPUT_PIN_MISMATCH",
        )
        self.pins[name], self.bodies[name] = copy.deepcopy(pin), body
        self.total += len(body)
        return body

    def load(self, pin):
        return acquisition._json(self.read(pin))

    def changed(self):
        result = []
        for pin in self.pins.values():
            try:
                preparation._verify(self.root, pin, MAX_JSON)
            except (Error, OSError):
                result.append(pin["path"])
        return result


def _screening(value, manifest, manifest_pin, inputs):
    require(
        type(value) is dict
        and value.get("schema_id") == screening.SCHEMA
        and value.get("producer_sha256") == screening.PRODUCER_SHA256
        and value.get("research_only") is True
        and type(value.get("inputs_stable")) is bool
        and type(value.get("status")) is str
        and value["status"] in {"passed", "failed"}
        and all(value.get(k) is False for k in screening.acquisition.FLAGS)
        and all(
            value.get(k) is False
            for k in (
                "candidate_review_complete",
                "split_assignment_performed",
                "model_inference_run",
                "cross_source_identity_proven",
                "no_leakage_accepted",
                "images_or_thumbnails_written",
                "original_binary_integrity_rechecked",
            )
        )
        and _same(value.get("fingerprint_contract"), screening.fingerprint_contract()),
        "SCREENING_VERSION_OR_BOUNDARY_MISMATCH",
    )
    pins = value.get("inputs")
    require(
        type(pins) is list and len(pins) == 6 and sum(p == manifest_pin for p in pins) == 1,
        "SCREENING_MANIFEST_PIN_MISMATCH",
    )
    for pin in pins:
        inputs.read(pin, suffixes=(".json", ".py"))
    source_plan = acquisition._json(inputs.read(pins[0], maximum=screening.MAX_PLAN))
    acquisition._keys(
        source_plan,
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
        source_plan["schema_id"] == screening.SCHEMA
        and acquisition._identifier(source_plan["plan_id"])
        and source_plan["plan_id"] == value.get("plan_id")
        and source_plan["preparation_report"] == pins[1]
        and source_plan["prepared_manifest"] == pins[2] == manifest_pin
        and _same(source_plan["fingerprint_contract"], value["fingerprint_contract"])
        and source_plan["algorithm_sources"] == pins[4:],
        "SCREENING_INPUT_ROLE_MISMATCH",
    )
    require(
        {p["path"] for p in pins[4:]} == set(screening.ALGORITHM_SOURCES)
        and all(p["sha256"] == screening._RUNNING_SOURCES[p["path"]] for p in pins[4:]),
        "SCREENING_ALGORITHM_SOURCE_MISMATCH",
    )
    preparation_report, prepared, original_pin = screening._inputs(inputs.root, source_plan)
    require(prepared == manifest and original_pin == pins[3], "SCREENING_LINEAGE_MISMATCH")
    require(preparation_report["inputs_stable"] is True, "PREPARATION_UNSTABLE")
    rows = value.get("records")
    require(
        type(rows) is list
        and len(rows) == len(manifest["records"])
        and all(type(r) is dict for r in rows)
        and [r.get("k5") for r in rows] == manifest["records"],
        "SCREENING_K5_LEDGER_MISMATCH",
    )
    features = {}
    for i, row in enumerate(rows):
        require(
            type(row.get("index")) is int
            and row["index"] == i
            and row.get("sample_id") == row["k5"]["sample_id"],
            "SCREENING_INDEX_MISMATCH",
        )
        require(
            type(row.get("status")) is str and row["status"] in {"fingerprinted", "failed"},
            "SCREENING_ROW_STATUS_INVALID",
        )
        if row["status"] == "failed":
            require(
                type(row.get("error_code")) is str and bool(row["error_code"]),
                "SCREENING_FAILURE_CODE_MISSING",
            )
            continue
        require(
            row.get("initial_pin_verified") is True
            and row.get("final_pin_verified") is True
            and row.get("error_code") is None,
            "SCREENING_SUCCESS_NOT_VERIFIED",
        )
        preparation._pin(row.get("normalized"), screening.retrieval.MAX_IMAGE_BYTES)
        require(row["normalized"]["path"].endswith(".png"), "SCREENING_IMAGE_PIN_INVALID")
        acquisition._keys(row.get("views"), VIEWS)
        views = {}
        for name in VIEWS:
            view = row["views"][name]
            acquisition._keys(view, ("horizontal_dhash", "vertical_dhash", "pixel_sha256"))
            require(acquisition._sha(view["pixel_sha256"]), "SCREENING_PIXEL_HASH_INVALID")
            for field in ("horizontal_dhash", "vertical_dhash"):
                require(
                    type(view[field]) is str
                    and len(view[field]) == 16
                    and all(c in "0123456789abcdef" for c in view[field]),
                    "SCREENING_DHASH_INVALID",
                )
            views[name] = {
                "horizontal": int(view["horizontal_dhash"], 16),
                "vertical": int(view["vertical_dhash"], 16),
                "pixel_sha256": view["pixel_sha256"],
            }
        features[i] = {"views": views}
    ledger, candidates = value.get("pair_ledger"), value.get("candidates")
    pairs = list(combinations(range(len(rows)), 2))
    require(
        type(ledger) is list and len(ledger) == len(pairs) and type(candidates) is list,
        "SCREENING_PAIR_LEDGER_MISMATCH",
    )
    ids = {}
    for candidate in candidates:
        require(
            type(candidate) is dict
            and acquisition._integer(candidate.get("candidate_id"), 0, len(pairs) - 1),
            "SCREENING_CANDIDATE_ID_INVALID",
        )
        cid = candidate["candidate_id"]
        require(cid not in ids, "SCREENING_CANDIDATE_ID_DUPLICATE")
        ids[cid] = candidate
    used = []
    for pair, (left, right) in zip(ledger, pairs, strict=True):
        acquisition._keys(pair, ("left_index", "right_index", "candidate_id", "status"))
        require(
            _same([pair["left_index"], pair["right_index"]], [left, right]),
            "SCREENING_PAIR_ORDER_MISMATCH",
        )
        comparable = left in features and right in features
        require(
            pair["status"] == ("comparable" if comparable else "uncomparable"),
            "SCREENING_PAIR_STATUS_MISMATCH",
        )
        if not comparable:
            require(pair["candidate_id"] is None, "FAILED_IMAGE_HAS_CANDIDATE")
            continue
        hits, pixels = [], []
        for a, b in product(VIEWS, repeat=2):
            x, y = features[left]["views"][a], features[right]["views"][b]
            names = {"left_view": a, "right_view": b}
            if x["pixel_sha256"] == y["pixel_sha256"]:
                pixels.append(names)
            h, v = (
                (x["horizontal"] ^ y["horizontal"]).bit_count(),
                (x["vertical"] ^ y["vertical"]).bit_count(),
            )
            if h <= 8 and v <= 8:
                hits.append({**names, "horizontal_hamming": h, "vertical_hamming": v})
        same_file = rows[left]["normalized"]["sha256"] == rows[right]["normalized"]["sha256"]
        if not (hits or pixels or same_file):
            require(pair["candidate_id"] is None, "SCREENING_UNSUPPORTED_CANDIDATE")
            continue
        cid = pair["candidate_id"]
        require(type(cid) is int and cid in ids, "SCREENING_CANDIDATE_OMITTED")
        candidate = ids[cid]
        require(
            _same([candidate.get("left_index"), candidate.get("right_index")], [left, right])
            and candidate.get("sample_ids") == [rows[left]["sample_id"], rows[right]["sample_id"]],
            "SCREENING_CANDIDATE_PAIR_MISMATCH",
        )
        require(
            _same(candidate.get("same_normalized_file_sha256"), same_file)
            and candidate.get("equal_rgb_pixel_view_pairs") == pixels,
            "SCREENING_EXACT_EVIDENCE_MISMATCH",
        )
        matched = candidate.get("matched_view_pairs")
        require(type(matched) is list and len(matched) == len(hits), "SCREENING_MATCHES_OMITTED")
        for hit, expected in zip(matched, hits, strict=True):
            acquisition._keys(hit, (*expected, "gray32_mae"))
            require(
                _same({k: hit[k] for k in expected}, expected), "SCREENING_HASH_DISTANCE_MISMATCH"
            )
            require(
                type(hit["gray32_mae"]) in (int, float)
                and math.isfinite(hit["gray32_mae"])
                and 0 <= hit["gray32_mae"] <= 1,
                "SCREENING_DIAGNOSTIC_INVALID",
            )
        used.append(cid)
    require(
        used == [c["candidate_id"] for c in candidates],
        "SCREENING_CANDIDATE_ORDER_OR_COVERAGE_MISMATCH",
    )
    require(
        _same(value.get("exact_groups"), screening._exact_groups(rows, features))
        and _same(value.get("components"), screening.retrieval._components(candidates)),
        "SCREENING_GROUP_EVIDENCE_MISMATCH",
    )
    summary = value.get("summary")
    require(
        type(summary) is dict
        and acquisition._integer(
            summary.get("images_before_final_check"), len(features), len(rows)
        ),
        "SCREENING_SUMMARY_INVALID",
    )
    expected = {
        "requested_images": len(rows),
        "fingerprinted_images": len(features),
        "failed_images": len(rows) - len(features),
        "images_before_final_check": summary["images_before_final_check"],
        "requested_pairs": len(pairs),
        "comparable_pairs": len(features) * (len(features) - 1) // 2,
        "candidate_pairs": len(candidates),
        "cross_use_candidate_pairs": sum(
            screening._use_summary([c["left_index"], c["right_index"]], rows)["cross_assigned_uses"]
            for c in candidates
        ),
    }
    expected["uncomparable_pairs"] = len(pairs) - expected["comparable_pairs"]
    require(_same(summary, expected), "SCREENING_SUMMARY_MISMATCH")
    require(
        (value["status"] == "passed") == (value["inputs_stable"] and len(features) == len(rows)),
        "SCREENING_STATUS_CONFLICT",
    )
    return rows, candidates, features


def _basis(value, assignments, candidates, inputs):
    acquisition._keys(value, ("schema_id", "basis_id", "groups", "candidate_reviews"))
    require(
        value["schema_id"] == BASIS_SCHEMA and metadata._identifier(value["basis_id"]),
        "INVALID_BASIS_SCHEMA",
    )
    groups, reviews = value["groups"], value["candidate_reviews"]
    require(type(groups) is list and 1 <= len(groups) <= len(assignments), "INVALID_BASIS_GROUPS")
    membership = {}
    group_ids = set()
    for item in groups:
        acquisition._keys(item, ("group_id", "sample_ids", "origin", "recorded_by", "evidence"))
        require(
            metadata._identifier(item["group_id"]) and item["group_id"] not in group_ids,
            "DUPLICATE_OR_INVALID_GROUP_ID",
        )
        group_ids.add(item["group_id"])
        require(
            type(item["sample_ids"]) is list and 1 <= len(item["sample_ids"]) <= len(assignments),
            "INVALID_GROUP_MEMBERS",
        )
        for sid in item["sample_ids"]:
            require(
                metadata._identifier(sid) and sid not in membership, "DUPLICATE_GROUP_MEMBERSHIP"
            )
            membership[sid] = item["group_id"]
    require(
        membership == {a["sample_id"]: a["group_id"] for a in assignments},
        "GROUP_COVERAGE_OR_ASSIGNMENT_MISMATCH",
    )
    require(
        type(reviews) is list and len(reviews) == len(candidates),
        "CANDIDATE_REVIEW_LEDGER_MISMATCH",
    )
    for review, candidate in zip(reviews, candidates, strict=True):
        acquisition._keys(
            review, ("candidate_id", "sample_ids", "decision", "origin", "recorded_by", "evidence")
        )
        require(
            type(review["candidate_id"]) is int
            and review["candidate_id"] == candidate["candidate_id"]
            and review["sample_ids"] == candidate["sample_ids"],
            "CANDIDATE_REVIEW_BINDING_MISMATCH",
        )
        require(
            type(review["decision"]) is str and review["decision"] in DECISIONS,
            "INVALID_REVIEW_DECISION",
        )
    for item in [*groups, *reviews]:
        require(
            type(item["origin"]) is str and item["origin"] in ORIGINS, "INVALID_DECLARATION_ORIGIN"
        )
        require(
            item["recorded_by"] is None or metadata._identifier(item["recorded_by"]),
            "INVALID_RECORDER",
        )
        if item["evidence"] is not None:
            inputs.read(item["evidence"], suffixes=(".json", ".md"))
    return groups, reviews


def _constraints(manifest, source, assignments, groups, reviews, candidates):
    findings = []
    by_id = {a["sample_id"]: a for a in assignments}
    rows = manifest["records"]

    def add(code, sample_ids=(), **extra):
        findings.append({"code": code, "sample_ids": list(sample_ids), **extra})

    if source["status"] != "passed":
        add("SCREENING_INCOMPLETE_OR_UNSTABLE")
    for row, assignment in zip(rows, assignments, strict=True):
        sid = row["sample_id"]
        if assignment["use"] != row["use"]:
            add("PROPOSED_USE_DIFFERS_FROM_INPUT", [sid])
        if assignment["use"] == "unassigned":
            add("UNASSIGNED_USE", [sid])
    for group in groups:
        uses = {by_id[sid]["use"] for sid in group["sample_ids"]} - {"unassigned"}
        if len(uses) > 1:
            add("GROUP_CROSSES_USES", group["sample_ids"], group_id=group["group_id"])
        if (
            group["origin"] not in {"official", "human", "synthetic"}
            or group["recorded_by"] is None
            or group["evidence"] is None
        ):
            add("GROUP_BASIS_UNRESOLVED", group["sample_ids"], group_id=group["group_id"])
    identities = defaultdict(list)
    for row in rows:
        sid = row["sample_id"]
        if row["subject_id"] is not None:
            identities[("local", row["dataset_id"], row["subject_id"])].append(sid)
        if row["linked_subject_id"] is not None:
            identities[("linked", row["linked_subject_id"])].append(sid)
        if (
            row["parent_id"] is not None
            and by_id[sid]["group_id"] != by_id[row["parent_id"]]["group_id"]
        ):
            add("LINEAGE_SPLIT", [row["parent_id"], sid])
    for key, members in identities.items():
        if len({by_id[sid]["group_id"] for sid in members}) > 1:
            add(
                "DECLARED_IDENTITY_SPLIT" if key[0] == "local" else "LINKED_IDENTITY_SPLIT", members
            )
    for finding in metadata.audit_manifest(manifest)["findings"]:
        if finding["code"] in {
            "DECLARED_DUPLICATE_CONTENT_CROSSES_USES",
            "DECLARED_HASH_SIZE_CONFLICT",
            "DECLARED_PATH_CONTENT_CONFLICT",
            "IDENTITY_OR_LINEAGE_CROSSES_USES",
        }:
            add(finding["code"], finding["sample_ids"])
    for group in source["exact_groups"]:
        if group["kind"] == "normalized_file_sha256":
            members = [rows[i]["sample_id"] for i in group["image_indices"]]
            if len({by_id[sid]["use"] for sid in members} - {"unassigned"}) > 1:
                add("EXACT_FILE_CROSSES_USES", members)
    for review, candidate in zip(reviews, candidates, strict=True):
        members = review["sample_ids"]
        extra = {"candidate_id": review["candidate_id"]}
        if review["decision"] in {"pending", "uncertain"}:
            add("CANDIDATE_REVIEW_UNRESOLVED", members, **extra)
        elif (
            review["origin"] not in {"official", "human", "synthetic"}
            or review["recorded_by"] is None
            or review["evidence"] is None
        ):
            add("CANDIDATE_REVIEW_PROVENANCE_UNRESOLVED", members, **extra)
        elif (
            review["decision"] == "same_content"
            and len({by_id[sid]["group_id"] for sid in members}) > 1
        ):
            add("REVIEWED_DUPLICATE_SPLIT", members, **extra)
        if review["decision"] == "different_content" and candidate["same_normalized_file_sha256"]:
            add("EXACT_FILE_REVIEW_CONFLICT", members, **extra)
    return findings


def precheck(root, plan_name, plan_sha256, output):
    root = Path(root).absolute()
    require(
        root.is_dir() and root == root.resolve() and acquisition._sha(plan_sha256),
        "INVALID_ROOT_OR_PLAN_PIN",
    )
    body = acquisition._read(safe(root, plan_name), MAX_PLAN)
    require(hashlib.sha256(body).hexdigest() == plan_sha256, "PLAN_SHA256_MISMATCH")
    inputs = _Inputs(root)
    inputs.read({"path": plan_name, "bytes": len(body), "sha256": plan_sha256}, maximum=MAX_PLAN)
    plan = acquisition._json(body)
    acquisition._keys(
        plan,
        (
            "schema_id",
            "plan_id",
            "prepared_manifest",
            "screening_report",
            "basis",
            "assignments",
            "reserve_bytes",
        ),
    )
    require(
        plan["schema_id"] == SCHEMA and acquisition._identifier(plan["plan_id"]), "INVALID_PLAN"
    )
    require(acquisition._integer(plan["reserve_bytes"], 0, 64 * 1024**3), "INVALID_RESERVE")
    manifest = metadata.validate_manifest(inputs.load(plan["prepared_manifest"]))
    require(len(manifest["records"]) <= preparation.MAX_IMAGES, "RECORD_COUNT_LIMIT")
    source = inputs.load(plan["screening_report"])
    source_rows, candidates, _ = _screening(source, manifest, plan["prepared_manifest"], inputs)
    assignments = plan["assignments"]
    require(
        type(assignments) is list and len(assignments) == len(manifest["records"]),
        "ASSIGNMENT_LEDGER_MISMATCH",
    )
    for item, row in zip(assignments, manifest["records"], strict=True):
        acquisition._keys(item, ("sample_id", "group_id", "use"))
        require(
            item["sample_id"] == row["sample_id"] and metadata._identifier(item["group_id"]),
            "ASSIGNMENT_ORDER_OR_GROUP_INVALID",
        )
        require(type(item["use"]) is str and item["use"] in metadata.USES, "INVALID_PROPOSED_USE")
    basis = inputs.load(plan["basis"])
    groups, reviews = _basis(basis, assignments, candidates, inputs)
    findings = _constraints(manifest, source, assignments, groups, reviews, candidates)
    changed = inputs.changed()
    for name, digest in _SOURCES.items():
        try:
            require(
                hashlib.sha256((_SOURCE_ROOT / name).read_bytes()).hexdigest() == digest,
                "SOURCE_CHANGED",
            )
        except (Error, OSError):
            changed.append(name)
    if changed:
        findings.append(
            {
                "code": "INPUT_CHANGED_AT_FINAL_CHECK",
                "sample_ids": [],
                "paths": sorted(set(changed)),
            }
        )
    target = safe(root, output)
    require(output.startswith("output/research/") and not target.exists(), "OUTPUT_MUST_BE_NEW")
    require(
        shutil.disk_usage(root).free >= plan["reserve_bytes"] + 2 * MAX_JSON, "INSUFFICIENT_SPACE"
    )
    report = {
        "schema_id": SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan_sha256,
        "producer_sha256": PRODUCER_SHA256,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "dependency_sha256": _SOURCES,
        "inputs": list(inputs.pins.values()),
        "inputs_stable": not changed,
        "status": "blocked" if findings else "consistent",
        "research_only": True,
        "provenance_assessment": "self_reported_declarations_only",
        "records": [
            {
                "k5": copy.deepcopy(row),
                "assignment": copy.deepcopy(item),
                "screening_status": src["status"],
                "screening_error_code": src["error_code"],
            }
            for row, item, src in zip(manifest["records"], assignments, source_rows, strict=True)
        ],
        "basis": basis,
        "findings": findings,
        "metadata_audit": metadata.audit_manifest(manifest),
        "summary": {
            "records": len(assignments),
            "groups": len(groups),
            "candidate_reviews": len(reviews),
            "findings": len(findings),
            "declared_uses": dict(Counter(a["use"] for a in assignments)),
            "formal_split_records": {
                use: sum(a["use"] == use for a in assignments) for use in metadata.FORMAL_USES
            },
        },
        "frozen_inputs": None,
        **FLAGS,
    }
    frozen = {
        "schema_id": FROZEN_SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan_sha256,
        "input_pins": report["inputs"],
        "producer_sha256": PRODUCER_SHA256,
        "manifest": manifest,
        "assignments": assignments,
        "basis": basis,
        "assignment_method": "explicit_declarations_only",
        "random_seed": None,
        "provenance_assessment": "self_reported_declarations_only",
        "research_only": True,
        **FLAGS,
    }
    frozen_body = acquisition._encoded(frozen) if not findings else None
    require(frozen_body is None or len(frozen_body) <= MAX_JSON, "FROZEN_PACKET_TOO_LARGE")
    if frozen_body is not None:
        report["frozen_inputs"] = {
            "path": output + "/frozen-inputs.json",
            "bytes": len(frozen_body),
            "sha256": hashlib.sha256(frozen_body).hexdigest(),
        }
    report_body = acquisition._encoded(report)
    require(len(report_body) <= MAX_JSON, "REPORT_TOO_LARGE")
    target.mkdir(parents=True, exist_ok=False)
    if frozen_body is not None:
        with safe(root, output + "/frozen-inputs.json").open("xb") as stream:
            stream.write(frozen_body)
    with safe(root, output + "/report.json").open("xb") as stream:
        stream.write(report_body)
    return {**report, "receipt": output + "/report.json"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = precheck(args.root, args.plan, args.plan_sha256, args.output_dir)
    except (Error, OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **FLAGS}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "consistent" else 1


if __name__ == "__main__":
    sys.exit(main())
