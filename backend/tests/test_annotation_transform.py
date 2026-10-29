"""Affine centers/edges, immutable K5 lineage, complete ledgers and SVG geometry."""

import base64
import copy
import hashlib
import importlib
import json
import math
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
data = importlib.import_module("preprocessing.annotation_transform")
prep = importlib.import_module("preprocessing.archive_preparation")
metadata = importlib.import_module("preprocessing.dataset_manifest")
PREFIX = "output/research/annotations-fixture"
OUTPUT = PREFIX + "/review"
NAMES = ["subject_left", "subject_right", "unknown", "occluded"]


def sha(body):
    return hashlib.sha256(body).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def pin(root, path):
    body = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "bytes": len(body), "sha256": sha(body)}


def case(root, *, orientation=1, failed=False):
    """A synthetic preparation-report stub, with genuine normalized image bytes."""
    base = root / PREFIX
    base.mkdir(parents=True)
    width, height = 6, 4
    original = Image.new("RGB", (width, height))
    original.putdata([(x * 30, y * 40, x + y) for y in range(height) for x in range(width)])
    operations = {
        1: None,
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }
    image = (
        original.copy()
        if operations[orientation] is None
        else original.transpose(operations[orientation])
    )
    image_path = base / "normalized.png"
    image.save(image_path)
    source_size, normalized_size = [width, height], list(image.size)
    original.close()
    image.close()
    image_path.chmod(stat.S_IREAD)
    record = {
        "sample_id": "synthetic:0",
        "dataset_id": "synthetic",
        "file": {"path": PREFIX + "/raw/original.png", "bytes": 10, "sha256": "0" * 64},
        "subject_id": None,
        "linked_subject_id": None,
        "parent_id": None,
        "kind": "original",
        "use": "calibration_research",
        "age": metadata.age_label("unknown"),
        "age_source": "unknown",
        "exposure": dict.fromkeys(
            ["preprocessing", "model_selection", "result_inspection"], "unknown"
        ),
        "processing": {"status": "failed", "reason": "NO_FACE"},
    }
    manifest = {
        "schema_id": metadata.SCHEMA,
        "schema_version": 1,
        "task": metadata.TASK,
        "manifest_id": "synthetic-original",
        "origin": None,
        "datasets": [
            {
                "dataset_id": "synthetic",
                "version": "v1",
                "purpose_registration": {"status": "unresolved", "evidence": None},
                "identity_review": {"status": "pending", "evidence": None},
                "training_overlap": {"status": "unknown", "evidence": None},
                "near_duplicate_review": {"status": "pending", "evidence": None},
            }
        ],
        "records": [record],
    }
    original_path = base / "original-manifest.json"
    save(original_path, manifest)
    prepared = copy.deepcopy(manifest)
    prepared["manifest_id"] = "synthetic-prepared"
    prepared["records"][0]["exposure"]["preprocessing"] = "yes"
    prepared_path = base / "prepared-manifest.json"
    save(prepared_path, prepared)
    source_row = {
        "sample_id": "synthetic:0",
        "status": "failed" if failed else "decoded",
        "error_code": "IMAGE_DECODE_FAILED" if failed else None,
        "preprocessing_observed": True,
        "source_size": source_size,
        "normalized_size": normalized_size,
        "source_orientation": orientation,
        "original_to_normalized": prep.orientation_matrix(orientation, width, height),
        "normalized": None if failed else pin(root, image_path),
    }
    report = {
        "schema_id": prep.SCHEMA,
        "status": "failed" if failed else "passed",
        "inputs_stable": True,
        "inputs": {"metadata_manifest": pin(root, original_path)},
        "records": [source_row],
    }
    report_path = base / "preparation-report.json"
    save(report_path, report)
    item = {
        "sample_id": "synthetic:0",
        "point_schema": {"id": "synthetic-v1", "names": NAMES[:], "laterality": "subject"},
        "points": [
            {"name": NAMES[0], "xy": [0, 0], "visibility": "visible"},
            {"name": NAMES[1], "xy": [5, 3], "visibility": "visible"},
            {"name": NAMES[2], "xy": None, "visibility": "unknown"},
            {"name": NAMES[3], "xy": [2, 1], "visibility": "occluded"},
        ],
        "bbox": {"format": "xywh_edges", "values": [0, 0, width, height]},
        "alignment": {
            "crop_edges": [0, 0, *normalized_size],
            "output_size": normalized_size[:],
            "resample": "nearest",
        },
    }
    plan = {
        "schema_id": data.SCHEMA,
        "plan_id": "synthetic-v1",
        "preparation_report": pin(root, report_path),
        "prepared_manifest": pin(root, prepared_path),
        "asset_bytes": 1024**2,
        "reserve_bytes": 0,
        "annotations": [item],
    }
    return {
        "root": root,
        "plan": plan,
        "report": report,
        "report_path": report_path,
        "prepared": prepared,
        "prepared_path": prepared_path,
        "image_path": image_path,
        "original_path": original_path,
    }


