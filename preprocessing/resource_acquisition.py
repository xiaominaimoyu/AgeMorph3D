"""Bounded direct-file acquisition; integrity is not permission or data readiness.

CLI: python -m preprocessing.resource_acquisition --help
Only synthetic loopback transfers are exercised in the initial D06 batch.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

SCHEMA = "agemorph3d-resource-acquisition-v1"
MAX_JSON_BYTES = 128 * 1024
MAX_EVIDENCE_BYTES = 16 * 1024**2
MAX_TOTAL_BYTES = 64 * 1024**3
MAX_FILES = 32
CHUNK_BYTES = 64 * 1024
PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FLAGS = dict.fromkeys(
    (
        "formal_dataset_ready",
        "training_authorized",
        "independent_evaluation",
        "service_ready",
        "production_enabled",
        "g3_complete",
    ),
    False,
)


class AcquisitionError(ValueError):
    """A stable error code without remote response bodies or credentials."""


def _require(condition, code):
    if not condition:
        raise AcquisitionError(code)


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys), "INVALID_FIELDS")


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _identifier(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value)


def _relative(name):
    _require(type(name) is str and 0 < len(name) <= 240, "INVALID_PATH")
    path = PurePosixPath(name)
    _require(
        bool(path.parts)
        and not path.is_absolute()
        and path.as_posix() == name
        and not set('<>:"\\|?*') & set(name)
        and all(ord(c) >= 32 for c in name)
        and not {".", ".."} & set(path.parts),
        "INVALID_PATH",
    )
    for part in path.parts:
        _require(
            not part.endswith((".", " "))
            and len(part) <= 120
            and not re.fullmatch(r"(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".")[0]),
            "INVALID_PATH",
        )
    return path


def _safe(root, name):
    relative = _relative(name)
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        if current.exists() or current.is_symlink():
            meta = current.lstat()
            _require(
                not stat.S_ISLNK(meta.st_mode)
                and not getattr(meta, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                "LINK_OR_REPARSE_PATH",
            )
    _require(current.resolve().is_relative_to(root), "EXTERNAL_PATH")
    return current


def _read(path, limit):
    _require(path.is_file() and path.stat().st_size <= limit, "INPUT_NOT_BOUNDED_FILE")
    with path.open("rb") as stream:
        body = stream.read(limit + 1)
    _require(len(body) <= limit, "INPUT_TOO_LARGE")
    return body


def _json(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    try:
        return json.loads(body.decode("utf-8-sig"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise AcquisitionError("INVALID_JSON") from error


def _encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def _url(value, scope):
    _require(type(value) is str and len(value) <= 2048, "INVALID_URL")
    _require(all(33 <= ord(c) <= 126 for c in value), "INVALID_URL")
    try:
        parsed = urlsplit(value)
        _require(parsed.hostname and parsed.port != 0, "INVALID_URL")
    except ValueError as error:
        raise AcquisitionError("INVALID_URL") from error
    _require(
        parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and "\\" not in value,
        "URL_AUTH_QUERY_OR_FRAGMENT_UNSUPPORTED",
    )
    if scope == "synthetic_loopback":
        _require(
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"},
            "SYNTHETIC_REQUIRES_LITERAL_LOOPBACK_HTTP",
        )
    else:
        _require(parsed.scheme == "https", "REAL_SOURCE_REQUIRES_HTTPS")


def validate_plan(plan):
    """Validate acquisition metadata, not legal eligibility or backend exits."""
    _keys(
        plan,
        (
            "schema_id",
            "plan_id",
            "resource_id",
            "resource_version",
            "transport_scope",
            "purpose_evidence",
            "entry_evidence",
            "max_total_bytes",
            "reserve_bytes",
            "files",
        ),
    )
    _require(plan["schema_id"] == SCHEMA, "INVALID_SCHEMA")
    _require(
        all(_identifier(plan[k]) for k in ("plan_id", "resource_id", "resource_version")),
        "INVALID_IDENTIFIER",
    )
    _require(
        type(plan["transport_scope"]) is str
        and plan["transport_scope"] in {"synthetic_loopback", "https_direct"},
        "INVALID_SCOPE",
    )
    _require(
        _integer(plan["max_total_bytes"], 1, MAX_TOTAL_BYTES)
        and _integer(plan["reserve_bytes"], 0, MAX_TOTAL_BYTES),
        "INVALID_BUDGET",
    )
    for key in ("purpose_evidence", "entry_evidence"):
        pin = plan[key]
        _keys(pin, ("path", "bytes", "sha256"))
        _relative(pin["path"])
        _require(
            _integer(pin["bytes"], 1, MAX_EVIDENCE_BYTES) and _sha(pin["sha256"]),
            "INVALID_EVIDENCE_PIN",
        )
    _require(
        type(plan["files"]) is list and 1 <= len(plan["files"]) <= MAX_FILES, "INVALID_FILE_COUNT"
    )
    paths, ids = [], set()
    for item in plan["files"]:
        _keys(item, ("file_id", "url", "path", "bytes", "sha256"))
        _require(
            _identifier(item["file_id"]) and item["file_id"].casefold() not in ids,
            "INVALID_OR_DUPLICATE_FILE_ID",
        )
        ids.add(item["file_id"].casefold())
        path = _relative(item["path"]).as_posix().casefold()
        _require(
            not any(
                path == p or path.startswith(p + "/") or p.startswith(path + "/") for p in paths
            ),
            "DUPLICATE_OR_OVERLAPPING_FILE_PATH",
        )
        paths.append(path)
        _require(
            _integer(item["bytes"], 1, MAX_TOTAL_BYTES) and _sha(item["sha256"]), "INVALID_FILE_PIN"
        )
        _url(item["url"], plan["transport_scope"])
    _require(sum(f["bytes"] for f in plan["files"]) <= plan["max_total_bytes"], "BUDGET_EXCEEDED")


def _hash_file(path, maximum):
    _require(path.is_file() and path.stat().st_size <= maximum, "FILE_SIZE_EXCEEDED")
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(min(CHUNK_BYTES, maximum - count + 1)):
            count += len(chunk)
            _require(count <= maximum, "FILE_SIZE_EXCEEDED")
            digest.update(chunk)
    return count, digest


def _atomic_state(root, name, value):
    path = _safe(root, name)
    temp_name = name + ".tmp"
    temp = _safe(root, temp_name)
    with temp.open("xb") as stream:
        stream.write(_encoded(value))
    os.replace(temp, path)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AcquisitionError("REDIRECT_UNSUPPORTED")


def _header(headers, name):
    values = headers.get_all(name, [])
    _require(len(values) <= 1, "DUPLICATE_HTTP_HEADER")
    return values[0].strip() if values else None


def _strong_etag(value):
    return (
        value if type(value) is str and re.fullmatch(r'"[\x21\x23-\x7e]{0,254}"', value) else None
    )


def _acquire_one(root, item, raw_name, work_name, binding, timeout, deadline, pins_stable):
    final_name = raw_name + "/" + item["path"]
    part_name = work_name + "/" + item["file_id"] + ".part"
    state_name = work_name + "/" + item["file_id"] + ".state.json"
    row = {
        "file_id": item["file_id"],
        "path": final_name,
        "expected_bytes": item["bytes"],
        "expected_sha256": item["sha256"],
        "status": "failed",
        "error_code": None,
        "resumed_from_bytes": 0,
        "network_body_bytes_read": 0,
        "integrity_verified": False,
        "published_read_only": False,
    }
    try:
        _require(pins_stable(), "INPUT_PIN_CHANGED")
        final = _safe(root, final_name)
        part, state = _safe(root, part_name), _safe(root, state_name)
        if final.exists():
            count, hashed = _hash_file(final, item["bytes"])
            _require(
                count == item["bytes"] and hashed.hexdigest() == item["sha256"],
                "EXISTING_FILE_MISMATCH",
            )
            _require(not final.stat().st_mode & 0o222, "EXISTING_FILE_NOT_READ_ONLY")
            _require(pins_stable(), "INPUT_PIN_CHANGED")
            row.update(status="reused", integrity_verified=True, published_read_only=True)
            return row
        _require(part.exists() == state.exists(), "INCOMPLETE_RESUME_STATE")
        offset, hashed, etag = 0, hashlib.sha256(), None
        if part.exists():
            _require(part.stat().st_nlink == 1, "LINKED_PART_FILE")
            old = _json(_read(state, MAX_JSON_BYTES))
            _keys(old, ("binding", "bytes", "prefix_sha256", "etag"))
            _require(old["binding"] == binding, "RESUME_PLAN_CHANGED")
            _require(
                _integer(old["bytes"], 0, item["bytes"])
                and _sha(old["prefix_sha256"])
                and (old["etag"] is None or type(old["etag"]) is str),
                "INVALID_RESUME_STATE",
            )
            offset, hashed = _hash_file(part, item["bytes"])
            _require(
                old["bytes"] == offset and old["prefix_sha256"] == hashed.hexdigest(),
                "RESUME_PREFIX_CHANGED",
            )
            etag = _strong_etag(old["etag"])
            if offset < item["bytes"]:
                _require(etag is not None, "RESUME_REQUIRES_STRONG_ETAG")
        row["resumed_from_bytes"] = offset
        if offset < item["bytes"]:
            headers = {"Accept-Encoding": "identity", "User-Agent": "AgeMorph3D-acquisition/1"}
            if offset:
                headers.update({"Range": f"bytes={offset}-", "If-Range": etag})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            request = urllib.request.Request(item["url"], headers=headers)
            _require(time.monotonic() < deadline, "DEADLINE_EXCEEDED")
            with opener.open(request, timeout=timeout) as response:
                code = response.status
                _require(code == (206 if offset else 200), "UNEXPECTED_HTTP_STATUS")
                encoding = _header(response.headers, "Content-Encoding")
                _require(encoding in {None, "identity"}, "ENCODED_RESPONSE_UNSUPPORTED")
                response_etag = _strong_etag(_header(response.headers, "ETag"))
                if offset:
                    _require(response_etag == etag, "RESUME_ETAG_CHANGED")
                    expected_range = f"bytes {offset}-{item['bytes'] - 1}/{item['bytes']}"
                    _require(
                        _header(response.headers, "Content-Range") == expected_range,
                        "INVALID_CONTENT_RANGE",
                    )
                else:
                    _require(
                        _header(response.headers, "Content-Range") is None,
                        "UNEXPECTED_CONTENT_RANGE",
                    )
                length = _header(response.headers, "Content-Length")
                _require(
                    length is None or length == str(item["bytes"] - offset),
                    "CONTENT_LENGTH_MISMATCH",
                )
                etag = response_etag
                _safe(root, final_name)
                final.parent.mkdir(parents=True, exist_ok=True)
                _safe(root, part_name)
                with part.open("ab" if offset else "xb") as stream:

                    def checkpoint():
                        _atomic_state(
                            root,
                            state_name,
                            {
                                "binding": binding,
                                "bytes": offset,
                                "prefix_sha256": hashed.hexdigest(),
                                "etag": etag,
                            },
                        )

                    checkpoint()
                    try:
                        while True:
                            _require(time.monotonic() < deadline, "DEADLINE_EXCEEDED")
                            chunk = response.read1(min(CHUNK_BYTES, item["bytes"] - offset + 1))
                            row["network_body_bytes_read"] += len(chunk)
                            if not chunk:
                                break
                            _require(offset + len(chunk) <= item["bytes"], "BODY_SIZE_EXCEEDED")
                            stream.write(chunk)
                            stream.flush()
                            hashed.update(chunk)
                            offset += len(chunk)
                            checkpoint()
                    finally:
                        checkpoint()
            _require(offset == item["bytes"], "INCOMPLETE_BODY")
        _require(
            offset == item["bytes"] and hashed.hexdigest() == item["sha256"], "SHA256_MISMATCH"
        )
        # Re-read the complete candidate before publication, including resumed bytes.
        count, full_hash = _hash_file(part, item["bytes"])
        _require(
            count == item["bytes"] and full_hash.hexdigest() == item["sha256"],
            "FINAL_INTEGRITY_MISMATCH",
        )
        _safe(root, final_name)
        _safe(root, part_name)
        _require(pins_stable(), "INPUT_PIN_CHANGED")
        os.link(part, final)  # Atomic create; never replace an existing raw file.
        part.unlink()
        final.chmod(final.stat().st_mode & ~0o222)
        _require(not final.stat().st_mode & 0o222, "READ_ONLY_PUBLICATION_FAILED")
        row.update(status="downloaded", integrity_verified=True, published_read_only=True)
    except AcquisitionError as error:
        row["error_code"] = str(error)
    except urllib.error.HTTPError as error:
        row["error_code"] = "HTTP_ERROR_" + str(error.code)
        error.close()
    except (OSError, urllib.error.URLError, http.client.HTTPException):
        row["error_code"] = "IO_OR_TRANSPORT_ERROR"
    return row


def acquire(
    root, plan_name, expected_sha256, raw_dir, work_dir, *, timeout=10, deadline_seconds=120
):
    """Execute a pinned direct-file plan; records do not certify their own purposes."""
    _require(
        type(timeout) in (int, float)
        and 0 < timeout <= 30
        and type(deadline_seconds) in (int, float)
        and 0 < deadline_seconds <= 300,
        "INVALID_TIMEOUT",
    )
    root = Path(root).absolute()
    _require(root.is_dir() and not root.is_symlink() and root == root.resolve(), "INVALID_ROOT")
    _require(_sha(expected_sha256), "INVALID_PLAN_SHA256")
    body = _read(_safe(root, plan_name), MAX_JSON_BYTES)
    _require(hashlib.sha256(body).hexdigest() == expected_sha256, "PLAN_SHA256_MISMATCH")
    plan = _json(body)
    validate_plan(plan)
    pinned_inputs = [(plan_name, len(body), expected_sha256, MAX_JSON_BYTES)]
    for key in ("purpose_evidence", "entry_evidence"):
        pin = plan[key]
        evidence = _read(_safe(root, pin["path"]), MAX_EVIDENCE_BYTES)
        _require(
            len(evidence) == pin["bytes"] and hashlib.sha256(evidence).hexdigest() == pin["sha256"],
            "EVIDENCE_PIN_MISMATCH",
        )
        pinned_inputs.append((pin["path"], pin["bytes"], pin["sha256"], MAX_EVIDENCE_BYTES))

    def pins_stable():
        for name, size, sha256, maximum in pinned_inputs:
            current = _read(_safe(root, name), maximum)
            if len(current) != size or hashlib.sha256(current).hexdigest() != sha256:
                return False
        return True

    raw, work = _safe(root, raw_dir), _safe(root, work_dir)
    prefix = (
        "output/research/" if plan["transport_scope"] == "synthetic_loopback" else "data/datasets/"
    )
    _require(
        raw_dir.startswith(prefix) and work_dir.startswith("output/research/"),
        "OUTPUT_OUTSIDE_IGNORED_ROOT",
    )
    _require(not raw.is_relative_to(work) and not work.is_relative_to(raw), "RAW_WORK_OVERLAP")
    for item in plan["files"]:
        _safe(root, raw_dir + "/" + item["path"])
    work.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_id": SCHEMA,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "producer_sha256": PRODUCER_SHA256,
        "python": sys.version.split()[0],
        "plan_path": plan_name,
        "plan_sha256": expected_sha256,
        "plan_id": plan["plan_id"],
        "transport_scope": plan["transport_scope"],
        "status": "failed",
        "records": [],
        "evidence_pins_verified": True,
        "permission_assessment": "not_performed",
        "backend_entry_assessment": "not_performed",
        **FLAGS,
    }
    lock = _safe(root, work_dir + "/active.lock")
    # One writer per work directory. A stale lock requires explicit inspection.
    try:
        with lock.open("xb") as stream:
            stream.write(str(os.getpid()).encode())
    except FileExistsError as error:
        raise AcquisitionError("WORK_DIRECTORY_LOCKED") from error
    try:
        deadline = time.monotonic() + deadline_seconds
        binding = hashlib.sha256(
            _encoded({"plan_sha256": expected_sha256, "raw_dir": raw_dir})
        ).hexdigest()
        required = sum(f["bytes"] for f in plan["files"]) + plan["reserve_bytes"]
        space_ok = shutil.disk_usage(work).free >= required
        for item in plan["files"]:
            if not space_ok and not _safe(root, raw_dir + "/" + item["path"]).exists():
                row = {
                    "file_id": item["file_id"],
                    "path": raw_dir + "/" + item["path"],
                    "expected_bytes": item["bytes"],
                    "expected_sha256": item["sha256"],
                    "status": "failed",
                    "error_code": "INSUFFICIENT_SPACE",
                    "integrity_verified": False,
                    "published_read_only": False,
                    "resumed_from_bytes": 0,
                    "network_body_bytes_read": 0,
                }
            else:
                row = _acquire_one(
                    root, item, raw_dir, work_dir, binding, timeout, deadline, pins_stable
                )
            report["records"].append(row)
        report["summary"] = {
            "requested": len(plan["files"]),
            "downloaded": sum(r["status"] == "downloaded" for r in report["records"]),
            "reused": sum(r["status"] == "reused" for r in report["records"]),
            "failed": sum(r["status"] == "failed" for r in report["records"]),
        }
        try:
            report["inputs_stable"] = pins_stable()
        except (AcquisitionError, OSError):
            report["inputs_stable"] = False
        report["status"] = (
            "passed" if report["summary"]["failed"] == 0 and report["inputs_stable"] else "failed"
        )
        report_name = work_dir + "/attempt-" + uuid.uuid4().hex + ".json"
        with _safe(root, report_name).open("xb") as stream:
            stream.write(_encoded(report))
        return {**report, "receipt": report_name}
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = acquire(args.root, args.plan, args.plan_sha256, args.raw_dir, args.work_dir)
    except (AcquisitionError, OSError) as error:
        code = str(error) if isinstance(error, AcquisitionError) else "LOCAL_IO_ERROR"
        print(json.dumps({"status": "rejected", "error_code": code, **FLAGS}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
