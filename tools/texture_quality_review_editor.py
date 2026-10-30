"""Build an opt-in, self-contained offline observation editor from existing K4 evidence.

The original read-only pages, study plan and quality collector are unchanged.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import stat
import subprocess
import sys
from pathlib import Path

try:
    from . import texture_quality_review as review
except ImportError:
    import texture_quality_review as review

MAX_HTML = 64 * 1024**2
MAX_CODE = 128 * 1024
SOURCES = (
    "frontend/src/research-quality-review.ts",
    "frontend/src/research-quality-review.css",
    "tools/texture_quality_review_editor.py",
)
COMPILER = (
    'import {readFileSync} from "node:fs";'
    'import {stripTypeScriptTypes} from "node:module";'
    'process.stdout.write(stripTypeScriptTypes(readFileSync(process.argv[1],"utf8"),'
    '{mode:"strip"}));'
)


def _pin(root, name):
    body = review._bounded(root / name, MAX_CODE)
    return {
        "path": name,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _safe_output(root, output):
    target = review._relative(root, output)
    if not output.startswith("output/research/") or target.exists():
        raise ValueError("Use a new output/research directory.")
    current = root
    for part in Path(output).parts:
        current /= part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError("Links or reparse output paths are not allowed.")
    return target


def build_editor(root, study_plan, output, node_executable):
    root = Path(root).absolute()
    if root != root.resolve() or not root.is_dir():
        raise ValueError("Use a real project root.")
    _safe_output(root, output)
    runtime = Path(node_executable).absolute()
    if not runtime.is_file() or runtime.is_symlink():
        raise ValueError("Specify the installed Node executable.")
    runtime_body = runtime.read_bytes()
    runtime_pin = {
        "path": str(runtime),
        "bytes": len(runtime_body),
        "sha256": hashlib.sha256(runtime_body).hexdigest(),
    }
    inputs, worksheet, images = review.load(root, study_plan)
    review.validate(worksheet, worksheet)
    code = {}
    for name in SOURCES:
        code[name] = inputs.read(_pin(root, name), MAX_CODE).decode("utf-8")
    compiled = subprocess.run(
        [str(runtime), "--input-type=module", "-e", COMPILER, str(root / SOURCES[0])],
        cwd=root,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if compiled.returncode or not compiled.stdout or len(compiled.stdout) > MAX_CODE:
        raise ValueError("Installed Node could not strip the editor TypeScript.")
    script = compiled.stdout.decode("utf-8")
    if re.search(r"\bimport\b\s*(?:[\w\"'{*]|\()", script):
        raise ValueError("The offline editor must have no runtime imports.")
    css = code[SOURCES[1]]
    if "</style" in css.lower():
        raise ValueError("Invalid inline stylesheet.")
    selected = {}
    originals = {}
    for index, row in enumerate(worksheet["records"]):
        for variant in review.VARIANTS:
            raw = images[variant, row["evidence"][variant]["frame_id"]]
            selected[f"{index}/{variant}"] = (
                "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
            )
        config = row["config_id"]
        if config not in originals:
            raw = images["observed", "fgnet-004a63--original::" + config]
            originals[config] = "data:image/png;base64," + base64.b64encode(raw).decode(
                "ascii"
            )
    package = json.dumps(
        {"worksheet": worksheet, "images": selected, "originals": originals},
        ensure_ascii=False,
    )
    package = (
        package.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
    script = re.sub(r"</script", r"<\/script", script, flags=re.IGNORECASE)
    html = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "connect-src 'none'; img-src data:; style-src 'unsafe-inline'; "
        """script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">"""
        "<title>AgeMorph3D 纹理质量观察</title><style>" + css + "</style></head><body>"
        '<main id="quality-review"></main><script id="review-package" type="application/json">'
        + package
        + '</script><script type="module">'
        + script
        + '\nmountQualityReview(JSON.parse(document.getElementById("review-package").textContent));'
        "</script></body></html>"
    ).encode("utf-8")
    if len(html) > MAX_HTML:
        raise ValueError("Self-contained page exceeds 64 MiB.")
    if runtime.read_bytes() != runtime_body:
        raise ValueError("Node executable changed during compilation.")
    report = {
        "protocol_id": "agemorph3d-texture-quality-editor-v1",
        "status": "prepared_pending_observations",
        "research_only": True,
        "study_plan": worksheet["plan"],
        "verified_inputs": list(inputs.pins.values()),
        "runtime": runtime_pin,
        "node_compiler_stderr": compiled.stderr.decode("utf-8", errors="replace"),
        "embedded_images": len(selected) + len(originals),
        "worksheet_records": len(worksheet["records"]),
        "criteria": 320,
        "worksheet_initially_pending": True,
        "artifact": {
            "path": "index.html",
            "bytes": len(html),
            "sha256": hashlib.sha256(html).hexdigest(),
        },
        "model_inference_run": False,
        "saved_producer_reexecuted": False,
        **review.FLAGS,
    }
    review.publish(
        inputs, output, {"index.html": html, "report.json": review._encode(report)}
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-plan", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--node-executable", required=True)
    args = parser.parse_args(argv)
    try:
        report = build_editor(
            Path(__file__).resolve().parents[1],
            args.study_plan,
            args.output_dir,
            args.node_executable,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps({"status": "invalid_input", "error": str(error), **review.FLAGS})
        )
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "embedded_images": report["embedded_images"],
                "criteria": report["criteria"],
                **review.FLAGS,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