def run(c, output=OUTPUT):
    save(c["report_path"], c["report"])
    save(c["prepared_path"], c["prepared"])
    c["plan"]["preparation_report"] = pin(c["root"], c["report_path"])
    c["plan"]["prepared_manifest"] = pin(c["root"], c["prepared_path"])
    path = c["root"] / PREFIX / "plan.json"
    save(path, c["plan"])
    return data.review(
        c["root"], path.relative_to(c["root"]).as_posix(), sha(path.read_bytes()), output
    )


@pytest.fixture(autouse=True)
def writable_cleanup(tmp_path):
    yield
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("orientation", range(1, 9))
def test_exif_centers_and_box_edges_have_different_translation(tmp_path, orientation):
    c = case(tmp_path, orientation=orientation)
    result = run(c)
    assert result["status"] == "passed"
    row = result["records"][0]
    assert [p["name"] for p in row["points"]] == NAMES
    assert row["points"][2]["xy"] is None and row["points"][2]["in_frame"] is None
    assert row["points"][3]["visibility"] == "occluded"
    assert row["bbox"]["enclosing_xyxy_edges"] == [0, 0, *row["output_size"]]
    assert row["roundtrip_max_abs_error"] < 1e-10
    assert row["k5"] == c["prepared"]["records"][0]
    assert row["k5"]["processing"] == {"status": "failed", "reason": "NO_FACE"}
    assert row["k5"]["age"]["kind"] == "unknown"
    assert row["semantic_reindexing_performed"] is False
    assert all(result[k] is False for k in data.acquisition.FLAGS)
    if orientation == 2:
        assert row["center_matrix"][0] == [-1, 0, 5]
        assert row["edge_matrix"][0] == [-1, 0, 6]


def test_half_pixel_crop_resize_matches_real_raster_blocks(tmp_path):
    c = case(tmp_path)
    c["plan"]["annotations"][0]["alignment"] = {
        "crop_edges": [1, 1, 5, 3],
        "output_size": [8, 4],
        "resample": "nearest",
    }
    row = run(c)["records"][0]
    assert row["center_matrix"] == [[2, 0, -1.5], [0, 2, -1.5], [0, 0, 1]]
    assert row["edge_matrix"] == [[2, 0, -2], [0, 2, -2], [0, 0, 1]]
    assert row["points"][3]["xy"] == [2.5, 0.5]
    assert row["points"][0]["in_frame"] is False
    with Image.open(tmp_path / row["assets"]["aligned"]["path"]) as image:
        assert image.size == (8, 4)
        for y in range(4):
            for x in range(8):
                sx, sy = x // 2 + 1, y // 2 + 1
                assert image.getpixel((x, y)) == (sx * 30, sy * 40, sx + sy)


