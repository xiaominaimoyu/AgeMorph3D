"""Explicit affine point/box preparation and offline overlays for P02.

Point coordinates use zero-based pixel centers; boxes use pixel edges.
No dataset-specific landmark mapping, model inference or training is performed.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html
import io
import json
import math
import shutil
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from . import archive_preparation as preparation
from . import dataset_manifest as metadata
from . import resource_acquisition as acquisition

SCHEMA = "agemorph3d-annotation-transform-v1"
MAX_JSON = 4 * 1024**2
MAX_PLAN = 512 * 1024
MAX_IMAGE_BYTES = 16 * 1024**2
MAX_SIDE = 8192
MAX_PIXELS = 16 * 1024**2
MAX_POINTS = 128
MAX_ASSETS = 256 * 1024**2
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
Error, require, safe = preparation.Error, preparation.require, preparation.safe


def _number(value):
    require(type(value) in (int, float), "NONNUMERIC_COORDINATE")
    try:
        value = float(value)
    except (ValueError, OverflowError) as error:
        raise Error("INVALID_COORDINATE") from error
    require(math.isfinite(value) and abs(value) <= 1e12, "INVALID_COORDINATE")
    return value


def affine(value):
    require(
        type(value) is list
        and len(value) == 3
        and all(type(row) is list and len(row) == 3 for row in value),
        "INVALID_AFFINE_SHAPE",
    )
    matrix = [[_number(v) for v in row] for row in value]
    require(matrix[2] == [0, 0, 1], "PROJECTIVE_MATRIX_UNSUPPORTED")
    a, b = matrix[0][:2]
    c, d = matrix[1][:2]
    scale = max(abs(a), abs(b), abs(c), abs(d))
    require(
        scale > 0 and abs(a * d - b * c) > 1e-12 * scale**2, "SINGULAR_OR_ILL_CONDITIONED_AFFINE"
    )
    return matrix


def compose(after, before):
    """Apply before first, then after (column-vector convention)."""
    after, before = affine(after), affine(before)
    return affine(
        [[sum(after[i][k] * before[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    )


def inverse(matrix):
    matrix = affine(matrix)
    a, b, x = matrix[0]
    c, d, y = matrix[1]
    determinant = a * d - b * c
    return affine(
        [
            [d / determinant, -b / determinant, (b * y - d * x) / determinant],
            [-c / determinant, a / determinant, (c * x - a * y) / determinant],
            [0, 0, 1],
        ]
    )


def point(matrix, xy):
    if xy is None:
        return None
    matrix = affine(matrix)
    require(type(xy) is list and len(xy) == 2, "INVALID_POINT")
    x, y = [_number(v) for v in xy]
    return [_number(matrix[i][0] * x + matrix[i][1] * y + matrix[i][2]) for i in range(2)]


def edge_matrix(center_matrix):
    """Conjugate a pixel-center transform into pixel-edge coordinates."""
    return compose(
        [[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1]],
        compose(center_matrix, [[1, 0, -0.5], [0, 1, -0.5], [0, 0, 1]]),
    )


def box(matrix, value, output_size):
    if value is None:
        return None
    acquisition._keys(value, ("format", "values"))
    require(
        type(value["format"]) is str and value["format"] in {"xyxy_edges", "xywh_edges"},
        "BOX_FORMAT_UNSUPPORTED",
    )
    require(type(value["values"]) is list and len(value["values"]) == 4, "INVALID_BOX")
    left, top, right, bottom = [_number(v) for v in value["values"]]
    if value["format"] == "xywh_edges":
        require(right > 0 and bottom > 0, "DEGENERATE_BOX")
        right, bottom = _number(left + right), _number(top + bottom)
    require(right > left and bottom > top, "DEGENERATE_BOX")
    corners = [
        point(edge_matrix(matrix), p)
        for p in [[left, top], [right, top], [right, bottom], [left, bottom]]
    ]
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    bounds = [min(xs), min(ys), max(xs), max(ys)]
    width, height = _size(output_size)
    clipped = [max(0, bounds[0]), max(0, bounds[1]), min(width, bounds[2]), min(height, bounds[3])]
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        clipped = None
    return {
        "polygon_edges": corners,
        "enclosing_xyxy_edges": bounds,
        "clipped_xyxy_edges": clipped,
        "fully_inside": bounds[0] >= 0
        and bounds[1] >= 0
        and bounds[2] <= width
        and bounds[3] <= height,
    }


def _size(value):
    require(
        type(value) is list
        and len(value) == 2
        and all(acquisition._integer(v, 1, MAX_SIDE) for v in value)
        and value[0] * value[1] <= MAX_PIXELS,
        "RASTER_SIZE_LIMIT",
    )
    return value


def crop_resize_matrix(crop, size, source_size):
    width, height = _size(source_size)
    _size(size)
    require(
        type(crop) is list and len(crop) == 4 and all(type(v) is int for v in crop),
        "CROP_REQUIRES_INTEGER_EDGES",
    )
    left, top, right, bottom = crop
    require(0 <= left < right <= width and 0 <= top < bottom <= height, "CROP_OUTSIDE_SOURCE")
    sx, sy = size[0] / (right - left), size[1] / (bottom - top)
    return affine([[sx, 0, (0.5 - left) * sx - 0.5], [0, sy, (0.5 - top) * sy - 0.5], [0, 0, 1]])


def _annotation(item):
    acquisition._keys(item, ("sample_id", "point_schema", "points", "bbox", "alignment"))
    require(metadata._identifier(item["sample_id"]), "INVALID_SAMPLE_ID")
    schema = item["point_schema"]
    acquisition._keys(schema, ("id", "names", "laterality"))
    require(
        metadata._identifier(schema["id"])
        and type(schema["laterality"]) is str
        and schema["laterality"] in {"subject", "source_image", "unspecified"},
        "INVALID_POINT_SCHEMA",
    )
    require(
        type(schema["names"]) is list
        and 1 <= len(schema["names"]) <= MAX_POINTS
        and all(
            type(n) is str and 0 < len(n) <= 80 and all(ord(c) >= 32 for c in n)
            for n in schema["names"]
        ),
        "INVALID_POINT_NAMES",
    )
    require(len(set(schema["names"])) == len(schema["names"]), "DUPLICATE_POINT_NAMES")
    require(
        type(item["points"]) is list and len(item["points"]) == len(schema["names"]),
        "POINT_COUNT_MISMATCH",
    )
    for name, p in zip(schema["names"], item["points"], strict=True):
        acquisition._keys(p, ("name", "xy", "visibility"))
        require(
            p["name"] == name
            and type(p["visibility"]) is str
            and p["visibility"] in {"visible", "occluded", "unknown", "not_annotated"},
            "POINT_ORDER_OR_VISIBILITY_INVALID",
        )
        require(
            (p["xy"] is not None or p["visibility"] != "visible")
            and (p["xy"] is None or p["visibility"] != "not_annotated"),
            "MISSING_POINT_SEMANTICS_INVALID",
        )
        point(IDENTITY, p["xy"])
    box(IDENTITY, item["bbox"], [1, 1])
    acquisition._keys(item["alignment"], ("crop_edges", "output_size", "resample"))
    require(
        type(item["alignment"]["resample"]) is str
        and item["alignment"]["resample"] in {"nearest", "bilinear"},
        "RESAMPLE_UNSUPPORTED",
    )


def _load(root, value):
    preparation._pin(value, MAX_JSON)
    path = preparation._verify(root, value, MAX_JSON)
    return acquisition._json(acquisition._read(path, MAX_JSON))


class _Budget:
    def __init__(self, maximum):
        self.maximum, self.used, self.files = maximum, 0, []

    def write(self, root, name, body):
        require(self.used + len(body) <= self.maximum, "ASSET_BUDGET_EXCEEDED")
        self.used += len(body)
        entry = {"path": name, "reserved_bytes": len(body), "status": "incomplete", "file": None}
        self.files.append(entry)
        path = safe(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(body)
        path.chmod(path.stat().st_mode & ~0o222)
        entry.update(status="published", file=preparation._file_pin(root, path))
        return entry["file"]


def _svg(png, size, points, bbox):
    width, height = size
    radius = max(min(width, height) / 100, 0.01)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" overflow="hidden">',
        f'<image x="0" y="0" width="{width}" height="{height}" '
        f'href="data:image/png;base64,{base64.b64encode(png).decode()}"/>',
    ]
    if bbox is not None:
        polygon = " ".join(f"{x:.17g},{y:.17g}" for x, y in bbox["polygon_edges"])
        parts.append(
            f'<polygon class="bbox" points="{polygon}" fill="none" '
            f'stroke="#ffbf47" stroke-width="{radius / 2}"/>'
        )
    colors = {
        "visible": "#35d3c0",
        "occluded": "#ffbf47",
        "unknown": "#b3bbce",
        "not_annotated": "#b3bbce",
    }
    for p in points:
        if p["xy"] is None:
            continue
        x, y = p["xy"][0] + 0.5, p["xy"][1] + 0.5
        name = html.escape(p["name"], quote=True)
        parts.extend(
            [
                f'<circle class="landmark" data-name="{name}" cx="{x:.17g}" cy="{y:.17g}" '
                f'r="{radius}" fill="{colors[p["visibility"]]}"/>',
                f'<text x="{x + 2 * radius:.17g}" y="{y:.17g}" '
                f'font-size="{radius * 2.5}" fill="white">{name}</text>',
            ]
        )
    return ("".join(parts) + "</svg>").encode()


def _mapped(points, matrix, size):
    result = []
    for p in points:
        xy = point(matrix, p["xy"])
        inside = (
            None
            if xy is None
            else (-0.5 <= xy[0] < size[0] - 0.5 and -0.5 <= xy[1] < size[1] - 0.5)
        )
        result.append({**copy.deepcopy(p), "xy": xy, "in_frame": inside})
    return result


def _one(root, item, source, k5, output, budget, image_pins):
    row = {
        "sample_id": item["sample_id"],
        "status": "failed",
        "error_code": None,
        "source_status": source.get("status"),
        "source_error_code": source.get("error_code"),
        "k5": copy.deepcopy(k5),
        "annotations": copy.deepcopy(item),
        "assets": None,
    }
    try:
        require(source.get("status") == "decoded", "SOURCE_PREPARATION_FAILED")
        src_size, oriented_size = _size(source["source_size"]), _size(source["normalized_size"])
        orientation = source["source_orientation"]
        orient = preparation.orientation_matrix(
            orientation if orientation is not None else 1, *src_size
        )
        require(source["original_to_normalized"] == orient, "SOURCE_ORIENTATION_MATRIX_MISMATCH")
        expected_size = src_size[::-1] if orientation in {5, 6, 7, 8} else src_size
        require(oriented_size == expected_size, "SOURCE_ORIENTED_SIZE_MISMATCH")
        source_pin = source["normalized"]
        preparation._pin(source_pin, MAX_IMAGE_BYTES)
        path = preparation._verify(root, source_pin, MAX_IMAGE_BYTES)
        image_pins.append(source_pin)
        alignment = item["alignment"]
        resize = crop_resize_matrix(
            alignment["crop_edges"], alignment["output_size"], oriented_size
        )
        matrix = compose(resize, orient)
        reverse = inverse(matrix)
        size = alignment["output_size"]
        mapped = _mapped(item["points"], matrix, size)
        oriented_points = _mapped(item["points"], orient, oriented_size)
        bbox, oriented_bbox = (
            box(matrix, item["bbox"], size),
            box(orient, item["bbox"], oriented_size),
        )
        errors = [
            abs(a - b)
            for p in item["points"]
            if p["xy"] is not None
            for a, b in zip(point(reverse, point(matrix, p["xy"])), p["xy"], strict=True)
        ]
        stem = hashlib.sha256(item["sample_id"].encode()).hexdigest()
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                require(
                    image.format == "PNG"
                    and list(image.size) == oriented_size
                    and image.mode in {"RGB", "RGBA"}
                    and getattr(image, "n_frames", 1) == 1,
                    "SOURCE_PNG_CONTRACT_MISMATCH",
                )
                image.load()
                resample = (
                    Image.Resampling.NEAREST
                    if alignment["resample"] == "nearest"
                    else Image.Resampling.BILINEAR
                )
                with (
                    image.crop(tuple(alignment["crop_edges"])) as cropped,
                    cropped.resize(tuple(size), resample=resample) as aligned,
                ):
                    buffer = io.BytesIO()
                    aligned.info.clear()
                    aligned.save(preparation._LimitedWriter(buffer, MAX_IMAGE_BYTES), format="PNG")
                    png = buffer.getvalue()
        aligned_pin = budget.write(root, output + "/aligned/" + stem + ".png", png)
        original_png = acquisition._read(path, MAX_IMAGE_BYTES)
        first = budget.write(
            root,
            output + "/overlays/" + stem + "-oriented.svg",
            _svg(original_png, oriented_size, oriented_points, oriented_bbox),
        )
        second = budget.write(
            root, output + "/overlays/" + stem + "-aligned.svg", _svg(png, size, mapped, bbox)
        )
        row.update(
            status="transformed",
            center_matrix=matrix,
            edge_matrix=edge_matrix(matrix),
            inverse_center_matrix=reverse,
            original_to_oriented=orient,
            output_size=size,
            points=mapped,
            bbox=bbox,
            roundtrip_max_abs_error=max(errors, default=None),
            point_schema=copy.deepcopy(item["point_schema"]),
            semantic_reindexing_performed=False,
            target_laterality_verified=False,
            assets={"aligned": aligned_pin, "oriented_overlay": first, "aligned_overlay": second},
        )
    except (
        Error,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as error:
        row["error_code"] = str(error) if isinstance(error, Error) else "ROW_INPUT_OR_IMAGE_ERROR"
    return row


def _html(rows):
    cards = []
    for row in rows:
        title = html.escape(row["sample_id"])
        if row["assets"] is None:
            content = "<p>" + html.escape(row["error_code"] or "failed") + "</p>"
        else:
            stem = hashlib.sha256(row["sample_id"].encode()).hexdigest()
            content = (
                '<div class="views"><figure><img alt="方向校正后" '
                f'src="overlays/{stem}-oriented.svg"><figcaption>方向校正后</figcaption>'
                '</figure><figure><img alt="裁剪/缩放后" '
                f'src="overlays/{stem}-aligned.svg"><figcaption>裁剪/缩放后</figcaption>'
                "</figure></div>"
            )
        cards.append(f"<section><h2>{title}</h2>{content}</section>")
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>P02坐标叠加检查</title>'
        "<style>body{background:#101624;color:#e9eef6;"
        "font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:24px}"
        "main{max-width:1200px;margin:auto}"
        "section{border:1px solid #354157;margin:20px 0;padding:16px}"
        ".views{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0}"
        "img{display:block;width:100%;max-height:420px;object-fit:contain;background:#0a0e1a}"
        "figcaption{margin-top:8px}</style><main><h1>P02 坐标叠加检查</h1>"
        "<p>像素中心点与像素边界框分别变换。颜色表示原声明：绿=可见，黄=遮挡，灰=未知；"
        "空值不绘制。左右语义、人工质量及真实数据验收另行核对。</p>"
        + "".join(cards)
        + "</main></html>"
    ).encode()


def review(root, plan_name, plan_sha256, output):
    root = Path(root).absolute()
    require(
        root.is_dir() and root == root.resolve() and acquisition._sha(plan_sha256),
        "INVALID_ROOT_OR_PLAN_PIN",
    )
    body = acquisition._read(safe(root, plan_name), MAX_PLAN)
    require(hashlib.sha256(body).hexdigest() == plan_sha256, "PLAN_SHA256_MISMATCH")
    plan = acquisition._json(body)
    acquisition._keys(
        plan,
        (
            "schema_id",
            "plan_id",
            "preparation_report",
            "prepared_manifest",
            "asset_bytes",
            "reserve_bytes",
            "annotations",
        ),
    )
    require(
        plan["schema_id"] == SCHEMA and acquisition._identifier(plan["plan_id"]), "INVALID_PLAN"
    )
    require(
        acquisition._integer(plan["asset_bytes"], 1, MAX_ASSETS)
        and acquisition._integer(plan["reserve_bytes"], 0, 64 * 1024**3),
        "INVALID_BUDGET",
    )
    source = _load(root, plan["preparation_report"])
    require(
        type(source) is dict
        and source.get("schema_id") == preparation.SCHEMA
        and source.get("inputs_stable") is True
        and type(source.get("status")) is str
        and source["status"] in {"passed", "failed"}
        and type(source.get("records")) is list
        and 1 <= len(source["records"]) <= 32,
        "PREPARATION_REPORT_INVALID",
    )
    prepared = metadata.validate_manifest(_load(root, plan["prepared_manifest"]))
    original_pin = source["inputs"]["metadata_manifest"]
    original = metadata.validate_manifest(_load(root, original_pin))
    original["manifest_id"] = prepared["manifest_id"]
    require(len(original["records"]) == len(source["records"]), "SOURCE_RECORD_COUNT_MISMATCH")
    for record, row in zip(original["records"], source["records"], strict=True):
        require(
            record["sample_id"] == row["sample_id"] and type(row["preprocessing_observed"]) is bool,
            "SOURCE_RECORD_ORDER_MISMATCH",
        )
        if row["preprocessing_observed"]:
            record["exposure"]["preprocessing"] = "yes"
    require(prepared == original, "PREPARED_K5_SEMANTICS_CHANGED")
    require(
        type(plan["annotations"]) is list
        and [r.get("sample_id") for r in plan["annotations"] if type(r) is dict]
        == [r["sample_id"] for r in source["records"]]
        and len(plan["annotations"]) == len(source["records"]),
        "ANNOTATION_LEDGER_MISMATCH",
    )
    for item in plan["annotations"]:
        _annotation(item)
    target = safe(root, output)
    require(
        output.startswith("output/research/") and not target.exists(),
        "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY",
    )
    require(
        shutil.disk_usage(root).free >= plan["asset_bytes"] + plan["reserve_bytes"] + MAX_JSON,
        "INSUFFICIENT_SPACE",
    )
    target.mkdir(parents=True, exist_ok=False)
    budget, image_pins = _Budget(plan["asset_bytes"]), []
    rows = [
        _one(root, item, src, k5, output, budget, image_pins)
        for item, src, k5 in zip(
            plan["annotations"], source["records"], prepared["records"], strict=True
        )
    ]
    stable = True
    try:
        require(
            hashlib.sha256(acquisition._read(safe(root, plan_name), MAX_PLAN)).hexdigest()
            == plan_sha256,
            "INPUT_CHANGED",
        )
        for pin in [
            plan["preparation_report"],
            plan["prepared_manifest"],
            original_pin,
            *image_pins,
        ]:
            preparation._verify(root, pin, MAX_IMAGE_BYTES if pin in image_pins else MAX_JSON)
    except (Error, OSError):
        stable = False
    content = _html(rows)
    require(len(content) <= MAX_JSON, "HTML_TOO_LARGE")
    with safe(root, output + "/index.html").open("xb") as stream:
        stream.write(content)
    report = {
        "schema_id": SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_path": plan_name,
        "plan_sha256": plan_sha256,
        "producer_sha256": PRODUCER_SHA256,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "inputs_stable": stable,
        "inputs": {
            "preparation_report": plan["preparation_report"],
            "prepared_manifest": plan["prepared_manifest"],
            "original_manifest": original_pin,
        },
        "records": rows,
        "summary": {
            "requested": len(rows),
            "transformed": sum(r["status"] == "transformed" for r in rows),
            "failed": sum(r["status"] == "failed" for r in rows),
        },
        "asset_bytes_reserved": budget.used,
        "asset_inventory": budget.files,
        "point_schema_verified": False,
        "annotation_quality_assessed": False,
        "human_review_completed": False,
        "dataset_adapter_verified": False,
        "split_assignment_performed": False,
        "model_inference_run": False,
        **acquisition.FLAGS,
    }
    report["status"] = "passed" if stable and report["summary"]["failed"] == 0 else "failed"
    preparation._write_json(root, output + "/report.json", report)
    return {**report, "receipt": output + "/report.json", "index": output + "/index.html"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = review(args.root, args.plan, args.plan_sha256, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **acquisition.FLAGS}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
