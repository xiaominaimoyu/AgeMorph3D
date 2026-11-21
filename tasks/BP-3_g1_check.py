#!/usr/bin/env python3
r"""BP-3 G1 本机辅助检查（只读，仅标准库）。不属于仓库；放在被忽略的 output/g1/tools/ 下运行。

用法（项目根目录，Windows PowerShell）：
  backend\.venv\Scripts\python.exe output\g1\tools\g1_check.py resp  <reconstruct响应.json> [--source-age unknown|<数值>]
  backend\.venv\Scripts\python.exe output\g1\tools\g1_check.py glb   <文件.glb> [--kind service|viewer] [--response <响应.json>]
  backend\.venv\Scripts\python.exe output\g1\tools\g1_check.py angle <响应A.json> <响应B.json>
  backend\.venv\Scripts\python.exe output\g1\tools\g1_check.py distinct <a.glb> <b.glb> [...]
输出一行 JSON；退出码 0 = 本项检查全部满足，1 = 有不满足项，2 = 用法或文件错误。
数值容差 1e-4 为【建议】值，仓库没有规定；它只用于判定 R 是否正交，不是质量阈值。
"""
import hashlib, json, math, re, struct, sys

TOPOLOGY_ID = "tddfa-bfm-canon-v1-cc449ed7efa2860bed64be0a7e29ad8944912148c69f938ff768c8766d65e7cb"
VERTICES, FACES = 38365, 76073
AGE_KEYS = ("age", "ageAnchors", "displayAge", "texture_age")
TOL = 1e-4


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_glb(path):
    data = open(path, "rb").read()
    if len(data) < 28 or data[:4] != b"glTF":
        raise ValueError("不是 GLB（缺少 glTF 魔数）")
    version, length = struct.unpack_from("<II", data, 4)
    jlen, jtype = struct.unpack_from("<II", data, 12)
    if version != 2 or length != len(data) or jtype != 0x4E4F534A:
        raise ValueError("GLB 头不合法")
    doc = json.loads(data[20:20 + jlen].decode("utf-8"))
    off = 20 + jlen
    binary = b""
    if off + 8 <= len(data):
        blen, btype = struct.unpack_from("<II", data, off)
        if btype == 0x004E4942:
            binary = data[off + 8: off + 8 + blen]
    return data, doc, binary


def positions(doc, binary):
    out = []
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            acc = doc["accessors"][prim["attributes"]["POSITION"]]
            view = doc["bufferViews"][acc["bufferView"]]
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = view.get("byteStride", 12)
            for i in range(acc["count"]):
                out.append(struct.unpack_from("<fff", binary, start + i * stride))
    return out


def rot(resp):
    R = resp["pose"]["R"]
    return [R[0:3], R[3:6], R[6:9]]