@pytest.mark.parametrize(
    "matrix",
    [
        [[1, 0.5, 2], [0.25, 1, -3], [0, 0, 1]],
        [[0, -2, 7], [3, 0, 11], [0, 0, 1]],
        [[-1, 0, 7], [0, 1, 0], [0, 0, 1]],
    ],
)
def test_affine_composition_inverse_and_sheared_box_uses_all_corners(matrix):
    shift = [[1, 0, 4], [0, 1, -2], [0, 0, 1]]
    composed = data.compose(matrix, shift)
    for xy in [[0, 0], [3.25, -7.5], [100, 120]]:
        assert data.point(composed, xy) == pytest.approx(data.point(matrix, data.point(shift, xy)))
        assert data.point(data.inverse(composed), data.point(composed, xy)) == pytest.approx(xy)
    transformed = data.box(matrix, {"format": "xyxy_edges", "values": [0, 0, 4, 2]}, [32, 32])
    corners = transformed["polygon_edges"]
    assert len(corners) == 4
    assert transformed["enclosing_xyxy_edges"] == [
        min(p[0] for p in corners),
        min(p[1] for p in corners),
        max(p[0] for p in corners),
        max(p[1] for p in corners),
    ]


def test_clipping_does_not_replace_unclipped_geometry_or_visibility():
    result = data.box(data.IDENTITY, {"format": "xyxy_edges", "values": [-2, -1, 4, 3]}, [3, 2])
    assert result["enclosing_xyxy_edges"] == [-2, -1, 4, 3]
    assert result["clipped_xyxy_edges"] == [0, 0, 3, 2] and not result["fully_inside"]
    outside = data.box(data.IDENTITY, {"format": "xywh_edges", "values": [9, 9, 2, 2]}, [3, 2])
    assert outside["clipped_xyxy_edges"] is None


@pytest.mark.parametrize(
    "matrix",
    [
        [],
        [[1, 0], [0, 1]],
        [[1, 0, 0], [0, 0, 0], [0, 0, 1]],
        [[1, 0, 0], [0, 1, 0], [0.01, 0, 1]],
        [[True, 0, 0], [0, 1, 0], [0, 0, 1]],
        [[math.nan, 0, 0], [0, 1, 0], [0, 0, 1]],
        [[1, 0, 0], [0, math.inf, 0], [0, 0, 1]],
        [[1, 0, 0], [0, 1e-16, 0], [0, 0, 1]],
    ],
)
def test_bad_affines_rejected(matrix):
    with pytest.raises(data.Error):
        data.affine(matrix)


@pytest.mark.parametrize("xy", [[True, 0], [math.nan, 0], [math.inf, 0], [0], "0,1", [1e40, 0]])
def test_invalid_point_values_rejected(xy):
    with pytest.raises(data.Error):
        data.point(data.IDENTITY, xy)


@pytest.mark.parametrize(
    "box",
    [
        {"format": "xywh_edges", "values": [0, 0, 0, 2]},
        {"format": "xyxy_edges", "values": [2, 0, 1, 2]},
        {"format": "wider_implicit", "values": [0, 0, 2, 2]},
        {"format": "xyxy_edges", "values": [0, 0, math.inf, 2]},
    ],
)
def test_invalid_box_format_size_and_nonfinite_rejected(box):
    with pytest.raises(data.Error):
        data.box(data.IDENTITY, box, [4, 4])


