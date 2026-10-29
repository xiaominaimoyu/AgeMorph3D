"""Direct-file acquisition against deterministic local HTTP; no dataset downloads."""

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resource_acquisition", ROOT / "preprocessing/resource_acquisition.py"
)
data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(data)
BODY = b"synthetic-resource-record\n" * 6000
RAW = "output/research/synthetic/raw"
WORK = "output/research/synthetic/work"
PLAN = "output/research/synthetic/plan.json"


def sha(body):
    return hashlib.sha256(body).hexdigest()


def write_plan(root, plan):
    path = root / PLAN
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(plan, indent=2) + "\n").encode()
    path.write_bytes(body)
    return sha(body)


@pytest.fixture
def server():
    state = {"requests": [], "mode": "normal", "mutation": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            mode = state["mode"]
            state["requests"].append(
                {
                    "path": self.path,
                    "range": self.headers.get("Range"),
                    "if_range": self.headers.get("If-Range"),
                    "encoding": self.headers.get("Accept-Encoding"),
                }
            )
            if state["mutation"]:
                state["mutation"]()
            if mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/not-followed")
                self.end_headers()
                return
            if mode == "http_error":
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"private response body must not enter receipt")
                return
            offset = (
                int(self.headers["Range"].split("=")[1].split("-")[0])
                if self.headers.get("Range")
                else 0
            )
            ranged = offset > 0 and mode != "range_ignored"
            payload = BODY[offset:] if ranged else BODY
            if mode == "corrupt":
                payload = b"X" + payload[1:]
            self.send_response(206 if ranged else 200)
            if mode != "no_length" and mode != "overflow":
                self.send_header(
                    "Content-Length", str(len(payload) + (1 if mode == "wrong_length" else 0))
                )
            if mode == "duplicate_length":
                self.send_header("Content-Length", str(len(payload)))
            if mode != "no_etag":
                etag = '"v2"' if mode == "changed_etag" else '"v1"'
                self.send_header("ETag", "W/" + etag if mode == "weak_etag" else etag)
            if mode == "gzip":
                self.send_header("Content-Encoding", "gzip")
            if ranged:
                start = offset + (1 if mode == "wrong_range" else 0)
                self.send_header("Content-Range", f"bytes {start}-{len(BODY) - 1}/{len(BODY)}")
            self.end_headers()
            try:
                if mode == "interrupt":
                    self.wfile.write(payload[: data.CHUNK_BYTES])
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                self.wfile.write(payload + (b"overflow" if mode == "overflow" else b""))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.02})
    thread.start()
    state["url"] = f"http://127.0.0.1:{http.server_port}/resource.bin"
    try:
        yield state
    finally:
        http.shutdown()
        thread.join(timeout=3)
        http.server_close()
        assert not thread.is_alive()


@pytest.fixture
def plan(tmp_path, server):
    evidence_name = "output/research/synthetic/purpose-and-entry.txt"
    evidence = tmp_path / evidence_name
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"Synthetic transport exercise only; no dataset or permission grant.\n")
    pin = {
        "path": evidence_name,
        "bytes": evidence.stat().st_size,
        "sha256": sha(evidence.read_bytes()),
    }
    return {
        "schema_id": data.SCHEMA,
        "plan_id": "synthetic-v1",
        "resource_id": "synthetic",
        "resource_version": "v1",
        "transport_scope": "synthetic_loopback",
        "purpose_evidence": pin,
        "entry_evidence": copy.deepcopy(pin),
        "max_total_bytes": len(BODY) * 3,
        "reserve_bytes": 0,
        "files": [
            {
                "file_id": "record-1",
                "url": server["url"],
                "path": "records/test.bin",
                "bytes": len(BODY),
                "sha256": sha(BODY),
            }
        ],
    }


@pytest.fixture(autouse=True)
def writable_cleanup(tmp_path):
    yield
    # Windows cannot remove read-only fixture files until their write bit is restored.
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


def run(root, plan, **kwargs):
    return data.acquire(root, PLAN, write_plan(root, plan), RAW, WORK, **kwargs)


