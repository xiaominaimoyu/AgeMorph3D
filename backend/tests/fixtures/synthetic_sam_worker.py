"""Synthetic stdio child for lifecycle tests; no model, torch or GPU inference."""

import base64
import hashlib
import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path

configuration = Path(__file__).with_name("fake-sam-config.json")
config = json.loads(configuration.read_text()) if configuration.exists() else {}
identity = {"pid": os.getpid(), "load_count": 1, "research_only": True, "service_ready": False}


def send(value):
    data = json.dumps(value).encode()
    sys.stdout.buffer.write(struct.pack(">I", len(data)) + data)
    sys.stdout.buffer.flush()


def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def png(size):
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x70\x80\x90" * size) * size))
        + chunk(b"IEND", b"")
    )


send({"type": "hello", "pid": os.getpid(), "parent_pid": os.getppid()})
time.sleep(config.get("startup_delay", 0))
sys.stderr.buffer.write(b"x" * config.get("stderr_bytes", 0))
sys.stderr.buffer.flush()
if config.get("huge_startup"):
    sys.stdout.buffer.write(struct.pack(">I", 8 * 1024**2 + 1))
    sys.stdout.buffer.flush()
    time.sleep(60)
if config.get("startup_error"):
    send({"type": "startup_error", "code": "ASSET_LICENSE"})
    sys.exit(1)
send(
    {
        **identity,
        "type": "ready",
        "protocol_version": 1,
        "state": "research_loaded",
        "selftest": {"passed": not config.get("bad_selftest", False)},
    }
)
output = png(1024)
requests = 0
while True:
    prefix = sys.stdin.buffer.read(4)
    if not prefix:
        break
    length = struct.unpack(">I", prefix)[0]
    request = json.loads(sys.stdin.buffer.read(length))
    kind = request["type"]
    reply = {**identity, "type": kind + "_result", "id": request["id"]}
    if kind == "generate":
        requests += 1
        time.sleep(config.get("generate_delay", 0))
        if config.get("exit_generate"):
            sys.exit(3)
        if config.get("hang_generate"):
            time.sleep(60)
        if config.get("invalid_once") and requests == 1:
            send({**reply, "type": "error", "code": "INVALID_REQUEST", "fatal": False})
            continue
        if config.get("fatal_generate"):
            send({**reply, "type": "error", "code": "MODEL_INFERENCE_FAILED", "fatal": True})
            time.sleep(60)
        reply.update(
            png_b64=base64.b64encode(output).decode(),
            sha256=hashlib.sha256(output).hexdigest(),
            input_sha256=request["input_sha256"],
            target_age=request["target_age"],
            seconds=0.01,
            peak_vram_bytes=0,
        )
        if config.get("wrong_id"):
            reply["id"] = "unrelated-request"
        if config.get("bad_hash"):
            reply["sha256"] = "0" * 64
        if config.get("bad_png"):
            reply["png_b64"] = base64.b64encode(b"not-png").decode()
        if config.get("bad_seconds"):
            reply["seconds"] = True
        if config.get("bad_age"):
            reply["target_age"] = float(request["target_age"])
        if config.get("bad_frame"):
            send(["not-an-object"])
            continue
    send(reply)
    if kind == "shutdown":
        break
