"""LX-1..LX-3 local script pack: verify, recount and propose identity splits on-device.

Run from the project root: python -m preprocessing.lx_local --help
The CLI refuses to run unless ``--local-only-ack`` is passed. On start it warns
that filename-containing outputs stay on the user's machine only.

Intended only for the user's own machine. The script never accepts or stores an
archive password; encrypted official zips must be extracted with a system tool
(Explorer / 7-Zip) by the user, or the already-extracted folder is reused.
No network, no model inference, no training, no ``trust_remote_code``.

The only shareable output is ``summary.json``, restricted to a field whitelist of
aggregate counts and SHA-256 digests. Every other report is marked ``local_only``.
Stages are idempotent and resumable: a later run reuses completed stages when
input pins still match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from . import agedb_filenames as agedb
from . import archive_preparation as preparation
from . import dataset_manifest as metadata
from . import duplicate_screening as screening
from . import resource_acquisition as acquisition
from . import split_freeze as freeze

SCHEMA = "agemorph3d-lx-summary-v1"
STATE_SCHEMA = "agemorph3d-lx-state-v1"
REPORT_SCHEMA = "agemorph3d-lx-local-v1"
LOCAL_ONLY_WARNING = "含文件名的输出仅限用户本机"
LOCAL_ONLY_ACK_REQUIRED = "LOCAL_ONLY_ACK_REQUIRED"
PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_MEMBER_BYTES = 16 * 1024**2
MAX_TOTAL_UNPACKED = 2 * 1024**3
MAX_MEMBERS = 20_000
MAX_SNAPSHOT_BYTES = 16 * 1024**2
AGE_LOW, AGE_HIGH = agedb.AGE_LOW, agedb.AGE_HIGH
FORMAL_USES = metadata.FORMAL_USES
SPLIT_SEED = "agemorph3d-lx3-identity-split-v1"
Error, require, safe = preparation.Error, preparation.require, preparation.safe

# Shareable summary keys only. No filenames, person names, identity IDs,
# per-image records or feature values.
SUMMARY_WHITELIST = (
    "schema_id",
    "schema_version",
    "status",
    "producer_sha256",
    "python_runtime",
    "recorded_at_utc",
    "stages_completed",
    "inputs_stable",
    "archive_bytes",
    "archive_sha256",
    "archive_mtime_utc",
    "archive_hashed_at_utc",
    "archive_present",
    "extracted_readonly",
    "extracted_file_count",
    "terms_snapshot_bytes",
    "terms_snapshot_sha256",
    "extraction_method",
    "images",
    "identities",
    "images_age_20_70",
    "images_age_exact_70",
    "identities_span_ge_30",
    "identities_span_ge_30_within_20_70",
    "age_min",
    "age_max",
    "images_by_age_decade",
    "images_by_gender",
    "short_side_px",
    "images_without_size",
    "filter_short_ge_128_age_20_70",
    "filter_short_ge_128",
    "k5_records",
    "rejected",
    "rejected_by_reason",
    "image_failures_by_code",
    "k5_manifest_sha256",
    "inventory_sha256",
    "stats_sha256",
    "audit_sha256",
    "rejected_report_sha256",
    "split_train_images",
    "split_train_identities",
    "split_validation_images",
    "split_validation_identities",
    "split_test_images",
    "split_test_identities",
    "split_unassigned_images",
    "exclusions_by_reason",
    "exact_duplicate_groups",
    "exact_duplicate_extra_copies",
    "cross_split_exact_duplicate_groups",
    "assignment_ledger_sha256",
    "screening_report_sha256",
    "frozen_inputs_sha256",
    "split_freeze_status",
    "screening_status",
    "p03_p04_invoked",
    "p03_p04_block_reason",
    "contains_file_names_or_person_names",
    "password_accepted_or_stored",
    "research_only",
    "verified_on_real_data",
    "freeze_authorized",
    "split_assignment_performed",
) + tuple(acquisition.FLAGS)

_COUNT_MAPS = {
    "images_by_age_decade",
    "images_by_gender",
    "rejected_by_reason",
    "image_failures_by_code",
    "exclusions_by_reason",
}
_NESTED_COUNTS = {"filter_short_ge_128_age_20_70", "filter_short_ge_128", "short_side_px"}


def _now():
    return datetime.now(UTC).isoformat()


def _mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _write_json(root, name, value):
    body = acquisition._encoded(value)
    target = safe(root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(body)
    return {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def _replace_json(root, name, value):
    path = safe(root, name)
    if path.exists():
        path.chmod(stat.S_IWUSR | stat.S_IRUSR)
        path.unlink()
    return _write_json(root, name, value)


def _pin_file(root, name, maximum):
    path = safe(root, name)
    count, digest = acquisition._hash_file(path, maximum)
    return {"path": name, "bytes": count, "sha256": digest.hexdigest()}


def _set_readonly(path):
    if path.is_symlink():
        raise Error("LINK_OR_REPARSE_PATH")
    if path.is_dir():
        for child in sorted(path.iterdir()):
            _set_readonly(child)
        os.chmod(path, 0o555)
    elif path.is_file():
        os.chmod(path, 0o444)
    else:
        raise Error("NOT_REGULAR_FILE")


def _is_readonly(path):
    if path.is_file():
        return not (path.stat().st_mode & 0o222)
    if path.is_dir():
        return all(_is_readonly(child) for child in path.iterdir())
    return False


def zip_is_encrypted(path):
    with zipfile.ZipFile(path) as container:
        return any(info.flag_bits & 1 for info in container.infolist())


def _scan_zip(archive, limits):
    inventory, names, total = [], set(), 0
    with zipfile.ZipFile(archive) as container:
        require(not any(info.flag_bits & 1 for info in container.infolist()), "ZIP_ENCRYPTED")
        for info in container.infolist():
            require(len(inventory) < limits["members"], "MEMBER_COUNT_LIMIT")
            name = info.filename
            if info.is_dir() and name.endswith("/"):
                name = name[:-1]
            acquisition._relative(name)
            require(type(info.file_size) is int and info.file_size >= 0, "MEMBER_SIZE_INVALID")
            require(info.file_size <= limits["member_bytes"], "MEMBER_SIZE_LIMIT")
            key = name.casefold()
            require(key not in names, "DUPLICATE_MEMBER_PATH")
            names.add(key)
            if not info.is_dir():
                total += info.file_size
                require(total <= limits["total_bytes"], "TOTAL_UNPACKED_LIMIT")
            inventory.append((info, name, info.is_dir()))
    return inventory


def safe_extract_zip(root, archive_name, output_name, limits=None):
    """Extract a non-encrypted zip member-by-member with zip-slip checks. No extractall."""
    limits = limits or {
        "members": MAX_MEMBERS,
        "member_bytes": MAX_MEMBER_BYTES,
        "total_bytes": MAX_TOTAL_UNPACKED,
    }
    archive = safe(root, archive_name)
    target = safe(root, output_name)
    require(not target.exists(), "OUTPUT_MUST_BE_NEW")
    inventory = _scan_zip(archive, limits)
    require(any(not is_dir for _, _, is_dir in inventory), "ARCHIVE_EMPTY")
    created = target
    while not created.parent.exists():
        created = created.parent
    target.mkdir(parents=True, exist_ok=False)
    written = 0
    try:
        with zipfile.ZipFile(archive) as container:
            for info, name, is_dir in inventory:
                dest = safe(root, output_name + "/" + name)
                if is_dir:
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with container.open(info, pwd=None) as source, dest.open("xb") as out:
                    copied = 0
                    while chunk := source.read(64 * 1024):
                        copied += len(chunk)
                        require(copied <= limits["member_bytes"], "MEMBER_SIZE_LIMIT")
                        out.write(chunk)
                written += 1
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        path = target.parent
        while path != created.parent and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            path = path.parent
        raise
    return written


def project_summary(values):
    """Keep only whitelisted keys. Reject unexpected types; never pass through extras."""
    require(type(values) is dict, "SUMMARY_NOT_OBJECT")
    extra = set(values) - set(SUMMARY_WHITELIST)
    require(not extra, "SUMMARY_EXTRA_FIELDS")
    out = {}
    for key in SUMMARY_WHITELIST:
        if key not in values:
            continue
        value = values[key]
        if key in _COUNT_MAPS:
            require(type(value) is dict, "SUMMARY_FIELD_TYPE")
            require(
                all(type(k) is str and type(v) is int for k, v in value.items()),
                "SUMMARY_FIELD_TYPE",
            )
            out[key] = dict(value)
        elif key in _NESTED_COUNTS:
            require(type(value) is dict, "SUMMARY_FIELD_TYPE")
            out[key] = json.loads(json.dumps(value))
        else:
            out[key] = value
    out.setdefault("schema_id", SCHEMA)
    out.setdefault("schema_version", 1)
    out.setdefault("contains_file_names_or_person_names", False)
    out.setdefault("password_accepted_or_stored", False)
    out.setdefault("research_only", True)
    out.setdefault("verified_on_real_data", False)
    out.setdefault("freeze_authorized", False)
    out.setdefault("split_assignment_performed", False)
    for flag, default in acquisition.FLAGS.items():
        out.setdefault(flag, default)
    return out


def encode_summary(values):
    return acquisition._encoded(project_summary(values))


def _local(output, leaf):
    return output + "/local/" + leaf


def _load_state(root, output):
    path = safe(root, _local(output, "state.json"))
    if not path.exists():
        return {
            "schema_id": STATE_SCHEMA,
            "local_only": True,
            "output_dir": output,
            "stages": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(root, output, state):
    state = {**state, "schema_id": STATE_SCHEMA, "local_only": True, "output_dir": output}
    return _replace_json(root, _local(output, "state.json"), state)


def run_lx1(root, archive_name, images_dir, terms_name, output, state):
    """Pin the official pack, reuse or safely extract it, and set the folder read-only."""
    prior = state.get("stages", {}).get("lx1")
    report = {
        "schema_id": REPORT_SCHEMA,
        "local_only": True,
        "stage": "lx1",
        "archive_present": archive_name is not None,
        "password_accepted_or_stored": False,
        "extraction_method": None,
        "extracted_file_count": 0,
        "extracted_readonly": False,
    }
    if archive_name is not None:
        pin = _pin_file(root, archive_name, MAX_ARCHIVE_BYTES)
        archive = safe(root, archive_name)
        report.update(
            archive_bytes=pin["bytes"],
            archive_sha256=pin["sha256"],
            archive_mtime_utc=_mtime(archive),
            archive_hashed_at_utc=_now(),
            zip_encrypted=zip_is_encrypted(archive),
        )
    if terms_name is not None:
        snap = _pin_file(root, terms_name, MAX_SNAPSHOT_BYTES)
        report.update(terms_snapshot_bytes=snap["bytes"], terms_snapshot_sha256=snap["sha256"])
    images = safe(root, images_dir)
    if images.exists():
        require(images.is_dir(), "IMAGES_DIR_NOT_DIRECTORY")
        require(
            not images.is_symlink()
            and not getattr(images.lstat(), "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT,
            "LINK_OR_REPARSE_PATH",
        )
        files = [p for p in images.rglob("*") if p.is_file() and not p.is_symlink()]
        require(files, "IMAGES_DIR_EMPTY")
        if not _is_readonly(images):
            _set_readonly(images)
        report.update(
            extraction_method="already_extracted",
            extracted_file_count=len(files),
            extracted_readonly=_is_readonly(images),
        )
    elif archive_name is not None and report.get("zip_encrypted"):
        raise Error("SYSTEM_EXTRACTOR_REQUIRED")
    elif archive_name is not None:
        written = safe_extract_zip(root, archive_name, images_dir)
        _set_readonly(images)
        report.update(
            extraction_method="safe_unencrypted_zip",
            extracted_file_count=written,
            extracted_readonly=_is_readonly(images),
        )
    else:
        raise Error("ARCHIVE_OR_IMAGES_REQUIRED")
    if prior and prior.get("input_sha256") == report.get("archive_sha256"):
        # Idempotent: already completed with the same archive pin.
        if prior.get("status") == "passed" and images.exists():
            report["resumed"] = True
    pin = _replace_json(root, _local(output, "lx1-report.json"), report)
    state.setdefault("stages", {})["lx1"] = {
        "status": "passed",
        "input_sha256": report.get("archive_sha256"),
        "report_sha256": pin["sha256"],
        "extraction_method": report["extraction_method"],
    }
    _save_state(root, output, state)
    return report


def run_lx2(root, images_dir, output, state):
    """Call FG-2 library export()/build(); never the password-bearing surface."""
    stats_dir = _local(output, "agedb-stats")
    prior = state.get("stages", {}).get("lx2")
    if prior and prior.get("status") == "passed" and safe(root, stats_dir).exists():
        stats_path = safe(root, stats_dir + "/stats.json")
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        return stats, True
    stats = agedb.export(root, images_dir, stats_dir)
    pins = {
        leaf: hashlib.sha256(safe(root, stats_dir + "/" + leaf).read_bytes()).hexdigest()
        for leaf in ("stats.json", "rejected.json", "manifest.json", "audit.json")
    }
    state.setdefault("stages", {})["lx2"] = {
        "status": "passed",
        "inventory_sha256": stats["inventory_sha256"],
        "output_dir": stats_dir,
        "pins": pins,
    }
    _save_state(root, output, state)
    return stats, False


def assign_identities(records, seed=SPLIT_SEED):
    """Provisional identity-based formal split. All images of one subject stay together.

    Subjects with at least one in-range, header-readable image are assigned by
    ``int(sha256(seed:subject_id)[:8], 16) % 100`` to train (0-69), validation
    (70-84) or test (85-99). This ratio is provisional pending E01/BP-6.
    Out-of-range ages and failed headers stay ``unassigned`` and are counted as
    exclusions. The existing K5 ``use`` field is not rewritten here; the ledger
    is a separate local-only proposal.
    """
    require(type(records) is list and records, "NO_K5_RECORDS")
    exclusions = Counter()
    included = defaultdict(list)
    leftover = []
    for row in records:
        age = row["age"]
        value = age.get("value") if type(age) is dict else None
        failed = row.get("processing", {}).get("status") == "failed"
        outside = type(value) is not int or not (AGE_LOW <= value <= AGE_HIGH)
        if failed:
            exclusions["header_failed"] += 1
            leftover.append(row)
        elif outside:
            exclusions["age_outside_20_70"] += 1
            leftover.append(row)
        else:
            included[row["subject_id"]].append(row)
    assignments = []
    for subject in sorted(included):
        digest = hashlib.sha256(f"{seed}:{subject}".encode()).hexdigest()
        bucket = int(digest[:8], 16) % 100
        use = "train" if bucket < 70 else "validation" if bucket < 85 else "test"
        group_id = "subject-" + hashlib.sha256(subject.encode()).hexdigest()[:16]
        for row in included[subject]:
            assignments.append({"sample_id": row["sample_id"], "group_id": group_id, "use": use})
    for row in leftover:
        assignments.append(
            {"sample_id": row["sample_id"], "group_id": "excluded", "use": "unassigned"}
        )
    by_id = {row["sample_id"]: row for row in records}
    require(len(assignments) == len(records), "ASSIGNMENT_LEDGER_MISMATCH")
    return assignments, dict(exclusions), included, by_id


def _split_counts(assignments, by_id):
    result = {}
    for use in (*FORMAL_USES, "unassigned"):
        rows = [a for a in assignments if a["use"] == use]
        subjects = {by_id[a["sample_id"]]["subject_id"] for a in rows if a["use"] != "unassigned"}
        result[f"split_{use}_images"] = len(rows)
        if use != "unassigned":
            result[f"split_{use}_identities"] = len(subjects)
    return result


def _exact_duplicates(records, assignments):
    by_hash = defaultdict(list)
    for row in records:
        by_hash[row["file"]["sha256"]].append(row["sample_id"])
    groups = [ids for ids in by_hash.values() if len(ids) > 1]
    extra = sum(len(ids) - 1 for ids in groups)
    use_of = {a["sample_id"]: a["use"] for a in assignments}
    cross = 0
    for _digest, ids in by_hash.items():
        uses = {use_of[i] for i in ids if use_of[i] in FORMAL_USES}
        if len(uses) > 1:
            cross += 1
    return len(groups), extra, cross, {d: ids for d, ids in by_hash.items() if len(ids) > 1}


def run_p03_p04(root, output, prep_report, prepared_manifest, assignments, basis):
    """Call duplicate_screening.screen and split_freeze.precheck when plans are ready."""
    require(
        prep_report is not None and prepared_manifest is not None, "PREPARATION_REPORT_REQUIRED"
    )
    screen_plan = {
        "schema_id": screening.SCHEMA,
        "plan_id": "lx3-screen-v1",
        "preparation_report": prep_report,
        "prepared_manifest": prepared_manifest,
        "fingerprint_contract": screening.fingerprint_contract(),
        "algorithm_sources": [],
        "reserve_bytes": 0,
    }
    repo = Path(__file__).resolve().parents[1]
    for name in screening.ALGORITHM_SOURCES:
        target = root / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((repo / name).read_bytes())
        screen_plan["algorithm_sources"].append(_pin_file(root, name, 512 * 1024))
    plan_name = _local(output, "screen-plan.json")
    if safe(root, plan_name).exists():
        safe(root, plan_name).chmod(stat.S_IWUSR | stat.S_IRUSR)
        safe(root, plan_name).unlink()
    _write_json(root, plan_name, screen_plan)
    digest = hashlib.sha256(safe(root, plan_name).read_bytes()).hexdigest()
    screen_out = _local(output, "p03-screen")
    screen_report = screening.screen(root, plan_name, digest, screen_out)
    basis_name = _local(output, "freeze-basis.json")
    if safe(root, basis_name).exists():
        safe(root, basis_name).chmod(stat.S_IWUSR | stat.S_IRUSR)
        safe(root, basis_name).unlink()
    _write_json(root, basis_name, basis)
    freeze_plan = {
        "schema_id": freeze.SCHEMA,
        "plan_id": "lx3-freeze-v1",
        "prepared_manifest": prepared_manifest,
        "screening_report": _pin_file(root, screen_report["receipt"], 4 * 1024**2),
        "basis": _pin_file(root, basis_name, 512 * 1024),
        "assignments": assignments,
        "reserve_bytes": 0,
    }
    freeze_name = _local(output, "freeze-plan.json")
    if safe(root, freeze_name).exists():
        safe(root, freeze_name).chmod(stat.S_IWUSR | stat.S_IRUSR)
        safe(root, freeze_name).unlink()
    _write_json(root, freeze_name, freeze_plan)
    freeze_digest = hashlib.sha256(safe(root, freeze_name).read_bytes()).hexdigest()
    freeze_out = _local(output, "p04-freeze")
    freeze_report = freeze.precheck(root, freeze_name, freeze_digest, freeze_out)
    return screen_report, freeze_report


def run_lx3(
    root, output, state, *, prep_report=None, prepared_manifest=None, split_seed=SPLIT_SEED
):
    """Identity-based split proposal plus exact-hash QC; call P03/P04 when possible."""
    lx2 = state.get("stages", {}).get("lx2")
    require(lx2 and lx2.get("status") == "passed", "LX2_REQUIRED")
    stats_dir = lx2["output_dir"]
    manifest = json.loads(safe(root, stats_dir + "/manifest.json").read_text(encoding="utf-8"))
    metadata.validate_manifest(manifest)
    records = manifest["records"]
    assignments, exclusions, included, by_id = assign_identities(records, seed=split_seed)
    groups, extra, cross, group_map = _exact_duplicates(records, assignments)
    ledger = {
        "schema_id": REPORT_SCHEMA,
        "local_only": True,
        "stage": "lx3",
        "seed": split_seed,
        "assignments": assignments,
        "exclusions_by_reason": exclusions,
        "note": "Proposal only; split_freeze does not authorize a real freeze.",
    }
    ledger_pin = _replace_json(root, _local(output, "assignment-ledger.json"), ledger)
    dup_doc = {
        "schema_id": REPORT_SCHEMA,
        "local_only": True,
        "exact_duplicate_sample_ids": group_map,
    }
    _replace_json(root, _local(output, "exact-duplicates.json"), dup_doc)
    counts = _split_counts(assignments, by_id)
    tool = {
        "schema_id": REPORT_SCHEMA,
        "local_only": True,
        "p03_p04_invoked": False,
        "p03_p04_block_reason": None,
        "screening_status": None,
        "split_freeze_status": None,
        "screening_report_sha256": None,
        "frozen_inputs_sha256": None,
    }
    if prep_report is not None and prepared_manifest is not None:
        if len(records) > preparation.MAX_IMAGES:
            tool["p03_p04_block_reason"] = "P01_P04_RECORD_COUNT_LIMIT"
        else:
            try:
                basis = {
                    "schema_id": freeze.BASIS_SCHEMA,
                    "basis_id": "lx3-basis-v1",
                    "groups": [
                        {
                            "group_id": "subject-"
                            + hashlib.sha256(subject.encode()).hexdigest()[:16],
                            "sample_ids": [row["sample_id"] for row in rows],
                            "origin": "synthetic",
                            "recorded_by": "lx-local-identity-split",
                            "evidence": ledger_pin,
                        }
                        for subject, rows in included.items()
                    ],
                    "candidate_reviews": [],
                }
                screen_report, freeze_report = run_p03_p04(
                    root, output, prep_report, prepared_manifest, assignments, basis
                )
                tool.update(
                    p03_p04_invoked=True,
                    screening_status=screen_report["status"],
                    split_freeze_status=freeze_report["status"],
                    screening_report_sha256=hashlib.sha256(
                        safe(root, screen_report["receipt"]).read_bytes()
                    ).hexdigest(),
                    frozen_inputs_sha256=(
                        freeze_report["frozen_inputs"]["sha256"]
                        if freeze_report.get("frozen_inputs")
                        else None
                    ),
                )
            except (Error, OSError, ValueError, KeyError, TypeError) as error:
                code = str(error) if isinstance(error, Error) else "P03_P04_INPUT_REJECTED"
                # Common on this base: fingerprint_contract pins Python 3.11.16 exactly.
                tool["p03_p04_block_reason"] = code
    else:
        if len(records) > preparation.MAX_IMAGES:
            tool["p03_p04_block_reason"] = "P01_P04_RECORD_COUNT_LIMIT"
        else:
            tool["p03_p04_block_reason"] = "PREPARATION_REPORT_REQUIRED"
    _replace_json(root, _local(output, "lx3-tools.json"), tool)
    summary = {
        **counts,
        "exclusions_by_reason": exclusions,
        "exact_duplicate_groups": groups,
        "exact_duplicate_extra_copies": extra,
        "cross_split_exact_duplicate_groups": cross,
        "assignment_ledger_sha256": ledger_pin["sha256"],
        **{
            k: tool[k]
            for k in (
                "p03_p04_invoked",
                "p03_p04_block_reason",
                "screening_status",
                "split_freeze_status",
                "screening_report_sha256",
                "frozen_inputs_sha256",
            )
        },
    }
    state.setdefault("stages", {})["lx3"] = {
        "status": "passed",
        "assignment_sha256": ledger_pin["sha256"],
    }
    _save_state(root, output, state)
    return summary


def _lx2_aggregates(root, output, stats):
    stats_dir = _local(output, "agedb-stats")
    summary = stats["summary"]
    pins = {
        "stats_sha256": hashlib.sha256(
            safe(root, stats_dir + "/stats.json").read_bytes()
        ).hexdigest(),
        "rejected_report_sha256": hashlib.sha256(
            safe(root, stats_dir + "/rejected.json").read_bytes()
        ).hexdigest(),
        "k5_manifest_sha256": stats["k5_manifest_sha256"],
        "audit_sha256": hashlib.sha256(
            safe(root, stats_dir + "/audit.json").read_bytes()
        ).hexdigest(),
        "inventory_sha256": stats["inventory_sha256"],
    }
    return {
        "images": summary["images"],
        "identities": summary["identities"],
        "images_age_20_70": summary["images_age_20_70"],
        "images_age_exact_70": summary["images_age_exact_70"],
        "identities_span_ge_30": summary["identities_span_ge_30"],
        "identities_span_ge_30_within_20_70": summary["identities_span_ge_30_within_20_70"],
        "age_min": summary["age_min"],
        "age_max": summary["age_max"],
        "images_by_age_decade": summary["images_by_age_decade"],
        "images_by_gender": summary["images_by_gender"],
        "short_side_px": summary["short_side_px"],
        "images_without_size": summary["images_without_size"],
        "filter_short_ge_128_age_20_70": summary["filter_short_ge_128_age_20_70"],
        "filter_short_ge_128": summary["filter_short_ge_128"],
        "k5_records": stats["counts"]["k5_records"],
        "rejected": stats["counts"]["rejected"],
        "rejected_by_reason": stats["counts"]["rejected_by_reason"],
        "image_failures_by_code": stats["counts"]["image_failures_by_code"],
        **pins,
    }


def run_pack(
    root,
    output,
    *,
    archive=None,
    images_dir=None,
    terms_snapshot=None,
    stages=("lx1", "lx2", "lx3"),
    prep_report=None,
    prepared_manifest=None,
    split_seed=SPLIT_SEED,
):
    root = Path(root).absolute()
    require(root.is_dir() and root == root.resolve(), "INVALID_ROOT")
    require(output.startswith("output/research/"), "OUTPUT_MUST_BE_RESEARCH_DIRECTORY")
    safe(root, output + "/summary.json")  # validate the output path early
    safe(root, _local(output, "state.json")).parent.mkdir(parents=True, exist_ok=True)
    state = _load_state(root, output)
    stages = tuple(stages)
    require(all(s in {"lx1", "lx2", "lx3"} for s in stages), "INVALID_STAGE")
    require("lx1" in stages or safe(root, images_dir).exists(), "IMAGES_DIR_MISSING")
    summary = {
        "schema_id": SCHEMA,
        "schema_version": 1,
        "producer_sha256": PRODUCER_SHA256,
        "python_runtime": sys.version.split()[0],
        "recorded_at_utc": _now(),
        "stages_completed": [],
        "inputs_stable": True,
        "contains_file_names_or_person_names": False,
        "password_accepted_or_stored": False,
        "research_only": True,
        "verified_on_real_data": False,
        "freeze_authorized": False,
        "split_assignment_performed": False,
        **acquisition.FLAGS,
        "status": "passed",
    }
    try:
        if "lx1" in stages:
            lx1 = run_lx1(root, archive, images_dir, terms_snapshot, output, state)
            summary.update(
                archive_present=lx1["archive_present"],
                extraction_method=lx1["extraction_method"],
                extracted_file_count=lx1["extracted_file_count"],
                extracted_readonly=lx1["extracted_readonly"],
            )
            for key in (
                "archive_bytes",
                "archive_sha256",
                "archive_mtime_utc",
                "archive_hashed_at_utc",
                "terms_snapshot_bytes",
                "terms_snapshot_sha256",
            ):
                if key in lx1:
                    summary[key] = lx1[key]
            summary["stages_completed"].append("lx1")
            state = _load_state(root, output)
        if "lx2" in stages:
            require(images_dir is not None, "IMAGES_DIR_REQUIRED")
            stats, resumed = run_lx2(root, images_dir, output, state)
            summary.update(_lx2_aggregates(root, output, stats))
            summary["stages_completed"].append("lx2")
            if resumed:
                summary["inputs_stable"] = True
            state = _load_state(root, output)
        if "lx3" in stages:
            summary.update(
                run_lx3(
                    root,
                    output,
                    state,
                    prep_report=prep_report,
                    prepared_manifest=prepared_manifest,
                    split_seed=split_seed,
                )
            )
            summary["stages_completed"].append("lx3")
    except (Error, OSError, ValueError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        summary["status"] = "rejected"
        # error_code is not a shareable summary field; keep it only in the local state.
        state = _load_state(root, output)
        state["last_error_code"] = code
        _save_state(root, output, state)
        raise
    body = encode_summary(summary)
    summary_name = output + "/summary.json"
    if safe(root, summary_name).exists():
        safe(root, summary_name).chmod(stat.S_IWUSR | stat.S_IRUSR)
        safe(root, summary_name).unlink()
    with safe(root, summary_name).open("xb") as stream:
        stream.write(body)
    return project_summary(summary)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "未传入 --local-only-ack 时拒绝运行且不写任何文件。"
            "本工具不接收、不保存解压密码。含文件名的输出仅限用户本机；"
            "对外只回传 summary.json（字段白名单：汇总数字与文件 SHA-256）。"
        ),
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--archive", help="optional official AgeDB.zip already on this machine")
    parser.add_argument("--images-dir", help="extracted folder, e.g. data/datasets/agedb")
    parser.add_argument("--terms-snapshot", help="optional local snapshot of the terms page")
    parser.add_argument("--output-dir", required=True, help="new or resumable output/research/...")
    parser.add_argument(
        "--stages",
        default="lx1,lx2,lx3",
        help="comma-separated subset of lx1,lx2,lx3 (default: all)",
    )
    parser.add_argument("--split-seed", default=SPLIT_SEED)
    parser.add_argument(
        "--local-only-ack",
        action="store_true",
        help="必须显式传入才会执行。确认含文件名的输出仅限用户本机、不得外传。",
    )
    args = parser.parse_args(argv)
    if not args.local_only_ack:
        print(
            "拒绝执行：未传入 --local-only-ack。"
            "本工具会写出含文件名的本机专用报告，默认禁止运行。"
            "请仅在用户本机确认后显式传入 --local-only-ack。"
            "本工具不接收、不保存解压密码。",
            file=sys.stderr,
        )
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "error_code": LOCAL_ONLY_ACK_REQUIRED,
                    **acquisition.FLAGS,
                }
            )
        )
        return 2
    print(f"==========\n{LOCAL_ONLY_WARNING}\n==========", file=sys.stderr)
    stages = tuple(part.strip() for part in args.stages.split(",") if part.strip())
    try:
        summary = run_pack(
            args.root,
            args.output_dir,
            archive=args.archive,
            images_dir=args.images_dir,
            terms_snapshot=args.terms_snapshot,
            stages=stages,
            split_seed=args.split_seed,
        )
    except (Error, OSError, ValueError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **acquisition.FLAGS}))
        return 2
    print(
        json.dumps(
            {
                "status": summary["status"],
                "output_dir": args.output_dir,
                "stages_completed": summary["stages_completed"],
                **acquisition.FLAGS,
            },
            ensure_ascii=False,
        )
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