def receipt(root, report):
    return json.loads((root / report["receipt"]).read_text(encoding="utf-8"))


def interrupt(root, plan, server):
    server["mode"] = "interrupt"
    report = run(root, plan)
    assert report["status"] == "failed"
    assert report["records"][0]["error_code"] == "INCOMPLETE_BODY"
    assert (root / WORK / "record-1.part").stat().st_size == data.CHUNK_BYTES
    assert not (root / RAW / plan["files"][0]["path"]).exists()
    return report


def test_download_publish_and_reuse_without_network(tmp_path, plan, server):
    result = run(tmp_path, plan)
    assert result["status"] == "passed" and result["summary"] == {
        "requested": 1,
        "downloaded": 1,
        "reused": 0,
        "failed": 0,
    }
    final = tmp_path / RAW / plan["files"][0]["path"]
    assert final.read_bytes() == BODY and not final.stat().st_mode & 0o222
    assert result["records"][0]["integrity_verified"]
    assert not (tmp_path / WORK / "record-1.part").exists()
    assert receipt(tmp_path, result)["summary"] == result["summary"]
    assert all(result[k] is False for k in data.FLAGS)
    assert result["permission_assessment"] == result["backend_entry_assessment"] == "not_performed"
    again = run(tmp_path, plan)
    assert again["records"][0]["status"] == "reused" and len(server["requests"]) == 1
    assert len(list((tmp_path / WORK).glob("attempt-*.json"))) == 2
    assert not (tmp_path / WORK / "active.lock").exists()


def test_interruption_resume_binds_range_etag_and_full_hash(tmp_path, plan, server):
    first = interrupt(tmp_path, plan, server)
    saved = (tmp_path / first["receipt"]).read_bytes()
    server["mode"] = "normal"
    second = run(tmp_path, plan)
    assert second["status"] == "passed"
    assert second["records"][0]["resumed_from_bytes"] == data.CHUNK_BYTES
    assert server["requests"][1]["range"] == f"bytes={data.CHUNK_BYTES}-"
    assert server["requests"][1]["if_range"] == '"v1"'
    assert server["requests"][1]["encoding"] == "identity"
    assert (tmp_path / first["receipt"]).read_bytes() == saved
    assert (tmp_path / RAW / plan["files"][0]["path"]).read_bytes() == BODY


@pytest.mark.parametrize(
    "mode,code",
    [
        ("wrong_length", "CONTENT_LENGTH_MISMATCH"),
        ("gzip", "ENCODED_RESPONSE_UNSUPPORTED"),
        ("duplicate_length", "DUPLICATE_HTTP_HEADER"),
        ("corrupt", "SHA256_MISMATCH"),
        ("redirect", "REDIRECT_UNSUPPORTED"),
        ("http_error", "HTTP_ERROR_403"),
        ("overflow", "BODY_SIZE_EXCEEDED"),
    ],
)
def test_http_and_integrity_failures_never_publish(tmp_path, plan, server, mode, code):
    server["mode"] = mode
    result = run(tmp_path, plan)
    assert result["summary"]["failed"] == 1
    assert result["records"][0]["error_code"] == code
    assert not (tmp_path / RAW / plan["files"][0]["path"]).exists()
    assert receipt(tmp_path, result)["status"] == "failed"
    assert "private response" not in json.dumps(result)
    assert len(server["requests"]) == 1


def test_missing_length_is_still_bounded_and_hash_verified(tmp_path, plan, server):
    server["mode"] = "no_length"
    assert run(tmp_path, plan)["status"] == "passed"


@pytest.mark.parametrize(
    "mode,code",
    [
        ("range_ignored", "UNEXPECTED_HTTP_STATUS"),
        ("changed_etag", "RESUME_ETAG_CHANGED"),
        ("wrong_range", "INVALID_CONTENT_RANGE"),
        ("corrupt", "SHA256_MISMATCH"),
    ],
)
def test_invalid_resume_responses_preserve_prefix(tmp_path, plan, server, mode, code):
    interrupt(tmp_path, plan, server)
    part = tmp_path / WORK / "record-1.part"
    prefix = part.read_bytes()
    server["mode"] = mode
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == code
    if mode != "corrupt":
        assert part.read_bytes() == prefix
    assert not (tmp_path / RAW / plan["files"][0]["path"]).exists()
    assert len(server["requests"]) == 2