def test_source_failure_preserved_without_image_read(tmp_path, monkeypatch):
    c = case(tmp_path, failed=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("failed source was decoded")

    monkeypatch.setattr(data.Image, "open", forbidden)
    result = run(c)
    assert result["summary"] == {"requested": 1, "transformed": 0, "failed": 1}
    row = result["records"][0]
    assert row["error_code"] == "SOURCE_PREPARATION_FAILED"
    assert row["source_error_code"] == "IMAGE_DECODE_FAILED"


def test_bad_crop_is_per_request_failure(tmp_path):
    c = case(tmp_path)
    c["plan"]["annotations"][0]["alignment"]["crop_edges"] = [-1, 0, 6, 4]
    result = run(c)
    assert result["records"][0]["error_code"] == "CROP_OUTSIDE_SOURCE"
    assert result["summary"]["failed"] == 1


def test_complete_ledger_cannot_omit_failed_source(tmp_path):
    c = case(tmp_path, failed=True)
    c["plan"]["annotations"] = []
    with pytest.raises(data.Error, match="ANNOTATION_LEDGER_MISMATCH"):
        run(c)
    assert not (tmp_path / OUTPUT).exists()


def test_k5_changed_label_or_failure_rejected_before_output(tmp_path):
    c = case(tmp_path)
    c["prepared"]["records"][0]["processing"] = {"status": "ok", "reason": None}
    with pytest.raises(data.Error, match="PREPARED_K5_SEMANTICS_CHANGED"):
        run(c)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize(
    "change",
    [
        "order",
        "null_visible",
        "known_not_annotated",
        "duplicate_name",
        "bad_visibility",
        "resample",
    ],
)
def test_schema_visibility_and_order_contract(tmp_path, change):
    c = case(tmp_path)
    item = c["plan"]["annotations"][0]
    if change == "order":
        item["points"].reverse()
    elif change == "null_visible":
        item["points"][0]["xy"] = None
    elif change == "known_not_annotated":
        item["points"][0]["visibility"] = "not_annotated"
    elif change == "duplicate_name":
        item["point_schema"]["names"][1] = NAMES[0]
    elif change == "bad_visibility":
        item["points"][0]["visibility"] = True
    else:
        item["alignment"]["resample"] = "implicit"
    with pytest.raises(data.Error):
        run(c)
    assert not (tmp_path / OUTPUT).exists()


def test_svg_embedded_bytes_centers_and_escaped_labels(tmp_path):
    c = case(tmp_path)
    c["plan"]["annotations"][0]["point_schema"]["names"][0] = '<script>alert("x")</script>'
    c["plan"]["annotations"][0]["points"][0]["name"] = '<script>alert("x")</script>'
    result = run(c)
    row = result["records"][0]
    path = tmp_path / row["assets"]["aligned_overlay"]["path"]
    xml = ET.fromstring(path.read_bytes())
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert not xml.findall("s:script", ns)
    circles = xml.findall("s:circle", ns)
    assert len(circles) == 3 and circles[0].attrib["cx"] == circles[0].attrib["cy"] == "0.5"
    href = xml.find("s:image", ns).attrib["href"]
    assert (
        base64.b64decode(href.split(",", 1)[1])
        == (tmp_path / row["assets"]["aligned"]["path"]).read_bytes()
    )
    assert "<script>" not in path.read_text()
    assert len(result["asset_inventory"]) == 3


def test_budget_failure_retains_written_asset_inventory(tmp_path):
    c = case(tmp_path)
    # Enough for the PNG, too little for an embedded SVG.
    c["plan"]["asset_bytes"] = 250
    result = run(c)
    assert (
        result["status"] == "failed"
        and result["records"][0]["error_code"] == "ASSET_BUDGET_EXCEEDED"
    )
    assert len(result["asset_inventory"]) == 1
    assert result["asset_inventory"][0]["status"] == "published"
    assert result["asset_bytes_reserved"] <= 250


def test_input_image_hash_and_orientation_drift_are_row_failures(tmp_path):
    c = case(tmp_path)
    c["report"]["records"][0]["original_to_normalized"][0][2] = 7
    result = run(c)
    assert result["records"][0]["error_code"] == "SOURCE_ORIENTATION_MATRIX_MISMATCH"


def test_new_output_refuses_overwrite(tmp_path):
    c = case(tmp_path)
    result = run(c)
    original = (tmp_path / result["receipt"]).read_bytes()
    with pytest.raises(data.Error, match="OUTPUT_MUST_BE_NEW"):
        run(c)
    assert (tmp_path / result["receipt"]).read_bytes() == original


def test_bilinear_option_uses_same_declared_geometry(tmp_path):
    c = case(tmp_path)
    c["plan"]["annotations"][0]["alignment"].update(output_size=[3, 2], resample="bilinear")
    row = run(c)["records"][0]
    assert row["status"] == "transformed"
    assert row["center_matrix"] == [[0.5, 0, -0.25], [0, 0.5, -0.25], [0, 0, 1]]


def test_mixed_ledger_preserves_failed_source_and_continues(tmp_path):
    c = case(tmp_path)
    original = json.loads(c["original_path"].read_text())
    second = copy.deepcopy(original["records"][0])
    second["sample_id"] = "synthetic:1"
    original["records"].append(second)
    save(c["original_path"], original)
    c["report"]["inputs"]["metadata_manifest"] = pin(tmp_path, c["original_path"])
    prepared_second = copy.deepcopy(second)
    prepared_second["exposure"]["preprocessing"] = "yes"
    c["prepared"]["records"].append(prepared_second)
    c["report"]["records"].append(
        {
            "sample_id": "synthetic:1",
            "status": "failed",
            "error_code": "IMAGE_DECODE_FAILED",
            "preprocessing_observed": True,
        }
    )
    c["report"]["status"] = "failed"
    item = copy.deepcopy(c["plan"]["annotations"][0])
    item["sample_id"] = "synthetic:1"
    c["plan"]["annotations"].append(item)
    result = run(c)
    assert result["summary"] == {"requested": 2, "transformed": 1, "failed": 1}
    assert [r["sample_id"] for r in result["records"]] == ["synthetic:0", "synthetic:1"]
    assert result["records"][1]["source_error_code"] == "IMAGE_DECODE_FAILED"


def test_late_source_image_drift_fails_batch_without_erasing_records(tmp_path, monkeypatch):
    c = case(tmp_path)
    original_one = data._one

    def drift(*args, **kwargs):
        result = original_one(*args, **kwargs)
        c["image_path"].chmod(stat.S_IREAD | stat.S_IWRITE)
        c["image_path"].write_bytes(b"drift")
        return result

    monkeypatch.setattr(data, "_one", drift)
    result = run(c)
    assert not result["inputs_stable"] and result["status"] == "failed"
    assert result["summary"] == {"requested": 1, "transformed": 1, "failed": 0}


def test_source_png_pin_failure_is_explicit(tmp_path):
    c = case(tmp_path)
    c["report"]["records"][0]["normalized"]["sha256"] = "0" * 64
    result = run(c)
    assert result["records"][0]["error_code"] == "INPUT_PIN_MISMATCH"
    assert not result["asset_inventory"]


def test_preparation_input_drift_is_rejected_before_output(tmp_path):
    c = case(tmp_path)
    c["report"]["inputs_stable"] = False
    with pytest.raises(data.Error, match="PREPARATION_REPORT_INVALID"):
        run(c)
    assert not (tmp_path / OUTPUT).exists()


def test_cli_exit_codes_and_source_digests_unchanged(tmp_path):
    c = case(tmp_path)
    run(c)
    plan_path = tmp_path / PREFIX / "plan.json"
    checksum = sha(plan_path.read_bytes())

    # First use a new output name; the immutable source plan does not bind output names.
    def cli(expected, output):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "preprocessing.annotation_transform",
                "--root",
                str(tmp_path),
                "--plan",
                plan_path.relative_to(tmp_path).as_posix(),
                "--plan-sha256",
                expected,
                "--output-dir",
                output,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )

    before = {
        p: p.read_bytes()
        for p in [c["report_path"], c["prepared_path"], c["original_path"], c["image_path"]]
    }
    success = cli(checksum, PREFIX + "/cli-output")
    assert success.returncode == 0 and json.loads(success.stdout)["status"] == "passed"
    rejected = cli("0" * 64, PREFIX + "/rejected")
    assert rejected.returncode == 2 and json.loads(rejected.stdout)["status"] == "rejected"
    assert not success.stderr and not rejected.stderr
    assert all(p.read_bytes() == value for p, value in before.items())