def det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def check_resp(path, source_age):
    r = json.load(open(path, encoding="utf-8"))
    c = {}
    c["keys"] = {"mesh_id", "topology_id", "asset_mode", "capabilities", "source_age",
                 "shape", "expr", "pose"} <= set(r)
    c["mesh_id_32hex"] = bool(re.fullmatch(r"[0-9a-f]{32}", str(r.get("mesh_id", ""))))
    c["topology_id"] = r.get("topology_id") == TOPOLOGY_ID
    c["asset_mode_static"] = r.get("asset_mode") == "static"
    c["capabilities_false"] = r.get("capabilities") == {"age_morph": False, "age_texture": False}
    c["texture_url_null"] = r.get("texture_url") is None
    c["shape_40"] = len(r.get("shape", [])) == 40
    c["expr_10"] = len(r.get("expr", [])) == 10
    c["t_zero"] = r.get("pose", {}).get("t") == [0, 0, 0]
    R = rot(r)
    rtr = [[sum(R[k][i] * R[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    orth = max(abs(rtr[i][j] - (1 if i == j else 0)) for i in range(3) for j in range(3))
    d = det3(R)
    c["RtR_eq_I"] = orth <= TOL
    c["det_eq_1"] = abs(d - 1) <= TOL
    sa = r.get("source_age", {})
    if source_age == "unknown":
        c["source_age"] = sa == {"value": None, "method": "unknown", "calibration_id": None}
    elif source_age is not None:
        c["source_age"] = (sa.get("method") == "user" and sa.get("calibration_id") is None
                           and abs(float(sa.get("value")) - float(source_age)) < 1e-9)
    angle = math.degrees(math.acos(max(-1, min(1, (R[0][0] + R[1][1] + R[2][2] - 1) / 2))))
    return c, {"file": path, "sha256": sha256(path), "mesh_id": r.get("mesh_id"),
               "RtR_max_abs_error": orth, "det_R": d, "angle_from_identity_deg": angle}


def check_glb(path, kind, response):
    data, doc, binary = load_glb(path)
    c = {}
    c["single_embedded_buffer"] = len(doc.get("buffers", [])) == 1 and "uri" not in doc["buffers"][0]
    c["no_external_images"] = all("uri" not in im for im in doc.get("images", []))
    prims = [p for m in doc.get("meshes", []) for p in m.get("primitives", [])]
    c["no_morph_targets"] = all(not p.get("targets") for p in prims)
    nverts = sum(doc["accessors"][p["attributes"]["POSITION"]]["count"] for p in prims)
    nidx = sum(doc["accessors"][p["indices"]]["count"] for p in prims if "indices" in p)
    c["vertices_38365"] = nverts == VERTICES
    c["faces_76073"] = nidx == FACES * 3
    if kind == "service":
        extras = (doc.get("scenes") or [{}])[0].get("extras", {})
        cm = extras.get("coordinate_metadata", {})
        c["generator"] = doc.get("asset", {}).get("generator") == "AgeMorph3D static canonical v1"
        c["coordinate_metadata"] = (cm.get("canonical_unit") == "dimensionless"
                                    and cm.get("source_units") == "unverified"
                                    and cm.get("metric_scale_verified") is False)
    else:
        root = next((n for n in doc.get("nodes", []) if n.get("name") == "AgeMorph3D_Loaded_Model"), None)
        extras = (root or {}).get("extras", {})
        c["viewer_root_node"] = root is not None
    c["extras_asset_mode_static"] = extras.get("asset_mode") == "static"
    c["extras_no_age_keys"] = all(k not in extras for k in AGE_KEYS)
    if response:
        r = json.load(open(response, encoding="utf-8"))
        c["extras_topology_matches_response"] = extras.get("topology_id") == r.get("topology_id")
        c["extras_source_age_matches_response"] = extras.get("source_age") == r.get("source_age")
    else:
        c["extras_topology_id"] = extras.get("topology_id") == TOPOLOGY_ID
    return c, {"file": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
               "vertices": nverts, "triangles": nidx // 3, "kind": kind}


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    cmd, args = argv[1], argv[2:]
    def opt(name, default=None):
        if name in args:
            i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return v
        return default
    try:
        if cmd == "resp":
            sa = opt("--source-age"); checks, info = check_resp(args[0], sa)
        elif cmd == "glb":
            kind = opt("--kind", "service"); resp = opt("--response")
            checks, info = check_glb(args[0], kind, resp)
        elif cmd == "angle":
            a, b = rot(json.load(open(args[0], encoding="utf-8"))), rot(json.load(open(args[1], encoding="utf-8")))
            tr = sum(a[k][i] * b[k][i] for i in range(3) for k in range(3))
            ang = math.degrees(math.acos(max(-1, min(1, (tr - 1) / 2))))
            checks, info = {}, {"a": args[0], "b": args[1], "relative_rotation_deg": ang}
        elif cmd == "distinct":
            if len(args) < 2: raise ValueError("至少两个 GLB")
            hashes = [sha256(p) for p in args]
            pos = [positions(*load_glb(p)[1:]) for p in args]
            pairs = {}
            for i in range(len(args)):
                for j in range(i + 1, len(args)):
                    diff = (max(abs(x - y) for u, v in zip(pos[i], pos[j]) for x, y in zip(u, v))
                            if len(pos[i]) == len(pos[j]) else None)
                    pairs[f"{args[i]} | {args[j]}"] = diff
            checks = {"sha256_all_distinct": len(set(hashes)) == len(hashes),
                      "positions_all_differ": all(v is None or v > 0 for v in pairs.values())}
            info = {"sha256": dict(zip(args, hashes)), "max_abs_position_diff": pairs}
        else:
            print(__doc__); return 2
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
        print(json.dumps({"command": cmd, "error": str(e)}, ensure_ascii=False)); return 2
    ok = all(checks.values())
    print(json.dumps({"command": cmd, "ok": ok, "checks": checks, "info": info}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