@pytest.mark.parametrize("mode", ["no_etag", "weak_etag"])
def test_non_strong_etag_cannot_resume(tmp_path, plan, server, mode):
    # Simulate a previously interrupted prefix whose response had no strong validator.
    interrupt(tmp_path, plan, server)
    state_path = tmp_path / WORK / "record-1.state.json"
    state = json.loads(state_path.read_text())
    state["etag"] = None if mode == "no_etag" else 'W/"v1"'
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == "RESUME_REQUIRES_STRONG_ETAG"
    assert len(server["requests"]) == 1


def test_local_prefix_tamper_is_rejected_before_network(tmp_path, plan, server):
    interrupt(tmp_path, plan, server)
    part = tmp_path / WORK / "record-1.part"
    part.write_bytes(b"X" + part.read_bytes()[1:])
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == "RESUME_PREFIX_CHANGED"
    assert len(server["requests"]) == 1


def test_changed_plan_cannot_reuse_old_partial(tmp_path, plan, server):
    interrupt(tmp_path, plan, server)
    plan["resource_version"] = "v2"
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == "RESUME_PLAN_CHANGED"
    assert len(server["requests"]) == 1


def test_existing_raw_mismatch_is_preserved(tmp_path, plan, server):
    final = tmp_path / RAW / plan["files"][0]["path"]
    final.parent.mkdir(parents=True)
    final.write_bytes(b"old")
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == "EXISTING_FILE_MISMATCH"
    assert final.read_bytes() == b"old" and not server["requests"]


def test_existing_matching_but_writable_raw_not_silently_changed(tmp_path, plan, server):
    final = tmp_path / RAW / plan["files"][0]["path"]
    final.parent.mkdir(parents=True)
    final.write_bytes(BODY)
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == "EXISTING_FILE_NOT_READ_ONLY"
    assert final.stat().st_mode & 0o222 and not server["requests"]


def test_complete_candidate_can_publish_without_network(tmp_path, plan, server):
    server["mode"] = "corrupt"
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == "SHA256_MISMATCH"
    part = tmp_path / WORK / "record-1.part"
    part.write_bytes(BODY)
    state_path = tmp_path / WORK / "record-1.state.json"
    state = json.loads(state_path.read_text())
    state["prefix_sha256"] = sha(BODY)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert run(tmp_path, plan)["status"] == "passed"
    assert len(server["requests"]) == 1


def test_complete_failure_denominator_continues_to_next_file(tmp_path, plan, server):
    plan["files"][0]["sha256"] = "0" * 64
    plan["files"].append(
        {**plan["files"][0], "file_id": "record-2", "path": "records/ok.bin", "sha256": sha(BODY)}
    )
    result = run(tmp_path, plan)
    assert result["summary"] == {"requested": 2, "downloaded": 1, "reused": 0, "failed": 1}
    assert [r["status"] for r in result["records"]] == ["failed", "downloaded"]
    assert len(server["requests"]) == 2


def test_low_disk_space_retains_every_requested_failure(tmp_path, plan, server, monkeypatch):
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        data.shutil, "disk_usage", lambda _: type(usage)(usage.total, usage.used, 0)
    )
    result = run(tmp_path, plan)
    assert result["summary"]["failed"] == 1
    assert result["records"][0]["error_code"] == "INSUFFICIENT_SPACE" and not server["requests"]


def test_lock_is_not_stolen_or_deleted(tmp_path, plan, server):
    lock = tmp_path / WORK / "active.lock"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(b"another writer")
    with pytest.raises(data.AcquisitionError, match="WORK_DIRECTORY_LOCKED"):
        run(tmp_path, plan)
    assert lock.read_bytes() == b"another writer" and not server["requests"]


