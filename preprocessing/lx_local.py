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
LX-2 is resumable when a fresh inventory hash of ``images_dir`` still matches the
stored pin; LX-1 re-validates the archive and extracted tree each run (it does
not re-extract when the folder already exists); LX-3 always recomputes.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import sys
import unicodedata
import zipfile
import zlib
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
# Same numeric limits as the unmerged FG-4 archive_preparation (not merged here).
ZIP_MAX_RATIO = 200
ZIP_RATIO_FLOOR_BYTES = 1024**2
AGE_LOW, AGE_HIGH = agedb.AGE_LOW, agedb.AGE_HIGH
FORMAL_USES = metadata.FORMAL_USES
SPLIT_SEED = "agemorph3d-lx3-identity-split-v1"
LX2_LEAVES = ("stats.json", "rejected.json", "manifest.json", "audit.json")
# LX-3 outputs are discarded before every LX-3 run so nothing stale survives a failure.
LX3_OUTPUTS = (
    "assignment-ledger.json",
    "exact-duplicates.json",
    "lx3-tools.json",
    "screen-plan.json",
    "p03-screen",
    "freeze-basis.json",
    "freeze-plan.json",
    "p04-freeze",
)
Error, require, safe = preparation.Error, preparation.require, preparation.safe
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")
_ZIP_LOCAL = struct.Struct("<4s5H3L2H")
MAX_ZIP_DIRECTORY_BYTES = 8 * 1024**2
ZIP_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
REGULAR_OR_DIR = {0, stat.S_IFREG, stat.S_IFDIR}
IMAGES_DIR_LEAF = re.compile(r"^[Aa]ge[Dd][Bb](?:[-_][A-Za-z0-9][A-Za-z0-9._-]*)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")
DECADE_RE = re.compile(r"^\d{1,3}-\d{1,3}$")
HIST_RE = re.compile(r"^(?:\d{1,5}-\d{1,5}|>=\d{1,5})$")
QUANTILE_RE = re.compile(r"^p\d{1,2}$")
RUNTIME_RE = re.compile(r"^\d+\.\d+\.\d+$")
LX2_STATUS_VALUES = {"passed", "needs_review"}
K5_AUDIT_VALUES = {"metadata_consistent", "completed_with_findings"}
SCREENING_VALUES = {"passed", "failed"}
FREEZE_VALUES = {"consistent", "blocked"}
# Pending user decisions (relayed by Atlas). Recorded as fixed disclosures so a
# zero exact-duplicate count can never be read as proof of no overlap.
PENDING_USER_DECISIONS = ("NEAR_DUPLICATE_METHOD", "SPLIT_RULE", "SMALL_CELL_SUPPRESSION")
FORCED_DISCLOSURES = {
    "near_duplicate_checked_at_full_scale": False,
    "near_duplicate_method_status": "pending_user_decision",
    "split_rule_status": "provisional_pending_user_decision",
    "split_ratio_has_source": False,
    "split_age_stratified": False,
    "small_cell_suppression_status": "pending_user_decision",
    "pending_user_decisions": list(PENDING_USER_DECISIONS),
    # Always true/false in this version; forced so an edited summary is detected.
    "p01_quality_checks_performed": False,
    "exact_duplicate_zero_does_not_prove_no_leakage": True,
    "small_cell_suppression_applied": False,
    "freeze_authorized": False,
    "split_assignment_performed": False,
}
STAGE_VALUES = {"lx1", "lx2", "lx3"}
STATUS_VALUES = {"passed", "needs_review", "rejected"}
EXTRACTION_METHODS = {"already_extracted", "safe_unencrypted_zip"}
GENDER_KEYS = {"male", "female"}
FILTER_KEYS = {"images", "identities", "identities_span_ge_30", "images_age_exact_70"}
SHORT_SIDE_KEYS = {"count", "min", "max", "median", "below_128", "histogram", "quantiles"}

