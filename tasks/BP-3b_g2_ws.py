#!/usr/bin/env python3
"""G2 /ws/frame 协议辅助客户端（BP-3b 附录 A，【建议】工具，不是仓库代码）。

只连接本机正式端点 ws://127.0.0.1:8000/ws/frame，按前端同样方式把图片编码为
最长边 640、质量 70 的 JPEG（与 services.ts 的 videoBlob(video, 640, 0.7) 对应）。
不保存任何图片字节、关键点坐标或旋转矩阵；输出只含计数、尺寸、哈希前 12 位、
结构检查结果、朝向向量与耗时。输出文件仍按照片派生物处理，不出本机。
数值容差 1e-4 为【建议】值，只判定 R 是否正交，不是姿态质量阈值。

依赖：backend 虚拟环境中的 Pillow 与 websockets（uvicorn[standard] 的依赖，
需要 websockets>=11 的同步客户端）。缺少时退出码 3，用例记为“阻塞”。
用法见 BP-3b §5 各用例；退出码 0 = 本子命令的 ok 为 true，1 = false，2 = 参数错误。
"""
import argparse, hashlib, io, json, math, os, sys, time

TOL = 1e-4
URL = "ws://127.0.0.1:8000/ws/frame"
ORIGIN = "http://127.0.0.1:4173"
FACE_KEYS = {"type", "seq", "ts", "bbox", "landmarks", "pose", "conf"}

try:
    from PIL import Image, ImageOps
    from websockets.sync.client import connect
    import websockets
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"ok": False, "blocked": f"缺少依赖：{exc!r}"}, ensure_ascii=False))
    sys.exit(3)