def test_pin_change_during_response_rejects_publication(tmp_path, plan, server):
    evidence = tmp_path / plan["purpose_evidence"]["path"]
    server["mutation"] = lambda: evidence.write_bytes(b"changed")
    result = run(tmp_path, plan)
    assert not result["inputs_stable"]
    assert result["records"][0]["error_code"] == "INPUT_PIN_CHANGED"
    assert not (tmp_path / RAW / plan["files"][0]["path"]).exists()
    assert receipt(tmp_path, result)["status"] == "failed"


def test_elapsed_deadline_keeps_failure_receipt(tmp_path, plan, server, monkeypatch):
    clock = {"now": 0}
    monkeypatch.setattr(data, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    server["mutation"] = lambda: clock.update(now=301)
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == "DEADLINE_EXCEEDED"
    assert not (tmp_path / RAW / plan["files"][0]["path"]).exists()
    assert receipt(tmp_path, result)["summary"]["failed"] == 1


@pytest.mark.parametrize(
    "bad",
    [
        "../escape",
        "/escape",
        "a/../b",
        "a//b",
        "a\\b",
        "C:/x",
        ".",
        "",
        "a.",
        "a ",
        "CON.txt",
        "x/NUL",
        "x\x00y",
        "a?b",
        "a|b",
    ],
)
def test_noncanonical_or_windows_reserved_file_paths_rejected(plan, bad):
    plan["files"][0]["path"] = bad
    with pytest.raises(data.AcquisitionError):
        data.validate_plan(plan)


@pytest.mark.parametrize(
    "key,value",
    [
        ("bytes", True),
        ("bytes", 0),
        ("bytes", None),
        ("bytes", data.MAX_TOTAL_BYTES + 1),
        ("sha256", "X" * 64),
        ("sha256", None),
        ("file_id", "../escape"),
        ("url", "http://example.com/file"),
        ("url", "http://localhost/file"),
        ("url", "http://127.0.0.1/file?token=private"),
        ("url", "http://user:password@127.0.0.1/file"),
        ("url", "file:///tmp/data"),
        ("url", "http://127.0.0.1/file#fragment"),
    ],
)
def test_invalid_file_metadata_rejected(plan, key, value):
    plan["files"][0][key] = value
    with pytest.raises(data.AcquisitionError):
        data.validate_plan(plan)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_id",
        "case_path",
        "nested_path",
        "too_many",
        "empty",
        "over_budget",
        "bad_scope",
        "extra_field",
    ],
)
def test_plan_shape_count_budget_and_collision_guards(plan, change):
    second = {**plan["files"][0], "file_id": "second", "path": "records/second.bin"}
    if change == "duplicate_id":
        second["file_id"] = "RECORD-1"
    elif change == "case_path":
        second["path"] = "RECORDS/TEST.BIN"
    elif change == "nested_path":
        second["path"] = "records/test.bin/nested"
    if change in {"duplicate_id", "case_path", "nested_path"}:
        plan["files"].append(second)
    elif change == "too_many":
        plan["files"] *= 33
    elif change == "empty":
        plan["files"] = []
    elif change == "over_budget":
        plan["max_total_bytes"] = 1
    elif change == "bad_scope":
        plan["transport_scope"] = []
    elif change == "extra_field":
        plan["ready"] = True
    with pytest.raises(data.AcquisitionError):
        data.validate_plan(plan)


def test_https_scope_rejects_http_and_accepts_direct_url_metadata_only(plan):
    plan["transport_scope"] = "https_direct"
    with pytest.raises(data.AcquisitionError, match="REAL_SOURCE_REQUIRES_HTTPS"):
        data.validate_plan(plan)
    plan["files"][0]["url"] = "https://example.org/never-requested.bin"
    data.validate_plan(plan)