# Shareable summary keys only. No filenames, person names, identity IDs,
# per-image records or feature values.
SUMMARY_WHITELIST = (
    "schema_id",
    "schema_version",
    "status",
    "error_code",
    "lx2_status",
    "k5_audit_status",
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
    "extracted_archive_consistent",
    "extracted_archive_crc_checked",
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
    "near_duplicate_screening_performed",
    "p01_quality_checks_performed",
    "exact_duplicate_zero_does_not_prove_no_leakage",
    "small_cell_suppression_applied",
    "near_duplicate_checked_at_full_scale",
    "near_duplicate_method_status",
    "split_rule_status",
    "split_ratio_has_source",
    "split_age_stratified",
    "small_cell_suppression_status",
    "pending_user_decisions",
    "k5_audit_finding_codes",
    "lx2_resumed",
    "assignment_ledger_sha256",
    "identity_group_origin",
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
_BOOL_KEYS = {
    "inputs_stable",
    "lx2_resumed",
    "archive_present",
    "extracted_readonly",
    "extracted_archive_crc_checked",
    "near_duplicate_screening_performed",
    "p03_p04_invoked",
    "contains_file_names_or_person_names",
    "password_accepted_or_stored",
    "research_only",
    "verified_on_real_data",
} | set(acquisition.FLAGS)
_SHA_KEYS = {
    "producer_sha256",
    "archive_sha256",
    "terms_snapshot_sha256",
    "k5_manifest_sha256",
    "inventory_sha256",
    "stats_sha256",
    "audit_sha256",
    "rejected_report_sha256",
    "assignment_ledger_sha256",
    "screening_report_sha256",
    "frozen_inputs_sha256",
}
_ISO_KEYS = {"recorded_at_utc", "archive_mtime_utc", "archive_hashed_at_utc"}
_INT_KEYS = {
    "schema_version",
    "archive_bytes",
    "extracted_file_count",
    "terms_snapshot_bytes",
    "images",
    "identities",
    "images_age_20_70",
    "images_age_exact_70",
    "identities_span_ge_30",
    "identities_span_ge_30_within_20_70",
    "age_min",
    "age_max",
    "images_without_size",
    "k5_records",
    "rejected",
    "split_train_images",
    "split_train_identities",
    "split_validation_images",
    "split_validation_identities",
    "split_test_images",
    "split_test_identities",
    "split_unassigned_images",
    "exact_duplicate_groups",
    "exact_duplicate_extra_copies",
    "cross_split_exact_duplicate_groups",
}
_NULLABLE_INTS = {"age_min", "age_max"}
_NULLABLE_SHA = {
    "archive_sha256",
    "terms_snapshot_sha256",
    "screening_report_sha256",
    "frozen_inputs_sha256",
}
_NULLABLE_BOOL = {"extracted_archive_consistent"}


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


def error_code_of(error):
    """Map any exception to a fixed code. Never return exception text (may contain names)."""
    if isinstance(error, Error):
        return str(error)
    if isinstance(error, zipfile.BadZipFile):
        return "ARCHIVE_CORRUPT_OR_NOT_ZIP"
    if isinstance(error, zipfile.LargeZipFile):
        return "ARCHIVE_TOO_LARGE"
    if isinstance(error, zlib.error):
        return "ARCHIVE_DECOMPRESS_FAILED"
    if isinstance(error, EOFError):
        return "ARCHIVE_TRUNCATED"
    if isinstance(error, (OSError, ValueError, KeyError, TypeError)):
        return "INPUT_REJECTED"
    return "UNEXPECTED_ERROR"


def _is_int(value):
    return type(value) is int and not isinstance(value, bool)


def _is_junction(path):
    checker = getattr(os.path, "isjunction", None)
    if checker is not None:
        try:
            return bool(checker(path))
        except OSError:
            return False
    try:
        meta = path.lstat()
    except OSError:
        return False
    return bool(getattr(meta, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _is_link_or_reparse(path):
    return path.is_symlink() or _is_junction(path)


def _assert_tree_has_no_links(path):
    """Scan the whole tree before any chmod, so a mid-tree link cannot leave partial modes."""
    if _is_link_or_reparse(path):
        raise Error("LINK_OR_REPARSE_PATH")
    if path.is_dir():
        for child in sorted(path.iterdir()):
            _assert_tree_has_no_links(child)
    elif not path.is_file():
        raise Error("NOT_REGULAR_FILE")


def _set_readonly(path):
    if _is_link_or_reparse(path):
        raise Error("LINK_OR_REPARSE_PATH")
    if path.is_dir():
        for child in sorted(path.iterdir()):
            _set_readonly(child)
        os.chmod(path, 0o555)
    elif path.is_file():
        os.chmod(path, 0o444)
    else:
        raise Error("NOT_REGULAR_FILE")


def _set_readonly_after_scan(path):
    _assert_tree_has_no_links(path)
    _set_readonly(path)


def _is_readonly(path):
    if _is_link_or_reparse(path):
        return False
    if path.is_file():
        return not (path.stat().st_mode & 0o222)
    if path.is_dir():
        return all(_is_readonly(child) for child in path.iterdir())
    return False


def _unlock_tree(path):
    if _is_link_or_reparse(path) or not path.exists():
        return
    if path.is_dir():
        os.chmod(path, 0o755)
        for child in path.iterdir():
            _unlock_tree(child)
    elif path.is_file():
        os.chmod(path, 0o644)


def require_images_dir(images_dir):
    """Restrict --images-dir to a dedicated AgeDB folder under data/datasets/."""
    require(type(images_dir) is str and images_dir, "IMAGES_DIR_REQUIRED")
    require("\\" not in images_dir and not images_dir.startswith("/"), "IMAGES_DIR_SCOPE")
    parts = Path(images_dir).parts
    require(".." not in parts and "." not in parts, "IMAGES_DIR_SCOPE")
    require(
        len(parts) == 3 and parts[0] == "data" and parts[1] == "datasets",
        "IMAGES_DIR_SCOPE",
    )
    require(bool(IMAGES_DIR_LEAF.fullmatch(parts[2])), "IMAGES_DIR_SCOPE")
    return images_dir


def _looks_like_zip(path):
    with path.open("rb") as stream:
        magic = stream.read(4)
    return magic in ZIP_MAGICS


def _end_record_position(tail):
    """The single end record whose declared comment length reaches EOF exactly.

    Scans backward through every end signature in the tail window. Two
    self-consistent candidates, or an end signature inside the chosen record's
    comment (where CPython ``zipfile`` would pick a different record), are
    ambiguous. Signatures that are not self-consistent are member data.
    """
    found, start = [], len(tail)
    while (position := tail.rfind(b"PK\x05\x06", 0, start)) >= 0:
        start = position
        if position + 22 <= len(tail):
            comment = int.from_bytes(tail[position + 20 : position + 22], "little")
            if position + 22 + comment == len(tail):
                found.append(position)
    require(found, "ZIP_END_INVALID")
    require(len(found) == 1, "ZIP_END_AMBIGUOUS")
    require(b"PK\x05\x06" not in tail[found[0] + 22 :], "ZIP_END_AMBIGUOUS")
    return found[0]


def _zip_guard(path, max_members=MAX_MEMBERS):
    """Bound and pin the zip layout before ZipFile builds entry objects.

    Re-implements (does not import) the unmerged FG-4 layout rules, tightened in
    SN-6 round 2: the file starts with a local header (or is an empty archive),
    exactly one end record ends the file (its declared comment reaches EOF, and the
    comment holds no further end signature), no multi-disk, ZIP64 or locator, and
    the central directory ends exactly where the end record starts. CPython's
    ``zipfile`` silently tolerates prepended or concatenated data by shifting
    offsets; this guard refuses such files instead. Returns the directory offset.

    End signatures earlier in the file (inside member data, e.g. a stored nested
    zip as the last member) are fine: adjacency, the gap check and the
    comment-reaches-EOF rule already reject concatenated, prepended and trailing
    data (SN-6 round 2 follow-up).
    """
    require(_looks_like_zip(path), "ARCHIVE_NOT_ZIP")
    size = path.stat().st_size
    with path.open("rb") as stream:
        tail_start = max(0, size - 65557)
        stream.seek(tail_start)
        tail = stream.read(65557)
    position = _end_record_position(tail)
    _, disk, directory_disk, disk_count, count, directory_bytes, offset, comment = struct.unpack(
        "<4s4H2LH", tail[position : position + 22]
    )
    require(
        position + 22 + comment == len(tail)
        and disk == directory_disk == 0
        and disk_count == count
        and count != 65535
        and offset != 0xFFFFFFFF,
        "ZIP_LAYOUT_UNSUPPORTED",
    )
    end_record = tail_start + position
    require(b"PK\x06\x07" not in tail[max(0, position - 20) : position], "ZIP_LAYOUT_UNSUPPORTED")
    require(
        count <= max_members and directory_bytes <= MAX_ZIP_DIRECTORY_BYTES,
        "ZIP_DIRECTORY_LIMIT",
    )
    require(offset + directory_bytes == end_record, "ZIP_DIRECTORY_NOT_ADJACENT")
    if count == 0:
        require(offset == 0 and directory_bytes == 0, "ZIP_LAYOUT_UNSUPPORTED")
    else:
        with path.open("rb") as stream:
            require(stream.read(4) == b"PK\x03\x04", "ZIP_PREFIX_UNSUPPORTED")
    return offset, count


def _zip_layout(path, infos, directory_offset):
    """Entries start at offset 0, follow each other with no gap or overlap, and the
    central directory starts right after the last one; local headers match it."""
    end = 0
    with path.open("rb") as stream:
        for info in sorted(infos, key=lambda item: item.header_offset):
            require(info.header_offset <= end, "ZIP_ENTRY_GAP")
            require(info.header_offset >= end, "ZIP_ENTRY_OVERLAP")
            stream.seek(info.header_offset)
            header = stream.read(_ZIP_LOCAL.size)
            require(len(header) == _ZIP_LOCAL.size, "ZIP_LOCAL_HEADER_INVALID")
            signature, _, flags, method, *_, name_length, extra_length = _ZIP_LOCAL.unpack(header)
            raw = stream.read(name_length)
            encoding = "utf-8" if flags & 0x800 else "cp437"
            require(
                signature == b"PK\x03\x04"
                and len(raw) == name_length
                and raw.decode(encoding, "replace") == info.orig_filename
                and method == info.compress_type
                and (flags & 1) == (info.flag_bits & 1),
                "ZIP_LOCAL_HEADER_MISMATCH",
            )
            end = info.header_offset + _ZIP_LOCAL.size + name_length + extra_length
            end += info.compress_size
            if flags & 0x08:  # data descriptor, with or without its optional signature
                stream.seek(end)
                end += 16 if stream.read(4) == b"PK\x07\x08" else 12
            require(end <= directory_offset, "ZIP_ENTRY_OVERLAP")
    require(end == directory_offset, "ZIP_ENTRY_GAP")


def _checked_infos(path, max_members=MAX_MEMBERS):
    """Guarded central-directory read; any zipfile error becomes a fixed code."""
    offset, count = _zip_guard(path, max_members)
    try:
        with zipfile.ZipFile(path) as container:
            infos = list(container.infolist())
            directory_offset = container.start_dir
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, zlib.error) as error:
        raise Error(error_code_of(error)) from None
    require(directory_offset == offset and len(infos) == count, "ZIP_DIRECTORY_INVALID")
    _zip_layout(path, infos, directory_offset)
    return infos


def _member_encrypted(info):
    return bool(info.flag_bits & 1) or info.compress_type == 99


def zip_is_encrypted(path):
    return any(_member_encrypted(info) for info in _checked_infos(path))


def _member_key(name):
    return unicodedata.normalize("NFC", name).casefold()


def _scan_zip(archive, limits):
    inventory, names, total = [], set(), 0
    infos = _checked_infos(archive, limits["members"])
    require(not any(_member_encrypted(info) for info in infos), "ZIP_ENCRYPTED")
    for info in infos:
        require(len(inventory) < limits["members"], "MEMBER_COUNT_LIMIT")
        name = info.filename.replace("\\", "/")
        if info.is_dir() and name.endswith("/"):
            name = name[:-1]
        acquisition._relative(name)
        kind = stat.S_IFMT(info.external_attr >> 16)
        require(kind in REGULAR_OR_DIR, "SPECIAL_MEMBER")
        require(info.compress_type in ZIP_METHODS, "ZIP_METHOD_UNSUPPORTED")
        require(type(info.file_size) is int and info.file_size >= 0, "MEMBER_SIZE_INVALID")
        require(not info.is_dir() or info.file_size == 0, "MEMBER_SIZE_INVALID")
        require(info.file_size <= limits["member_bytes"], "MEMBER_SIZE_LIMIT")
        require(
            info.file_size <= ZIP_RATIO_FLOOR_BYTES
            or info.file_size <= ZIP_MAX_RATIO * max(info.compress_size, 1),
            "COMPRESSION_RATIO_LIMIT",
        )
        key = _member_key(name)
        require(key not in names, "DUPLICATE_MEMBER_PATH")
        names.add(key)
        if not info.is_dir():
            total += info.file_size
            require(total <= limits["total_bytes"], "TOTAL_UNPACKED_LIMIT")
        inventory.append((info, name, info.is_dir()))
    return inventory


def safe_extract_zip(root, archive_name, output_name, limits=None):
    """Extract a non-encrypted zip member-by-member with zip-slip checks. No extractall.

    Only partly equivalent (部分等价) to the unmerged FG-4 ``archive_preparation``
    rules, re-implemented here rather than shared: non-zip input, prepended data,
    multi-disk/ZIP64 layouts, overlapping entries, local/central header mismatch,
    encrypted members, symlink/device members, unsupported methods, size and
    compression-ratio limits, NFC+casefold duplicate names and short/long member
    bodies are rejected. Not covered: tar/tar.gz (unsupported here) and FG-4's
    ``safe_loading`` module, which is not merged into this branch.
    """
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
                        require(copied <= info.file_size, "MEMBER_BODY_LIMIT")
                        out.write(chunk)
                    require(copied == info.file_size, "INCOMPLETE_MEMBER")
                written += 1
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, zlib.error) as error:
        shutil.rmtree(target, ignore_errors=True)
        path = target.parent
        while path != created.parent and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            path = path.parent
        raise Error(error_code_of(error)) from None
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        path = target.parent
        while path != created.parent and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            path = path.parent
        raise
    return written


def _zip_file_members(archive):
    rows = []
    for info in _checked_infos(archive):
        name = info.filename.replace("\\", "/")
        if info.is_dir() or name.endswith("/"):
            continue
        acquisition._relative(name)
        rows.append({"rel": name, "bytes": info.file_size, "crc32": info.CRC & 0xFFFFFFFF})
    return rows


def _strip_common_prefix(names):
    parts = [name.split("/") for name in names]
    if parts and all(len(item) >= 2 and item[0] == parts[0][0] for item in parts):
        return [name.split("/", 1)[1] for name in names]
    return list(names)


def _extracted_files(root, images_dir):
    base = safe(root, images_dir)
    rows = []
    for path in sorted(base.rglob("*")):
        if _is_link_or_reparse(path):
            raise Error("LINK_OR_REPARSE_PATH")
        if path.is_file():
            rows.append((path.relative_to(base).as_posix(), path))
    return rows


def verify_extracted_against_archive(root, images_dir, archive_name):
    """Compare extracted files to the zip central directory (names, sizes, CRC32).

    The central directory is readable without a password, including for encrypted
    official packs. Names are used only as in-memory keys and are never printed.
    """
    members = _zip_file_members(safe(root, archive_name))
    files = _extracted_files(root, images_dir)
    file_map = {rel: path for rel, path in files}
    key_sets = [[item["rel"] for item in members]]
    stripped = _strip_common_prefix(key_sets[0])
    if stripped != key_sets[0]:
        key_sets.append(stripped)
    for keys in key_sets:
        if len(keys) != len(set(keys)) or len(keys) != len(members):
            continue
        mapped = {key: item for key, item in zip(keys, members, strict=True)}
        if set(mapped) != set(file_map):
            continue
        crc_checked = True
        for rel, path in file_map.items():
            item = mapped[rel]
            if path.stat().st_size != item["bytes"]:
                return {
                    "consistent": False,
                    "crc_checked": False,
                    "code": "EXTRACTED_ARCHIVE_SIZE_MISMATCH",
                }
            if item["crc32"] == 0:
                crc_checked = False
                continue
            actual = binascii.crc32(path.read_bytes()) & 0xFFFFFFFF
            if actual != item["crc32"]:
                return {
                    "consistent": False,
                    "crc_checked": True,
                    "code": "EXTRACTED_ARCHIVE_CRC_MISMATCH",
                }
        return {"consistent": True, "crc_checked": crc_checked, "code": None}
    code = (
        "EXTRACTED_ARCHIVE_COUNT_MISMATCH"
        if len(files) != len(members)
        else "EXTRACTED_ARCHIVE_NAME_SET_MISMATCH"
    )
    return {"consistent": False, "crc_checked": False, "code": code}


def _require_int(value, allow_null=False):
    if allow_null and value is None:
        return None
    require(_is_int(value), "SUMMARY_FIELD_TYPE")
    require(value >= 0, "SUMMARY_FIELD_VALUE")
    return value


def _require_bool(value):
    require(type(value) is bool, "SUMMARY_FIELD_TYPE")
    return value


def _require_sha(value, allow_null=False):
    if allow_null and value is None:
        return None
    require(type(value) is str and bool(SHA256_RE.fullmatch(value)), "SUMMARY_FIELD_VALUE")
    return value


def _require_iso(value):
    require(type(value) is str and bool(ISO_RE.fullmatch(value)), "SUMMARY_FIELD_VALUE")
    return value


def _require_code(value, allow_null=False):
    if allow_null and value is None:
        return None
    require(type(value) is str and bool(CODE_RE.fullmatch(value)), "SUMMARY_FIELD_VALUE")
    return value


def _require_token(value, allow_null=False):
    if allow_null and value is None:
        return None
    require(type(value) is str and bool(TOKEN_RE.fullmatch(value)), "SUMMARY_FIELD_VALUE")
    return value


def _validate_count_map(key, value):
    require(type(value) is dict, "SUMMARY_FIELD_TYPE")
    out = {}
    for item_key, item_value in value.items():
        require(type(item_key) is str, "SUMMARY_FIELD_TYPE")
        require(_is_int(item_value) and item_value >= 0, "SUMMARY_FIELD_TYPE")
        if key == "images_by_age_decade":
            require(bool(DECADE_RE.fullmatch(item_key)), "SUMMARY_FIELD_VALUE")
        elif key == "images_by_gender":
            require(item_key in GENDER_KEYS, "SUMMARY_FIELD_VALUE")
        else:
            require(bool(TOKEN_RE.fullmatch(item_key)), "SUMMARY_FIELD_VALUE")
        out[item_key] = item_value
    return out


def _require_median(value):
    """Median of integer pixel sides: FG-2 keeps ``statistics.median`` (true median).

    For an even count it is the mean of the two middle values, so it is an int, an
    ``x.0`` float or an ``x.5`` float. Accept exactly those (finite, non-negative,
    not bool) or None when no image was readable.
    """
    if value is None:
        return None
    if _is_int(value):
        require(value >= 0, "SUMMARY_FIELD_VALUE")
        return value
    require(type(value) is float, "SUMMARY_FIELD_TYPE")
    require(math.isfinite(value) and value >= 0, "SUMMARY_FIELD_VALUE")
    require((value * 2).is_integer(), "SUMMARY_FIELD_VALUE")
    return value


def normalize_short_side(value):
    """Give the zero-readable case the same keys as the normal case.

    FG-2 ``_short_side_stats`` returns only count/min/max/median/quantiles when no
    image header was readable; the summary always carries all seven keys, with
    None for min/max/median, 0 below 128, and empty histogram/quantiles.
    """
    require(type(value) is dict, "SUMMARY_FIELD_TYPE")
    if value.get("count") == 0 and set(value) <= SHORT_SIDE_KEYS:
        require(
            all(value.get(key) is None for key in ("min", "max", "median", "quantiles")),
            "SUMMARY_FIELD_VALUE",
        )
        return {
            "count": 0,
            "min": None,
            "max": None,
            "median": None,
            "below_128": 0,
            "histogram": {},
            "quantiles": {},
        }
    return value


def _validate_short_side(value):
    require(type(value) is dict and set(value) == SHORT_SIDE_KEYS, "SUMMARY_FIELD_TYPE")
    out = {}
    for field in ("count", "min", "max", "below_128"):
        out[field] = _require_int(value[field], allow_null=field in {"min", "max"})
    out["median"] = _require_median(value["median"])
    if out["count"] == 0:
        require(
            out["min"] is None
            and out["max"] is None
            and out["median"] is None
            and out["below_128"] == 0
            and value["histogram"] == {}
            and value["quantiles"] == {},
            "SUMMARY_FIELD_VALUE",
        )
    else:
        require(None not in (out["min"], out["max"], out["median"]), "SUMMARY_FIELD_VALUE")
        require(out["min"] <= out["median"] <= out["max"], "SUMMARY_FIELD_VALUE")
    require(type(value["histogram"]) is dict, "SUMMARY_FIELD_TYPE")
    histogram = {}
    for item_key, item_value in value["histogram"].items():
        require(type(item_key) is str and bool(HIST_RE.fullmatch(item_key)), "SUMMARY_FIELD_VALUE")
        require(_is_int(item_value), "SUMMARY_FIELD_TYPE")
        require(item_value >= 0, "SUMMARY_FIELD_VALUE")
        histogram[item_key] = item_value
    out["histogram"] = histogram
    require(type(value["quantiles"]) is dict, "SUMMARY_FIELD_TYPE")
    quantiles = {}
    for item_key, item_value in value["quantiles"].items():
        ok = type(item_key) is str and bool(QUANTILE_RE.fullmatch(item_key))
        require(ok, "SUMMARY_FIELD_VALUE")
        require(_is_int(item_value), "SUMMARY_FIELD_TYPE")
        require(item_value >= 0, "SUMMARY_FIELD_VALUE")
        quantiles[item_key] = item_value
    out["quantiles"] = quantiles
    return out


def _validate_filter(value):
    require(type(value) is dict and set(value) == FILTER_KEYS, "SUMMARY_FIELD_TYPE")
    return {field: _require_int(value[field]) for field in FILTER_KEYS}


def project_summary(values):
    """Keep only whitelisted keys and require a value pattern for each key."""
    require(type(values) is dict, "SUMMARY_NOT_OBJECT")
    extra = set(values) - set(SUMMARY_WHITELIST)
    require(not extra, "SUMMARY_EXTRA_FIELDS")
    out = {}
    for key in SUMMARY_WHITELIST:
        if key not in values:
            continue
        value = values[key]
        if key == "schema_id":
            require(value == SCHEMA, "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key == "status":
            require(value in STATUS_VALUES, "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key == "error_code":
            out[key] = _require_code(value, allow_null=True)
        elif key == "identity_group_origin":
            require(value in {"official", "unknown"}, "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key == "lx2_status":
            require(value in LX2_STATUS_VALUES, "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key == "k5_audit_status":
            require(value in K5_AUDIT_VALUES, "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key in FORCED_DISCLOSURES:
            require(value == FORCED_DISCLOSURES[key], "SUMMARY_DISCLOSURE_ALTERED")
            require(type(value) is type(FORCED_DISCLOSURES[key]), "SUMMARY_DISCLOSURE_ALTERED")
            out[key] = list(value) if type(value) is list else value
        elif key == "k5_audit_finding_codes":
            require(type(value) is list, "SUMMARY_FIELD_TYPE")
            out[key] = [_require_code(item) for item in value]
            require(out[key] == sorted(set(out[key])), "SUMMARY_FIELD_VALUE")
        elif key == "python_runtime":
            require(type(value) is str and bool(RUNTIME_RE.fullmatch(value)), "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key == "extraction_method":
            require(value in EXTRACTION_METHODS or value is None, "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key == "p03_p04_block_reason":
            out[key] = _require_code(value, allow_null=True)
        elif key == "screening_status":
            require(value is None or value in SCREENING_VALUES, "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key == "split_freeze_status":
            require(value is None or value in FREEZE_VALUES, "SUMMARY_FIELD_VALUE")
            out[key] = value
        elif key == "stages_completed":
            require(type(value) is list, "SUMMARY_FIELD_TYPE")
            require(all(item in STAGE_VALUES for item in value), "SUMMARY_FIELD_VALUE")
            out[key] = list(value)
        elif key == "extracted_archive_consistent":
            require(type(value) is bool or value is None, "SUMMARY_FIELD_TYPE")
            out[key] = value
        elif key in _COUNT_MAPS:
            out[key] = _validate_count_map(key, value)
        elif key == "short_side_px":
            out[key] = _validate_short_side(value)
        elif key in {"filter_short_ge_128_age_20_70", "filter_short_ge_128"}:
            out[key] = _validate_filter(value)
        elif key in _SHA_KEYS:
            out[key] = _require_sha(value, allow_null=key in _NULLABLE_SHA)
        elif key in _ISO_KEYS:
            out[key] = _require_iso(value)
        elif key in _INT_KEYS:
            out[key] = _require_int(value, allow_null=key in _NULLABLE_INTS)
        elif key in _BOOL_KEYS:
            out[key] = _require_bool(value)
        else:
            raise Error("SUMMARY_FIELD_TYPE")
    out.setdefault("schema_id", SCHEMA)
    out.setdefault("schema_version", 1)
    out.setdefault("contains_file_names_or_person_names", False)
    out.setdefault("password_accepted_or_stored", False)
    out.setdefault("research_only", True)
    out.setdefault("verified_on_real_data", False)
    out.setdefault("freeze_authorized", False)
    out.setdefault("split_assignment_performed", False)
    out.setdefault("near_duplicate_screening_performed", False)
    out.setdefault("p01_quality_checks_performed", False)
    out.setdefault("exact_duplicate_zero_does_not_prove_no_leakage", True)
    out.setdefault("small_cell_suppression_applied", False)
    for key, value in FORCED_DISCLOSURES.items():
        out.setdefault(key, list(value) if type(value) is list else value)
    for flag, default in acquisition.FLAGS.items():
        out.setdefault(flag, default)
    return out


def encode_summary(values):
    return acquisition._encoded(project_summary(values))


def _local(output, leaf):
    return output + "/local/" + leaf


def _owned_local(output, leaf):
    name = _local(output, leaf)
    require(name.startswith(output + "/local/"), "INTERNAL_PATH")
    return name


def _remove_owned(root, output, leaf):
    """Delete a half-finished stage directory only under this run's output/local/."""
    name = _owned_local(output, leaf)
    path = safe(root, name)
    output_root = safe(root, output)
    local_root = safe(root, output + "/local")
    require(local_root.is_relative_to(output_root), "INTERNAL_PATH")
    require(path == local_root or path.is_relative_to(local_root), "INTERNAL_PATH")
    if not path.exists():
        return
    _unlock_tree(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()


def _stash_summary(root, output):
    name = output + "/summary.json"
    path = safe(root, name)
    if not path.exists():
        return
    stale = safe(root, _owned_local(output, "summary.stale.json"))
    path.chmod(stat.S_IWUSR | stat.S_IRUSR)
    if stale.exists():
        stale.chmod(stat.S_IWUSR | stat.S_IRUSR)
        stale.unlink()
    stale.parent.mkdir(parents=True, exist_ok=True)
    path.rename(stale)


def _write_rejected_summary(root, output, summary, code):
    summary = {
        **summary,
        "status": "rejected",
        "error_code": code,
        "contains_file_names_or_person_names": False,
        "password_accepted_or_stored": False,
    }
    try:
        body = encode_summary(summary)
    except (Error, OSError, ValueError, KeyError, TypeError):
        body = encode_summary(
            {
                "schema_id": SCHEMA,
                "schema_version": 1,
                "status": "rejected",
                "error_code": code,
                "producer_sha256": PRODUCER_SHA256,
                "python_runtime": sys.version.split()[0],
                "recorded_at_utc": _now(),
                "stages_completed": list(summary.get("stages_completed") or []),
                "inputs_stable": False,
                "contains_file_names_or_person_names": False,
                "password_accepted_or_stored": False,
                "research_only": True,
                "verified_on_real_data": False,
                "freeze_authorized": False,
                "split_assignment_performed": False,
                "near_duplicate_screening_performed": False,
                "p01_quality_checks_performed": False,
                "exact_duplicate_zero_does_not_prove_no_leakage": True,
                "small_cell_suppression_applied": False,
                **acquisition.FLAGS,
            }
        )
    name = output + "/summary.json"
    path = safe(root, name)
    if path.exists():
        path.chmod(stat.S_IWUSR | stat.S_IRUSR)
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(body)


def _record_error(root, output, code):
    if not output:
        return
    try:
        # Only update a state file that already exists in a valid output directory;
        # never create anything for an output argument that failed validation.
        if type(output) is not str or not output.startswith("output/research/"):
            return
        root = Path(root).absolute()
        if not safe(root, _local(output, "state.json")).is_file():
            return
        state = _load_state(root, output)
        state["last_error_code"] = code
        _save_state(root, output, state)
    except Exception:  # best effort only; never let a recording failure print a traceback
        return


def _load_state(root, output):
    path = safe(root, _local(output, "state.json"))
    if not path.exists():
        return {
            "schema_id": STATE_SCHEMA,
            "local_only": True,
            "output_dir": output,
            "stages": {},
        }
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Error("STATE_CORRUPT") from None
    require(
        type(state) is dict
        and state.get("schema_id") == STATE_SCHEMA
        and state.get("output_dir") == output
        and type(state.get("stages")) is dict,
        "STATE_CORRUPT",
    )
    return state


def _save_state(root, output, state):
    state = {**state, "schema_id": STATE_SCHEMA, "local_only": True, "output_dir": output}
    return _replace_json(root, _local(output, "state.json"), state)


def _inventory_sha256(root, images_dir):
    _files, rows, rejected = agedb.collect(root, images_dir)
    return agedb._inventory_sha256(rows, rejected)


def _apply_archive_check(root, images_dir, archive_name, report):
    if archive_name is None:
        report["extracted_archive_consistent"] = None
        report["extracted_archive_crc_checked"] = False
        return report
    check = verify_extracted_against_archive(root, images_dir, archive_name)
    report["extracted_archive_consistent"] = check["consistent"]
    report["extracted_archive_crc_checked"] = check["crc_checked"]
    if not check["consistent"]:
        raise Error(check["code"])
    return report


def run_lx1(root, archive_name, images_dir, terms_name, output, state):
    """Pin the official pack, reuse or safely extract it, and set the folder read-only."""
    require_images_dir(images_dir)
    report = {
        "schema_id": REPORT_SCHEMA,
        "local_only": True,
        "stage": "lx1",
        "archive_present": archive_name is not None,
        "password_accepted_or_stored": False,
        "extraction_method": None,
        "extracted_file_count": 0,
        "extracted_readonly": False,
        "extracted_archive_consistent": None,
        "extracted_archive_crc_checked": False,
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
        require(not _is_link_or_reparse(images), "LINK_OR_REPARSE_PATH")
        _assert_tree_has_no_links(images)
        files = [p for p in images.rglob("*") if p.is_file() and not p.is_symlink()]
        require(files, "IMAGES_DIR_EMPTY")
        # Re-verify the reused folder against the archive before touching its modes.
        _apply_archive_check(root, images_dir, archive_name, report)
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
        _set_readonly_after_scan(images)
        report.update(
            extraction_method="safe_unencrypted_zip",
            extracted_file_count=written,
            extracted_readonly=_is_readonly(images),
        )
        _apply_archive_check(root, images_dir, archive_name, report)
    else:
        raise Error("ARCHIVE_OR_IMAGES_REQUIRED")
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
    """Call FG-2 library export()/build(); never the password-bearing surface.

    Reuse only when a previous run marked lx2 as passed, a fresh inventory hash
    of images_dir (every file's SHA-256, size and path) matches the stored pin,
    and every stored stats file still matches its recorded SHA-256. Anything
    else (stale, half-finished or edited output) is removed only under this
    output's local/ folder and the stage is rerun; LX-3 state is then invalidated.
    """
    require_images_dir(images_dir)
    stats_dir = _owned_local(output, "agedb-stats")
    prior = state.get("stages", {}).get("lx2")
    inventory = _inventory_sha256(root, images_dir)
    if _lx2_reusable(root, prior, stats_dir, inventory):
        stats_path = safe(root, stats_dir + "/stats.json")
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        if stats.get("inventory_sha256") == inventory:
            return stats, {"resumed": True, "inputs_stable": True}
    state.setdefault("stages", {}).pop("lx2", None)
    invalidate_lx3(root, output, state)
    if safe(root, stats_dir).exists():
        _remove_owned(root, output, "agedb-stats")
    stats = agedb.export(root, images_dir, stats_dir)
    pins = {
        leaf: hashlib.sha256(safe(root, stats_dir + "/" + leaf).read_bytes()).hexdigest()
        for leaf in LX2_LEAVES
    }
    state.setdefault("stages", {})["lx2"] = {
        "status": "passed",
        "inventory_sha256": stats["inventory_sha256"],
        "output_dir": stats_dir,
        "pins": pins,
    }
    _save_state(root, output, state)
    inputs_stable = prior is None or (
        prior.get("status") == "passed" and prior.get("inventory_sha256") == inventory
    )
    return stats, {"resumed": False, "inputs_stable": inputs_stable}


def invalidate_lx3(root, output, state):
    """Mark LX-3 not passed and delete its ledger and P03/P04 leftovers (local/ only)."""
    state.setdefault("stages", {}).pop("lx3", None)
    _save_state(root, output, state)
    for leaf in LX3_OUTPUTS:
        _remove_owned(root, output, leaf)


def _lx2_reusable(root, prior, stats_dir, inventory):
    if not (
        type(prior) is dict
        and prior.get("status") == "passed"
        and prior.get("inventory_sha256") == inventory
        and prior.get("output_dir") == stats_dir
        and type(prior.get("pins")) is dict
        and set(prior["pins"]) == set(LX2_LEAVES)
    ):
        return False
    for leaf in LX2_LEAVES:
        path = safe(root, stats_dir + "/" + leaf)
        if not path.is_file() or _is_link_or_reparse(path):
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != prior["pins"][leaf]:
            return False
    return True


def verify_lx2_outputs(root, output, state, images_dir=None):
    """Before LX-3 uses LX-2 outputs: pins must match, and inputs must be unchanged."""
    prior = state.get("stages", {}).get("lx2")
    require(type(prior) is dict and prior.get("status") == "passed", "LX2_REQUIRED")
    stats_dir = _owned_local(output, "agedb-stats")
    inventory = prior.get("inventory_sha256")
    if images_dir is not None:
        inventory = _inventory_sha256(root, images_dir)
        require(inventory == prior.get("inventory_sha256"), "LX2_STALE_RERUN_REQUIRED")
    require(_lx2_reusable(root, prior, stats_dir, inventory), "LX2_OUTPUT_CHANGED")
    return prior


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


def identity_group_origin(records, archive_consistent):
    """``official`` only for agedb-official records whose folder matched the archive
    in this same run (SN-6 condition); otherwise ``unknown``.

    Groups come from the name field of the official filenames by a fixed rule (FG-2);
    nobody reviewed them, so ``human`` is never used. ``group_id`` is
    ``"subject-" + sha256(subject_id)[:16]`` with ``subject_id = "agedb-subject:" +
    sha256(name)[:24]`` (FG-2 ``agedb_filenames.subject_id``): two unsalted hashes of
    the name, so it can still be reversed against the public name list. It is a
    stable key, not an anonymisation.
    """
    official = archive_consistent is True and all(
        row.get("dataset_id") == agedb.DATASET_ID for row in records
    )
    return "official" if official else "unknown"


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
    root,
    output,
    state,
    *,
    prep_report=None,
    prepared_manifest=None,
    split_seed=SPLIT_SEED,
    images_dir=None,
    archive_consistent=False,
):
    """Identity-based split proposal plus exact-hash QC; call P03/P04 when possible.

    Official-scale AgeDB is not sent through ``duplicate_screening`` or
    ``split_freeze`` (those tools still cap at 32 images and need P01 artifacts).
    Default LX-3 therefore performs no perceptual near-duplicate screening and no
    P01 decode/orientation quality checks. ``cross_split_exact_duplicate_groups``
    being 0 does not prove the absence of leakage. The official-scale
    near-duplicate method, the split rule (the 70/15/15 hash rule has no source
    and is not age-stratified) and small-cell suppression are pending user
    decisions and are not chosen here; summary.json says so in fixed fields.
    This stage always recomputes after re-verifying the LX-2 pins.
    """
    # Invalidate first: a failed re-verification must not leave an old ledger behind.
    invalidate_lx3(root, output, state)
    lx2 = verify_lx2_outputs(root, output, state, images_dir)
    stats_dir = lx2["output_dir"]
    manifest_body = safe(root, stats_dir + "/manifest.json").read_bytes()
    require(
        hashlib.sha256(manifest_body).hexdigest() == lx2["pins"]["manifest.json"],
        "LX2_OUTPUT_CHANGED",
    )
    manifest = json.loads(manifest_body.decode("utf-8"))
    metadata.validate_manifest(manifest)
    records = manifest["records"]
    origin = identity_group_origin(records, archive_consistent)
    assignments, exclusions, included, by_id = assign_identities(records, seed=split_seed)
    groups, extra, cross, group_map = _exact_duplicates(records, assignments)
    ledger = {
        "schema_id": REPORT_SCHEMA,
        "local_only": True,
        "stage": "lx3",
        "seed": split_seed,
        "identity_group_origin": origin,
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
        "near_duplicate_screening_performed": False,
        "p01_quality_checks_performed": False,
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
                            "origin": origin,
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
                    near_duplicate_screening_performed=True,
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
        "identity_group_origin": origin,
        "near_duplicate_screening_performed": tool["near_duplicate_screening_performed"],
        "p01_quality_checks_performed": False,
        "exact_duplicate_zero_does_not_prove_no_leakage": True,
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


def _audit_finding_codes(root, stats_dir):
    """Finding codes only (e.g. NEAR_DUPLICATE_REVIEW_PENDING); never sample IDs."""
    audit = json.loads(safe(root, stats_dir + "/audit.json").read_text(encoding="utf-8"))
    findings = audit.get("findings") or []
    codes = {item.get("code") for item in findings if type(item) is dict}
    return sorted(code for code in codes if type(code) is str and CODE_RE.fullmatch(code))


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
        "lx2_status": stats["status"],
        "k5_audit_status": stats["k5_audit_status"],
        "k5_audit_finding_codes": _audit_finding_codes(root, stats_dir),
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
        "short_side_px": normalize_short_side(summary["short_side_px"]),
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
    suppress_small_cells=False,
):
    # Phase A: validate where we may write. A failure here writes nothing at all,
    # because the output location itself is not trusted yet.
    root = Path(root).absolute()
    require(root.is_dir() and root == root.resolve(), "INVALID_ROOT")
    require(
        type(output) is str and output.startswith("output/research/"),
        "OUTPUT_MUST_BE_RESEARCH_DIRECTORY",
    )
    safe(root, output + "/summary.json")
    safe(root, _local(output, "state.json"))
    # Phase B: from here on every failure writes a rejected summary.json.
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
        "near_duplicate_screening_performed": False,
        "p01_quality_checks_performed": False,
        "exact_duplicate_zero_does_not_prove_no_leakage": True,
        "small_cell_suppression_applied": False,
        **acquisition.FLAGS,
        "status": "passed",
    }
    try:
        if suppress_small_cells:
            raise Error("SMALL_CELL_SUPPRESSION_POLICY_UNSETTLED")
        safe(root, _local(output, "state.json")).parent.mkdir(parents=True, exist_ok=True)
        _stash_summary(root, output)
        if images_dir is not None:
            require_images_dir(images_dir)
        state = _load_state(root, output)
        stages = tuple(stages)
        require(all(s in {"lx1", "lx2", "lx3"} for s in stages), "INVALID_STAGE")
        require(images_dir is not None, "IMAGES_DIR_REQUIRED")
        require("lx1" in stages or safe(root, images_dir).exists(), "IMAGES_DIR_MISSING")
        if "lx1" in stages:
            lx1 = run_lx1(root, archive, images_dir, terms_snapshot, output, state)
            summary.update(
                archive_present=lx1["archive_present"],
                extraction_method=lx1["extraction_method"],
                extracted_file_count=lx1["extracted_file_count"],
                extracted_readonly=lx1["extracted_readonly"],
                extracted_archive_consistent=lx1["extracted_archive_consistent"],
                extracted_archive_crc_checked=lx1["extracted_archive_crc_checked"],
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
            stats, resume = run_lx2(root, images_dir, output, state)
            summary.update(_lx2_aggregates(root, output, stats))
            summary["stages_completed"].append("lx2")
            summary["inputs_stable"] = resume["inputs_stable"]
            summary["lx2_resumed"] = resume["resumed"]
            if stats["status"] != "passed":
                summary["status"] = "needs_review"
            state = _load_state(root, output)
        if "lx3" in stages:
            # Without LX-2 in this run, LX-3 must re-hash the inputs itself.
            if "lx2" not in stages:
                require(images_dir is not None, "IMAGES_DIR_REQUIRED")
            summary.update(
                run_lx3(
                    root,
                    output,
                    state,
                    prep_report=prep_report,
                    prepared_manifest=prepared_manifest,
                    split_seed=split_seed,
                    images_dir=None if "lx2" in stages else images_dir,
                    archive_consistent=(
                        "lx1" in stages and summary.get("extracted_archive_consistent") is True
                    ),
                )
            )
            summary["stages_completed"].append("lx3")
    except Exception as error:
        code = error_code_of(error)
        try:  # a corrupt state.json is left as it is, not overwritten
            state = _load_state(root, output)
            state["last_error_code"] = code
            _save_state(root, output, state)
        except Exception:
            pass
        _write_rejected_summary(root, output, summary, code)
        if isinstance(error, Error):
            raise
        raise Error(code) from None
    body = encode_summary(summary)
    summary_name = output + "/summary.json"
    if safe(root, summary_name).exists():
        safe(root, summary_name).chmod(stat.S_IWUSR | stat.S_IRUSR)
        safe(root, summary_name).unlink()
    with safe(root, summary_name).open("xb") as stream:
        stream.write(body)
    return project_summary(summary)


class _QuietParser(argparse.ArgumentParser):
    """Argument errors never echo the offending values (they may be paths or names)."""

    def error(self, message):
        print("参数错误（ARGUMENT_REJECTED）。运行 --help 查看用法。", file=sys.stderr)
        print(json.dumps({"status": "rejected", "error_code": "ARGUMENT_REJECTED"}))
        raise SystemExit(2)


def main(argv=None):
    parser = _QuietParser(
        description=__doc__,
        epilog=(
            "未传入 --local-only-ack 时拒绝运行且不写任何文件。"
            "本工具不接收、不保存解压密码。含文件名的输出仅限用户本机；"
            "对外只回传 summary.json（字段白名单：汇总数字与文件 SHA-256）。"
            "--images-dir 必须是 data/datasets/ 下以 agedb 为前缀的专用目录，"
            "不能是 data 或 data/datasets 本身。"
            "age_min/age_max、分位数和计数很小的格子在 568 人公开名人集上"
            "可能指认单人；本版本不抑制这些格子（small_cell_suppression_applied="
            "false）。是否抑制由用户决定，未选定规则前不要传 --suppress-small-cells。"
            "官方规模默认未做 P01 质检和感知近重复；精确重复为 0 不证明无泄漏。"
            "近重复方法、划分规则（70/15/15 无出处、未按年龄分层）和小格抑制均待用户决定，"
            "summary.json 用固定字段 pending_user_decisions 等如实标注“未做/待定”。"
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
    parser.add_argument(
        "--suppress-small-cells",
        action="store_true",
        help=(
            "保留开关，默认关闭（与当前行为一致，不抑制小格）。"
            "抑制规则尚未由用户选定；传入本参数会以 "
            "SMALL_CELL_SUPPRESSION_POLICY_UNSETTLED 拒绝，以免擅自选定规则。"
        ),
    )
    output_dir = None
    root = "."
    try:
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
        root = Path(args.root).absolute()
        output_dir = args.output_dir
        stages = tuple(part.strip() for part in args.stages.split(",") if part.strip())
        try:
            summary = run_pack(
                root,
                output_dir,
                archive=args.archive,
                images_dir=args.images_dir,
                terms_snapshot=args.terms_snapshot,
                stages=stages,
                split_seed=args.split_seed,
                suppress_small_cells=args.suppress_small_cells,
            )
        except Exception as error:
            code = error_code_of(error)
            _record_error(root, output_dir, code)
            print(json.dumps({"status": "rejected", "error_code": code, **acquisition.FLAGS}))
            return 2
        print(
            json.dumps(
                {
                    "status": summary["status"],
                    "output_dir": output_dir,
                    "stages_completed": summary["stages_completed"],
                    **acquisition.FLAGS,
                },
                ensure_ascii=False,
            )
        )
        return 0 if summary["status"] == "passed" else 1
    except SystemExit:
        raise
    except Exception as error:
        code = error_code_of(error)
        _record_error(root, output_dir, code)
        print(json.dumps({"status": "rejected", "error_code": code, **acquisition.FLAGS}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
