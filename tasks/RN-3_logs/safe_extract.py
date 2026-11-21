"""RN-3 driver: reuse FG-4 (feat/safe-loading @4b5e5c5) _scan/_extract unchanged; only limits are per-dataset."""
import json, sys, os, hashlib, time
from pathlib import Path
sys.path.insert(0, "/workspace/AgeMorph3D_fg4")
sys.dont_write_bytecode = True
from preprocessing import archive_preparation as ap
root = Path(sys.argv[1]).resolve(); archive = root / sys.argv[2]; output = sys.argv[3]
limits = json.loads(sys.argv[4]); dircap = int(sys.argv[5]) if len(sys.argv) > 5 else None
report = {"archive": str(archive), "output": str(root / output), "limits": limits,
          "fg4_module": ap.__file__, "fg4_module_sha256": ap.PRODUCER_SHA256,
          "zip_directory_cap_override": dircap}
dest = ap.safe(root, output + "/files")
assert not (root / output).exists(), "output exists"
try:
    inv = ap._scan(archive, "zip", limits, dest)
    report["preflight_unmodified"] = "PASS"
except ap.Error as e:
    report["preflight_unmodified"] = f"REJECT:{e}"
    if dircap is None or str(e) != "ZIP_DIRECTORY_LIMIT":
        print(json.dumps(report, ensure_ascii=False)); sys.exit(2)
    src = Path(ap.__file__).read_text()
    # override only the hard-coded 1 MiB central-directory byte cap; every other check identical
    seg = "def _zip_guard" + src.split("def _zip_guard", 1)[1].split("\nclass _BoundedReader", 1)[0]
    assert seg.count("directory_bytes <= 1024**2") == 1
    g = ap.__dict__
    ns = {}
    exec(compile(seg.replace("directory_bytes <= 1024**2", f"directory_bytes <= {dircap}"), "fg4_zip_guard_dircap", "exec"), g, ns)
    ap._zip_guard = ns["_zip_guard"]
    inv = ap._scan(archive, "zip", limits, dest)
    report["preflight_with_dircap_override"] = "PASS"
report["preflight_members"] = len(inv)
report["preflight_files"] = sum(r["kind"] == "file" for r in inv)
report["preflight_dirs"] = sum(r["kind"] == "directory" for r in inv)
report["preflight_total_bytes"] = sum(r["bytes"] for r in inv)
t = time.time()
res = ap._extract(root, archive, "zip", limits, output, inv)
report["extract_seconds"] = round(time.time() - t, 1)
from collections import Counter
report["status_counts"] = dict(Counter(r["status"] for r in res))
report["failures"] = [r for r in res if r["status"] == "failed"][:50]
report["extracted_bytes"] = sum(r["file"]["bytes"] for r in res if r["file"])
stage = root / output / "stage"
report["stage_leftover"] = sorted(os.listdir(stage)) if stage.exists() else None
if stage.exists() and not os.listdir(stage): stage.rmdir(); report["stage_removed_empty"] = True
manifest = root / (output + ".members.json")
manifest.write_text(json.dumps(res, ensure_ascii=False))
report["member_manifest"] = str(manifest)
report["member_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
print(json.dumps(report, ensure_ascii=False, indent=1))