@pytest.mark.parametrize(
    "which", ["plan_hash", "evidence_hash", "duplicate_json", "oversized_json", "catalog"]
)
def test_invalid_pinned_inputs_rejected_before_directory_or_network(tmp_path, plan, server, which):
    expected = write_plan(tmp_path, plan)
    if which == "plan_hash":
        expected = "0" * 64
    elif which == "evidence_hash":
        (tmp_path / plan["entry_evidence"]["path"]).write_bytes(b"changed")
    elif which == "duplicate_json":
        body = b'{"schema_id":1,"schema_id":2}'
        (tmp_path / PLAN).write_bytes(body)
        expected = sha(body)
    elif which == "oversized_json":
        body = b" " * (data.MAX_JSON_BYTES + 1)
        (tmp_path / PLAN).write_bytes(body)
        expected = sha(body)
    else:
        body = (ROOT / "docs/data-resources-v1.json").read_bytes()
        (tmp_path / PLAN).write_bytes(body)
        expected = sha(body)
    with pytest.raises(data.AcquisitionError):
        data.acquire(tmp_path, PLAN, expected, RAW, WORK)
    assert not (tmp_path / WORK).exists() and not server["requests"]


@pytest.mark.parametrize(
    "raw,work",
    [
        ("docs/raw", WORK),
        (RAW, "docs/work"),
        (RAW, RAW),
        (RAW, RAW + "/nested"),
        ("data/datasets/synthetic", WORK),
        (RAW, "../escape"),
    ],
)
def test_output_scope_guards(tmp_path, plan, server, raw, work):
    with pytest.raises(data.AcquisitionError):
        data.acquire(tmp_path, PLAN, write_plan(tmp_path, plan), raw, work)
    assert not server["requests"]


def test_reparse_path_rejected_without_symlink_privileges(tmp_path, plan, server, monkeypatch):
    target = tmp_path / "output/research/synthetic"
    original = Path.lstat

    def marked(path):
        info = original(path)
        if path == target:

            class Reparse:
                st_mode = info.st_mode
                st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT

            return Reparse()
        return info

    expected = write_plan(tmp_path, plan)
    monkeypatch.setattr(Path, "lstat", marked)
    with pytest.raises(data.AcquisitionError, match="LINK_OR_REPARSE_PATH"):
        data.acquire(tmp_path, PLAN, expected, RAW, WORK)
    assert not server["requests"]


def test_hardlinked_partial_not_appended(tmp_path, plan, server):
    interrupt(tmp_path, plan, server)
    part = tmp_path / WORK / "record-1.part"
    outside = tmp_path / "protected"
    os.link(part, outside)
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == "LINKED_PART_FILE"
    assert outside.read_bytes() == BODY[: data.CHUNK_BYTES] and len(server["requests"]) == 1


@pytest.mark.parametrize(
    "bad,code",
    [
        (None, "INVALID_RESUME_STATE"),
        ([], "INVALID_RESUME_STATE"),
        (3, "RESUME_PREFIX_CHANGED"),
        (True, "INVALID_RESUME_STATE"),
    ],
)
def test_corrupt_resume_state_is_reported_not_uncaught(tmp_path, plan, server, bad, code):
    interrupt(tmp_path, plan, server)
    path = tmp_path / WORK / "record-1.state.json"
    value = json.loads(path.read_text())
    value["bytes"] = bad
    path.write_text(json.dumps(value), encoding="utf-8")
    result = run(tmp_path, plan)
    assert result["records"][0]["error_code"] == code
    assert len(server["requests"]) == 1


def test_cli_success_failure_and_rejected_input(tmp_path, plan, server):
    def cli(expected):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "preprocessing.resource_acquisition",
                "--root",
                str(tmp_path),
                "--plan",
                PLAN,
                "--plan-sha256",
                expected,
                "--raw-dir",
                RAW,
                "--work-dir",
                WORK,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )

    expected = write_plan(tmp_path, plan)
    bad = cli("0" * 64)
    assert bad.returncode == 2 and json.loads(bad.stdout)["status"] == "rejected"
    server["mode"] = "interrupt"
    failed = cli(expected)
    assert failed.returncode == 1 and json.loads(failed.stdout)["summary"]["failed"] == 1
    server["mode"] = "normal"
    success = cli(expected)
    assert success.returncode == 0 and json.loads(success.stdout)["status"] == "passed"
    assert not bad.stderr and not failed.stderr and not success.stderr
