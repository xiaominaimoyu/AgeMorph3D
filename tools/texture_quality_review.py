"""Prepare and validate frozen, offline texture observations; never grant quality."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import itertools
import json
import re
import struct
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath

PROTOCOL = "agemorph3d-texture-quality-review-v1"
VARIANTS = ("conservative", "observed")
FOCUS = tuple(f"fgnet-004a63--sam-{age:03}" for age in (20, 45, 63, 70))
CONFIGS = tuple(
    "/".join(c) for c in itertools.product(("MASK", "BLEND"), ("front", "side"), ("black", "white"))
)
CRITERIA = (
    "eyes_glasses",
    "side_coverage",
    "seams",
    "identity_appearance",
    "age_condition_appearance",
)
RATINGS = ("pending", "issue", "no_obvious_issue", "not_assessable")
SOURCES = ("tools/texture_quality_review.py", "backend/tests/test_texture_quality_review.py")
ROLES = (
    "protocol",
    "target_review",
    "conservative_capture",
    "observed_capture",
    "conservative_identity",
    "observed_identity",
)
LIMITS = {
    "metadata_bytes": 16 * 1024**2,
    "image_bytes": 4 * 1024**2,
    "total_image_bytes": 1024**3,
    "image_side": 1024,
    "page_bytes": 16 * 1024**2,
    "total_page_bytes": 128 * 1024**2,
    "note_characters": 2000,
}
FLAGS = dict.fromkeys(
    (
        "human_review_completed",
        "age_quality_accepted",
        "identity_quality_accepted",
        "visual_seam_quality_accepted",
        "independent_evaluation",
        "service_ready",
        "production_enabled",
        "g3_complete",
    ),
    False,
)
FIELDS = (
    "asset_id",
    "source_id",
    "sample_id",
    "role",
    "source_age_label",
    "target_age",
    "category",
    "frame_id",
    "config_id",
    "configuration",
)
UNKNOWN_AGE = {"value": None, "method": "unknown", "calibration_id": None}
_LOADED_SOURCE_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _keys(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError("Unexpected or missing fields.")


def _equal(a, b):
    return _encode(a) == _encode(b)


def _encode(value):
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _json(data):
    def invalid(_):
        raise ValueError("Nonfinite JSON value.")

    return json.loads(data, object_pairs_hook=_pairs, parse_constant=invalid)


def _relative(root, name):
    if (
        type(name) is not str
        or not name
        or "\\" in name
        or ":" in name
        or any(p in {"", ".", ".."} for p in name.split("/"))
        or name.startswith("/")
    ):
        raise ValueError("Only canonical workspace-relative paths are allowed.")
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes workspace.")
    return path


def _bounded(path, maximum):
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Input is missing, nonregular or oversized.")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Input grew beyond its read budget.")
    return data


class Inputs:
    def __init__(self, root):
        self.root, self.pins = root, {}

    def read(self, pin, maximum=LIMITS["metadata_bytes"]):
        _keys(pin, ("path", "bytes", "sha256"))
        if (
            type(pin["bytes"]) is not int
            or not 0 < pin["bytes"] <= maximum
            or type(pin["sha256"]) is not str
            or not re.fullmatch("[0-9a-f]{64}", pin["sha256"])
        ):
            raise ValueError("Invalid size/hash pin.")
        name = pin["path"]
        path = _relative(self.root, name)
        if name in self.pins and not _equal(self.pins[name], pin):
            raise ValueError("Conflicting input pins.")
        data = _bounded(path, pin["bytes"])
        if len(data) != pin["bytes"] or hashlib.sha256(data).hexdigest() != pin["sha256"]:
            raise ValueError("Input size/hash differs from frozen evidence.")
        self.pins[name] = dict(pin)
        return data

    def recheck(self):
        for pin in list(self.pins.values()):
            self.read(pin, max(LIMITS["metadata_bytes"], pin["bytes"]))


def _closed(report):
    if report.get("research_only") is not True:
        raise ValueError("Evidence must be research-only.")
    for key in (
        "age_quality_accepted",
        "identity_quality_accepted",
        "independent_evaluation",
        "service_ready",
        "production_enabled",
        "g3_complete",
    ):
        if report.get(key) is not False:
            raise ValueError("Saved evidence cannot grant quality/service readiness.")


def _capture(report):
    _closed(report)
    if (
        report.get("protocol_id") != "agemorph3d-render-domain-v1"
        or report.get("status") != "passed"
    ):
        raise ValueError("A successful saved render capture is required.")
    if report.get("requested_frames") != 376 or report.get("requested_pairs") != 296:
        raise ValueError("Full capture denominator is required.")
    assets, frames, pairs = report.get("assets"), report.get("frames"), report.get("pairs")
    if (
        not isinstance(assets, list)
        or len(assets) != 47
        or not isinstance(frames, list)
        or len(frames) != 376
        or not isinstance(pairs, list)
        or len(pairs) != 296
    ):
        raise ValueError("Incomplete saved cohort.")
    by_asset = {a["asset_id"]: {k: a[k] for k in FIELDS[:7]} for a in assets}
    originals = {a["source_id"]: a for a in by_asset.values() if a["sample_id"] is None}
    targets = {a["sample_id"]: a for a in by_asset.values() if a["sample_id"] is not None}
    if (
        len(by_asset) != 47
        or len(originals) != 10
        or len(targets) != 37
        or not set(FOCUS) <= set(targets)
    ):
        raise ValueError("Wrong or duplicate source/target cohort.")
    expected = {}
    for asset in by_asset.values():
        if asset["source_id"] not in originals or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,100}", asset["asset_id"]
        ):
            raise ValueError("Unbound source or unsafe asset identifier.")
        for config in CONFIGS:
            frame_id = asset["asset_id"] + "::" + config
            material, view, background = config.split("/")
            expected[frame_id] = dict(
                asset,
                frame_id=frame_id,
                config_id=config,
                configuration={"material_mode": material, "view": view, "background": background},
            )
    images, actual = set(), {}
    for frame in frames:
        fid = frame["frame_id"]
        if (
            fid in actual
            or fid not in expected
            or not _equal({k: frame[k] for k in FIELDS}, expected[fid])
            or frame.get("status") != "ok"
        ):
            raise ValueError("Capture frame cohort/configuration differs.")
        image = frame["image"]
        name = image["path"]
        if (
            not name.startswith("output/research/")
            or PurePosixPath(name).suffix != ".png"
            or name in images
        ):
            raise ValueError("Each saved frame needs its own research PNG.")
        images.add(name)
        actual[fid] = frame
    if set(actual) != set(expected):
        raise ValueError("Missing capture configuration.")
    expected_pairs = {
        (
            t["source_id"],
            t["sample_id"],
            c,
            originals[t["source_id"]]["asset_id"] + "::" + c,
            t["asset_id"] + "::" + c,
        )
        for t in targets.values()
        for c in CONFIGS
    }
    actual_pairs = []
    for pair in pairs:
        _keys(pair, ("source_id", "sample_id", "config_id", "source_frame_id", "target_frame_id"))
        actual_pairs.append(
            tuple(
                pair[k]
                for k in (
                    "source_id",
                    "sample_id",
                    "config_id",
                    "source_frame_id",
                    "target_frame_id",
                )
            )
        )
    if len(set(actual_pairs)) != 296 or set(actual_pairs) != expected_pairs:
        raise ValueError("Source-target pair denominator differs.")
    return actual, targets


def load(root, plan_path):
    inputs = Inputs(root)
    raw = _bounded(_relative(root, plan_path), LIMITS["metadata_bytes"])
    plan_pin = {"path": plan_path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    plan = _json(inputs.read(plan_pin))
    _keys(plan, ("schema_version", "protocol_id", "roles", "sources"))
    if (
        type(plan["schema_version"]) is not int
        or plan["schema_version"] != 1
        or plan["protocol_id"] != PROTOCOL
    ):
        raise ValueError("Unsupported study plan.")
    _keys(plan["roles"], ROLES)
    if not isinstance(plan["sources"], list) or [s["path"] for s in plan["sources"]] != list(
        SOURCES
    ):
        raise ValueError("Freeze implementation and tests before preparing evidence.")
    for pin in plan["sources"]:
        inputs.read(pin)
    if _LOADED_SOURCE_HASH != plan["sources"][0]["sha256"]:
        raise ValueError("Loaded implementation is not the frozen producer.")
    values = {role: _json(inputs.read(pin)) for role, pin in plan["roles"].items()}
    policy = values["protocol"]
    required = {
        "schema_version": 1,
        "protocol_id": PROTOCOL,
        "cohort": {
            "sources": 10,
            "targets": 37,
            "frames_per_variant": 376,
            "pairs_per_variant": 296,
        },
        "focus": list(FOCUS),
        "variants": list(VARIANTS),
        "criteria": list(CRITERIA),
        "ratings": list(RATINGS),
        "limits": LIMITS,
    }
    if any(not _equal(policy.get(k), v) for k, v in required.items()):
        raise ValueError("Review protocol changed.")
    target_review = values["target_review"]
    _closed(target_review)
    review_ids = [r["sample_id"] for r in target_review["target_records"]]
    if len(review_ids) != 37 or len(set(review_ids)) != 37:
        raise ValueError("Full37 target review required.")
    captures, identity, images, counters = {}, {}, {}, {}
    total_bytes = 0
    for variant in VARIANTS:
        frames, targets = _capture(values[variant + "_capture"])
        if set(targets) != set(review_ids):
            raise ValueError("Target review and capture cohort differ.")
        saved = values[variant + "_identity"]
        _closed(saved)
        if saved.get("integrity_status") != "passed" or plan["roles"][
            variant + "_capture"
        ] not in saved.get("inputs", []):
            raise ValueError("Identity results are not bound to this exact capture.")
        rows = saved.get("frames")
        if not isinstance(rows, list) or len(rows) != 376:
            raise ValueError("Keep every evaluator failure in the denominator.")
        result = {}
        for row in rows:
            fid = row["frame_id"]
            if (
                fid in result
                or fid not in frames
                or any(not _equal(row[k], frames[fid][k]) for k in (*FIELDS, "image"))
            ):
                raise ValueError("Evaluator/frame provenance differs.")
            status = row["status"]
            if type(status) is not str or not re.fullmatch(r"[A-Za-z_]{1,64}", status):
                raise ValueError("Invalid saved evaluator status.")
            result[fid] = status
        if set(result) != set(frames):
            raise ValueError("Missing evaluator result.")
        counters[variant] = dict(Counter(result.values()))
        captures[variant], identity[variant] = frames, result
        for frame in frames.values():
            total_bytes += frame["image"]["bytes"]
            if total_bytes > LIMITS["total_image_bytes"]:
                raise ValueError("Total image budget exceeded.")
            data = inputs.read(frame["image"], LIMITS["image_bytes"])
            if (
                data[:8] != b"\x89PNG\r\n\x1a\n"
                or data[12:16] != b"IHDR"
                or len(data) < 33
                or struct.unpack(">II", data[16:24]) != (1024, 1024)
            ):
                raise ValueError("Expected saved native1024 PNG bytes.")
            if frame["sample_id"] in FOCUS or (
                frame["sample_id"] is None and frame["source_id"] == "fgnet-004a63"
            ):
                images[variant, frame["frame_id"]] = data
    for fid in captures[VARIANTS[0]]:
        if fid not in captures[VARIANTS[1]] or not _equal(
            {k: captures[VARIANTS[0]][fid][k] for k in FIELDS},
            {k: captures[VARIANTS[1]][fid][k] for k in FIELDS},
        ):
            raise ValueError("Variant cohorts/configurations differ.")
        left, right = (captures[v][fid] for v in VARIANTS)
        for key in ("geometry",):
            if not _equal(left["observed"][key], right["observed"][key]):
                raise ValueError("Variant geometry differs.")
        for key in ("camera", "transforms"):
            if not _equal(
                left["observed"]["invariants"][key], right["observed"]["invariants"][key]
            ):
                raise ValueError("Variant camera/transform differs.")
        if left["sample_id"] is None and left["image"]["sha256"] != right["image"]["sha256"]:
            raise ValueError("Original control pixels differ across variants.")
    if not _equal(
        values["conservative_capture"]["requested_configuration"],
        values["observed_capture"]["requested_configuration"],
    ):
        raise ValueError("Saved capture settings differ.")
    records = []
    for sample in FOCUS:
        for config in CONFIGS:
            fid = sample + "::" + config
            frame = captures["observed"][fid]
            records.append(
                {
                    "sample_id": sample,
                    "config_id": config,
                    "source_id": frame["source_id"],
                    "source_age_api": UNKNOWN_AGE,
                    "source_age_research_label": frame["source_age_label"],
                    "target_age_condition": frame["target_age"],
                    "category": frame["category"],
                    "evidence": {
                        v: {
                            "frame_id": fid,
                            "image": captures[v][fid]["image"],
                            "saved_identity_status": identity[v][fid],
                        }
                        for v in VARIANTS
                    },
                    "assessments": {
                        v: {c: {"rating": "pending", "note": ""} for c in CRITERIA}
                        for v in VARIANTS
                    },
                }
            )
    worksheet = {
        "schema_version": 1,
        "protocol_id": PROTOCOL,
        "plan": plan_pin,
        "reviewer": {"kind": None, "name": None, "recorded_at": None},
        "scope": "focus_development_observations_not_cohort_acceptance",
        "cohort_targets": [targets[name] for name in sorted(targets)],
        "denominators": {
            "targets": 37,
            "frames_per_variant": 376,
            "pairs_per_variant": 296,
            "focus_pairs": 32,
            "focus_frames_per_variant": 32,
            "saved_identity_status_counts": counters,
        },
        "records": records,
        "research_only": True,
        **FLAGS,
    }
    inputs.recheck()
    return inputs, worksheet, images


def validate(worksheet, expected):
    _keys(worksheet, expected)
    fixed = [k for k in expected if k not in {"reviewer", "records"}]
    if any(not _equal(worksheet[k], expected[k]) for k in fixed):
        raise ValueError("Worksheet evidence binding or closed flags changed.")
    reviewer = worksheet["reviewer"]
    _keys(reviewer, ("kind", "name", "recorded_at"))
    rows = worksheet["records"]
    if not isinstance(rows, list) or len(rows) != 32:
        raise ValueError("All32 focus pairs, including failures, must remain.")
    counts = Counter()
    for row, bound in zip(rows, expected["records"], strict=True):
        _keys(row, bound)
        if any(not _equal(row[k], bound[k]) for k in bound if k != "assessments"):
            raise ValueError("Review row evidence or order changed.")
        _keys(row["assessments"], VARIANTS)
        for variant in VARIANTS:
            _keys(row["assessments"][variant], CRITERIA)
            for check in row["assessments"][variant].values():
                _keys(check, ("rating", "note"))
                rating, note = check["rating"], check["note"]
                if (
                    type(rating) is not str
                    or rating not in RATINGS
                    or type(note) is not str
                    or len(note) > LIMITS["note_characters"]
                ):
                    raise ValueError("Invalid observation rating/note.")
                if rating != "pending" and not note.strip():
                    raise ValueError("Every answered criterion needs an explanation.")
                counts[rating] += 1
    empty_reviewer = all(v is None for v in reviewer.values())
    if not empty_reviewer:
        if (
            reviewer["kind"] not in {"human", "ai"}
            or type(reviewer["name"]) is not str
            or not 0 < len(reviewer["name"].strip()) <= 100
            or type(reviewer["recorded_at"]) is not str
        ):
            raise ValueError("Explicit self-reported reviewer kind/name/date required.")
        try:
            stamp = datetime.fromisoformat(reviewer["recorded_at"])
            if stamp.utcoffset() is None:
                raise ValueError("Reviewer date needs a timezone.")
        except (ValueError, TypeError) as error:
            raise ValueError("Invalid reviewer timestamp.") from error
    has_notes = any(
        check["note"].strip()
        for row in rows
        for checks in row["assessments"].values()
        for check in checks.values()
    )
    if (counts["pending"] != 320 or has_notes) and empty_reviewer:
        raise ValueError("Answered observations need explicit self-reported origin.")
    return {
        "status": "valid_pending" if counts["pending"] else "valid_self_reported_complete",
        "ratings": {r: counts[r] for r in RATINGS},
        "answered_criteria": 320 - counts["pending"],
        "total_criteria": 320,
        "reviewer_kind_self_reported": reviewer["kind"],
        "authorship_authenticated": False,
        "observations_are_quality_acceptance": False,
        "research_only": True,
        **FLAGS,
    }


def _document(title, body):
    csp = (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
        "script-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'"
    )
    return (
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
        f"<title>{html.escape(title)}</title><style>"
        "body{background:#0a0e1a;color:#e9eef6;"
        "font:16px 'Segoe UI',sans-serif;margin:24px}"
        "a{color:#35d3c0}section{margin:24px 0;padding:16px;background:#101624}"
        ".pair{display:flex;flex-wrap:wrap;gap:12px}figure{margin:0;flex:1;min-width:260px}"
        "img{display:block;max-width:100%;height:auto}code{overflow-wrap:anywhere}"
        f"</style><h1>{html.escape(title)}</h1>{body}</html>"
    ).encode()


def pages(worksheet, images):
    result = {}
    message = (
        "<p>开发证据人工/AI观察准备；不是质量签收。37目标、每版376帧/296对，32重点对照；"
        "NO_FACE完整保留。API源龄unknown；63仅为文件名研究标签，生成条件不是实际年龄。"
        "请另存并填写worksheet.json的reviewer及assessments；本页不保存或提交评审。"
        "身份和年龄项仅记画面观感；无法判断请填not_assessable，不能代替真实身份或年龄评价。</p>"
    )
    links = []
    for config in CONFIGS:
        name = config.replace("/", "--") + ".html"
        links.append(f'<li><a href="{name}">{html.escape(config)}</a></li>')
        blocks = []
        original = images["observed", "fgnet-004a63--original::" + config]
        original_uri = base64.b64encode(original).decode("ascii")
        blocks.append(
            "<section><h2>原始静态对照 / API源龄unknown</h2>"
            f'<img width="1024" height="1024" alt="原始静态对照" '
            f'src="data:image/png;base64,{original_uri}"></section>'
        )
        for row in worksheet["records"]:
            if row["config_id"] != config:
                continue
            figures = []
            for v in VARIANTS:
                evidence = row["evidence"][v]
                raw = images[v, evidence["frame_id"]]
                uri = base64.b64encode(raw).decode("ascii")
                caption = html.escape(v + " / " + evidence["saved_identity_status"])
                digest = html.escape(evidence["image"]["sha256"])
                figures.append(
                    f"<figure><figcaption>{caption}</figcaption>"
                    f'<img width="1024" height="1024" alt="{caption}" '
                    f'src="data:image/png;base64,{uri}"><code>{digest}</code></figure>'
                )
            blocks.append(
                f"<section><h2>{html.escape(row['sample_id'])}</h2>"
                f'<div class="pair">{"".join(figures)}</div>'
                "<p>逐项记录：眼区/眼镜、侧面覆盖、接缝、身份观感、年龄条件观感；"
                "无法判断请填not_assessable及原因。</p></section>"
            )
        result[name] = _document(
            config, '<a href="index.html">返回索引</a>' + message + "".join(blocks)
        )
    counts = html.escape(
        json.dumps(worksheet["denominators"]["saved_identity_status_counts"], ensure_ascii=False)
    )
    result["index.html"] = _document(
        "K4纹理观察评审准备",
        message
        + f"<p>历史检测状态：<code>{counts}</code></p><ul>{''.join(links)}</ul>"
        + "<p>所有评审仍待填写；完成表格不能自动授予人工质量、独立评价、服务或G3资格。</p>",
    )
    if (
        any(len(data) > LIMITS["page_bytes"] for data in result.values())
        or sum(map(len, result.values())) > LIMITS["total_page_bytes"]
    ):
        raise ValueError("Offline page byte budget exceeded.")
    return result


def publish(inputs, output, artifacts):
    output = _relative(inputs.root, output)
    if not output.relative_to(inputs.root).as_posix().startswith("output/research/"):
        raise ValueError("Use a fresh ignored output/research directory.")
    inputs.recheck()
    output.mkdir(parents=True, exist_ok=False)
    owned = []
    try:
        for name, data in artifacts.items():
            if PurePosixPath(name).name != name or name in {"", ".", ".."}:
                raise ValueError("Only flat owned output files are allowed.")
            target = output / name
            with target.open("xb") as stream:
                owned.append(target)
                stream.write(data)
        inputs.recheck()
    except BaseException:
        for path in reversed(owned):
            path.unlink()
        if not any(output.iterdir()):
            output.rmdir()
        raise


def run(root, plan, output, worksheet_path=None):
    inputs, expected, images = load(root, plan)
    if worksheet_path is None:
        artifacts = pages(expected, images)
        artifacts["worksheet.json"] = _encode(expected)
        report = validate(expected, expected)
    else:
        path = _relative(root, worksheet_path)
        data = _bounded(path, LIMITS["metadata_bytes"])
        pin = {
            "path": worksheet_path,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        report = validate(_json(inputs.read(pin)), expected)
        report["worksheet"] = pin
        artifacts = {}
    report.update(
        protocol_id=PROTOCOL,
        plan=expected["plan"],
        denominators=expected["denominators"],
        cohort_targets=expected["cohort_targets"],
        verified_inputs=list(inputs.pins.values()),
        verified_input_files=len(inputs.pins),
        saved_png_files_verified=752,
        model_inference_run=False,
        saved_producer_reexecuted=False,
        artifacts=[
            {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in artifacts.items()
        ],
    )
    artifacts["report.json"] = _encode(report)
    publish(inputs, output, artifacts)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-plan", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--worksheet", help="Validate a separately edited observation draft.")
    args = parser.parse_args(argv)
    try:
        report = run(
            Path(__file__).resolve().parents[1], args.study_plan, args.output_dir, args.worksheet
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(
            json.dumps({"status": "invalid_input", "error": str(error), **FLAGS}), file=sys.stderr
        )
        return 2
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "answered_criteria",
                    "total_criteria",
                    "saved_png_files_verified",
                    "g3_complete",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