def jpeg(path, side=640, quality=70):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((side, side)) if max(im.size) > side else None
        if side > 640 and max(im.size) <= 640:  # 边长超限用例：放大到 side
            scale = side / max(im.size)
            im = im.resize((round(im.width * scale), round(im.height * scale)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue(), im.size


def png(path):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((640, 640))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue(), im.size


def close_code(ws, exc=None):
    for obj in (exc, ws):
        for attr in ("rcvd", "close_rcvd"):
            frame = getattr(obj, attr, None) if obj is not None else None
            if frame is not None and getattr(frame, "code", None) is not None:
                return frame.code
    return getattr(ws, "close_code", None) if ws is not None else None


def check_face(msg, size):
    c = {}
    c["keys_exact"] = set(msg) == FACE_KEYS
    c["no_shape_expr"] = "shape" not in msg and "expr" not in msg
    b = msg.get("bbox", [])
    c["bbox_in_frame"] = (len(b) == 4 and all(isinstance(v, (int, float)) for v in b) and b[0] >= 0 and b[1] >= 0
                          and b[2] > 0 and b[3] > 0 and b[0] + b[2] <= size[0] + 1e-3 and b[1] + b[3] <= size[1] + 1e-3)
    lm = msg.get("landmarks", [])
    c["landmarks_5_finite"] = len(lm) == 5 and all(len(p) == 2 and all(math.isfinite(v) and abs(v) <= 16384 for v in p) for p in lm)
    R = msg.get("pose", {}).get("R", [])
    t = msg.get("pose", {}).get("t", [])
    ok_r = len(R) == 9 and all(math.isfinite(v) for v in R)
    if ok_r:
        m = [R[0:3], R[3:6], R[6:9]]
        orth = max(abs(sum(m[k][i] * m[k][j] for k in range(3)) - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3))
        det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
               + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        c["RtR_eq_I"] = orth <= TOL
        c["det_eq_1"] = abs(det - 1) <= TOL
        forward = [round(R[2], 4), round(R[5], 4), round(R[8], 4)]  # R·(0,0,1)，行优先
    else:
        c["RtR_eq_I"] = c["det_eq_1"] = False
        forward = None
    c["t_zero"] = t == [0, 0, 0]
    conf = msg.get("conf")
    c["conf_0_1"] = isinstance(conf, (int, float)) and 0 <= conf <= 1
    return c, forward


def session(frames, origin, wait=8.0):
    """frames: [(label, bytes, size)]；逐帧发送并等待终结回复，遇关闭停止。"""
    rec = {"url": URL, "origin": origin, "websockets": websockets.__version__, "replies": [], "status": None,
           "close_code": None, "handshake_error": None}
    try:
        ws = connect(URL, origin=origin, compression=None, max_size=None, open_timeout=wait)
    except Exception as exc:  # noqa: BLE001
        rec["handshake_error"] = f"{type(exc).__name__}: {exc}"[:200]
        return rec
    with ws:
        try:
            first = ws.recv(timeout=wait)
            rec["status"] = json.loads(first)
            rec["status_bytes"] = len(first.encode("utf-8"))
            for label, data, size in frames:
                t0 = time.perf_counter()
                ws.send(data)
                while True:
                    raw = ws.recv(timeout=wait)
                    msg = json.loads(raw)
                    if msg.get("type") != "status":
                        break
                item = {"input": label, "sent_bytes": len(data), "sha12": hashlib.sha256(data).hexdigest()[:12],
                        "size": list(size) if size else None, "type": msg.get("type"), "seq": msg.get("seq"),
                        "code": msg.get("code"), "reply_bytes": len(raw.encode("utf-8")),
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
                if msg.get("type") == "face_state":
                    item["checks"], item["forward"] = check_face(msg, size)
                rec["replies"].append(item)
                if msg.get("type") == "error" and msg.get("code") not in {"NO_FACE", "MULTI_FACE", "BUSY"}:
                    break
            ws.close()
        except Exception as exc:  # noqa: BLE001
            rec["end"] = type(exc).__name__
        rec["close_code"] = close_code(ws)
    return rec


def burst(payloads, origin, text=False, wait=8.0):
    """不等回复连续发送，收集到关闭为止（流水违规、文本帧、超大帧）。"""
    rec = {"url": URL, "origin": origin, "messages": [], "close_code": None}
    ws = connect(URL, origin=origin, compression=None, max_size=None, open_timeout=wait)
    with ws:
        rec["status"] = json.loads(ws.recv(timeout=wait))
        for p in payloads:
            ws.send(p)
        try:
            while True:
                raw = ws.recv(timeout=wait)
                msg = json.loads(raw)
                rec["messages"].append({"type": msg.get("type"), "seq": msg.get("seq"), "code": msg.get("code"),
                                        "reply_bytes": len(raw.encode("utf-8"))})
        except Exception as exc:  # noqa: BLE001
            rec["end"] = type(exc).__name__
        rec["close_code"] = close_code(ws)
    return rec


def all_checks(rec):
    return all(all(r["checks"].values()) for r in rec["replies"] if "checks" in r)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=("probe", "pipeline", "text", "png", "side", "oversize", "origin", "drop"))
    ap.add_argument("images", nargs="*")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--origin", default=ORIGIN)
    ap.add_argument("--expect", default="", help="probe：逗号分隔的期望类型/错误码序列，如 face_state,NO_FACE,face_state")
    ap.add_argument("--expect-close", type=int, default=None)
    ap.add_argument("--recover-seconds", type=float, default=15.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.path.exists(a.out):
        print("输出文件已存在，不覆盖", file=sys.stderr); sys.exit(2)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if a.mode == "probe":
        frames = [(os.path.basename(p), *jpeg(p)) for _ in range(a.repeat) for p in a.images]
        rec = session(frames, a.origin)
        got = [r["type"] if r["type"] == "face_state" else r["code"] for r in rec["replies"]]
        seqs = [r["seq"] for r in rec["replies"]]
        rec["observed"] = got
        rec["seq_continuous_from_1"] = seqs == list(range(1, len(seqs) + 1))
        rec["all_replies_le_1024"] = all(r["reply_bytes"] <= 1024 for r in rec["replies"])
        rec["face_checks_ok"] = all_checks(rec)
        ok = rec["handshake_error"] is None and rec["seq_continuous_from_1"] and rec["all_replies_le_1024"] and rec["face_checks_ok"]
        if a.expect:
            ok = ok and got == a.expect.split(",")
        if a.expect_close is not None:
            ok = ok and rec["close_code"] == a.expect_close
        lat = [r["latency_ms"] for r in rec["replies"]]
        rec["latency_ms"] = {"first": lat[0] if lat else None, "rest_p50": sorted(lat[1:])[len(lat[1:]) // 2] if len(lat) > 1 else None,
                             "max": max(lat) if lat else None}
    elif a.mode == "pipeline":
        data, _ = jpeg(a.images[0])
        rec = burst([data, data], a.origin)
        got = [(m["seq"], m["code"]) for m in rec["messages"] if m["type"] != "status"]
        ok = got == [(1, "BUSY"), (2, "BUSY")] and rec["close_code"] == 1013
    elif a.mode == "text":
        rec = burst(["not a jpeg frame"], a.origin)
        got = [(m["seq"], m["code"]) for m in rec["messages"] if m["type"] != "status"]
        ok = got == [(1, "BAD_INPUT")] and rec["close_code"] == 1003
    elif a.mode == "png":
        data, _ = png(a.images[0])
        rec = burst([data], a.origin)
        got = [(m["seq"], m["code"]) for m in rec["messages"] if m["type"] != "status"]
        ok = got == [(1, "UNSUPPORTED_MEDIA_TYPE")] and rec["close_code"] == 1003
    elif a.mode == "side":
        data, size = jpeg(a.images[0], side=800)
        rec = burst([data], a.origin)
        rec["frame_size"] = list(size)
        got = [(m["seq"], m["code"]) for m in rec["messages"] if m["type"] != "status"]
        ok = max(size) > 640 and got == [(1, "INPUT_TOO_LARGE")] and rec["close_code"] == 1003
    elif a.mode == "oversize":
        data = b"\xff\xd8" + os.urandom(2 * 1024 * 1024 - 1)  # 2 MiB + 1 字节
        rec = burst([data], a.origin)
        rec["sent_bytes"] = len(data)
        ok = rec["close_code"] == 1009 and not [m for m in rec["messages"] if m["type"] != "status"]
    elif a.mode == "origin":
        rec = session([], a.origin)
        ok = rec["status"] is None  # 握手被拒或连接被 1008 关闭，均不得收到 status
    else:  # drop
        data, size = jpeg(a.images[0])
        ws = connect(URL, origin=a.origin, compression=None, max_size=None, open_timeout=8)
        ws.recv(timeout=8); ws.send(data); ws.close()
        rec = {"dropped_after_send": True, "attempts": []}
        t0 = time.monotonic()
        ok = False
        while time.monotonic() - t0 < a.recover_seconds:
            r = session([("recover", data, size)], a.origin)
            kind = r["replies"][0]["type"] if r["replies"] else r.get("handshake_error") or "none"
            code = r["replies"][0]["code"] if r["replies"] else None
            rec["attempts"].append({"t_s": round(time.monotonic() - t0, 2), "type": kind, "code": code})
            if kind == "face_state" and all_checks(r):
                ok = True; break
            time.sleep(0.5)
    rec.update({"mode": a.mode, "started": started, "ok": bool(ok)})
    with open(a.out, "x", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print(json.dumps({"mode": a.mode, "ok": bool(ok), "out": a.out}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
