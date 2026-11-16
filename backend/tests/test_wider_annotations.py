"""WIDER FACE bbx_gt parsing, flag/out-of-frame policy, YOLO round trip and K5 ledger.

All inputs are synthetic; no real WIDER FACE file is read or downloaded.
"""

import hashlib
import importlib
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
wider = importlib.import_module("preprocessing.wider_annotations")
transform = importlib.import_module("preprocessing.annotation_transform")
metadata = importlib.import_module("preprocessing.dataset_manifest")
GT = "data/wider_face_split/wider_face_train_bbx_gt.txt"
IMAGES = "data/WIDER_train/images"
OUTPUT = "output/research/wider-fixture"


def sha(body):
    return hashlib.sha256(body).hexdigest()


def face(x, y, w, h, blur=0, expression=0, illumination=0, invalid=0, occlusion=0, pose=0):
    return f"{x} {y} {w} {h} {blur} {expression} {illumination} {invalid} {occlusion} {pose} "


# Mirrors the official layout, including trailing spaces and the zero-face placeholder row.
SAMPLE = "\n".join(
    [
        "0--Parade/0_Parade_marchingband_1_1.jpg",
        "4",
        face(10, 20, 30, 40),
        face(50, 10, 20, 25, blur=2, occlusion=1),
        face(5, 5, 8, 8, invalid=1),
        face(-6, 70, 20, 20, blur=1),
        "0--Parade/0_Parade_Parade_0_2.jpg",
        "0",
        face(0, 0, 0, 0),
        "1--Handshaking/1_Handshaking_3.png",
        "2",
        face(90, 70, 50, 50),
        face(500, 500, 10, 10),
    ]
)
SIZES = {
    "0--Parade/0_Parade_marchingband_1_1.jpg": (100, 80),
    "0--Parade/0_Parade_Parade_0_2.jpg": (64, 48),
    "1--Handshaking/1_Handshaking_3.png": (120, 90),
}


def build(root, text=SAMPLE, sizes=SIZES, orientation=None):
    body = text.encode()
    gt = root / GT
    gt.parent.mkdir(parents=True, exist_ok=True)
    gt.write_bytes(body)
    for name, size in sizes.items():
        path = root / IMAGES / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", size, (90, 120, 150))
        if orientation is not None and path.suffix == ".jpg":
            exif = Image.Exif()
            exif[0x0112] = orientation
            image.save(path, exif=exif)
        else:
            image.save(path)
    return sha(body)


def run(root, digest, **kwargs):
    return wider.convert(root, GT, digest, IMAGES, "train", OUTPUT, **kwargs)


# --- parsing -----------------------------------------------------------------


def test_parse_official_layout_and_zero_face_placeholder():
    entries = wider.parse_bbx_gt(SAMPLE.replace("\n", "\r\n") + "\n\n")
    assert [e["image"] for e in entries] == list(SIZES)
    assert [e["declared_faces"] for e in entries] == [4, 0, 2]
    assert [len(e["faces"]) for e in entries] == [4, 0, 2]
    first = entries[0]["faces"]
    assert first[0] == {
        "index": 0,
        "line": 3,
        "xywh": [10, 20, 30, 40],
        "blur": 0,
        "expression": 0,
        "illumination": 0,
        "invalid": 0,
        "occlusion": 0,
        "pose": 0,
    }
    assert first[1]["blur"] == 2 and first[1]["occlusion"] == 1
    assert first[2]["invalid"] == 1
    assert entries[1]["line"] == 7 and entries[2]["line"] == 10


def test_parse_accepts_utf8_bom_through_convert(tmp_path):
    digest = build(tmp_path, text="\ufeff" + SAMPLE)
    assert run(tmp_path, digest)["summary"]["images"] == 3


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "GT_EMPTY"),
        ("\n \n", "GT_EMPTY"),
        ("a/b.jpg", "GT_TRUNCATED_BLOCK"),
        ("a/b.jpg\n2\n" + face(1, 1, 2, 2), "GT_TRUNCATED_BLOCK"),
        ("a/b.jpg\n0", "GT_TRUNCATED_BLOCK"),
        ("a/b.jpg\n-1\n" + face(1, 1, 2, 2), "GT_FACE_COUNT_INVALID"),
        ("a/b.jpg\n1.0\n" + face(1, 1, 2, 2), "GT_FACE_COUNT_INVALID"),
        ("a/b.jpg\none\n" + face(1, 1, 2, 2), "GT_FACE_COUNT_INVALID"),
        ("a/b.jpg\n1 2\n" + face(1, 1, 2, 2), "GT_FACE_COUNT_INVALID"),
        ("a/b.jpg\n5000\n", "GT_FACE_COUNT_INVALID"),
        ("a/b.jpg\n1\n1 1 2 2 0 0 0 0 0", "GT_FACE_ROW_INVALID"),
        ("a/b.jpg\n1\n1 1 2 2 0 0 0 0 0 0 0", "GT_FACE_ROW_INVALID"),
        ("a/b.jpg\n1\n1.5 1 2 2 0 0 0 0 0 0", "GT_FACE_ROW_INVALID"),
        ("a/b.jpg\n1\n1 1 2 2 0 0 0 0 0 nan", "GT_FACE_ROW_INVALID"),
        ("a/b.jpg\n0\n" + face(1, 0, 0, 0), "GT_ZERO_FACE_PLACEHOLDER_INVALID"),
        ("a/b.jpg\n1\n" + face(1, 1, 2, 2, blur=3), "GT_ATTRIBUTE_OUT_OF_RANGE"),
        ("a/b.jpg\n1\n" + face(1, 1, 2, 2, invalid=2), "GT_ATTRIBUTE_OUT_OF_RANGE"),
        ("a/b.jpg\n1\n" + face(1, 1, 2, 2, occlusion=-1), "GT_ATTRIBUTE_OUT_OF_RANGE"),
        ("a/b.jpg\n1\n" + face(1, 1, 2, 2, pose=2), "GT_ATTRIBUTE_OUT_OF_RANGE"),
        ("a/b.jpg\n0\n" + face(0, 0, 0, 0) + "\na/b.jpg\n0\n" + face(0, 0, 0, 0), "GT_DUPLICATE"),
        ("a/b.jpg\n0\n" + face(0, 0, 0, 0) + "\na/B.png\n0\n" + face(0, 0, 0, 0), "STEM"),
        ("/abs/b.jpg\n0\n" + face(0, 0, 0, 0), "GT_IMAGE_PATH_INVALID"),
        ("a/../b.jpg\n0\n" + face(0, 0, 0, 0), "GT_IMAGE_PATH_INVALID"),
        ("a\\b.jpg\n0\n" + face(0, 0, 0, 0), "GT_IMAGE_PATH_INVALID"),
        ("a/b.gif\n0\n" + face(0, 0, 0, 0), "GT_IMAGE_PATH_INVALID"),
        ("12\n0\n" + face(0, 0, 0, 0), "GT_IMAGE_PATH_INVALID"),
        ("a/b.jpg\n\n1\n" + face(1, 1, 2, 2), "GT_FACE_COUNT_INVALID"),
    ],
)
def test_malformed_input_rejects_whole_file_with_line(text, code):
    with pytest.raises(wider.Error, match=code):
        wider.parse_bbx_gt(text)


def test_parse_rejects_non_text():
    with pytest.raises(wider.Error, match="GT_NOT_TEXT"):
        wider.parse_bbx_gt(b"a/b.jpg\n0\n")


def test_malformed_error_reports_line_number():
    text = SAMPLE.replace(face(50, 10, 20, 25, blur=2, occlusion=1), "50 10 20 25 2 0 0 0 1")
    with pytest.raises(wider.Error, match=r"GT_FACE_ROW_INVALID:line=4$"):
        wider.parse_bbx_gt(text)


# --- flag and geometry policy -------------------------------------------------


def faces_of(text):
    return [f for e in wider.parse_bbx_gt(text) for f in e["faces"]]


def test_invalid_flag_is_dropped_and_blur_is_kept_by_default():
    result = wider.convert_faces(faces_of(SAMPLE)[:4], [100, 80])
    decisions = [(f["decision"], f["reason"]) for f in result["ledger"]]
    assert decisions == [
        ("kept", None),
        ("kept", None),
        ("dropped", "INVALID_FLAG"),
        ("kept", None),
    ]
    assert len(result["lines"]) == 3
    assert result["ledger"][1]["blur"] == 2 and result["ledger"][1]["clipped"] is False


@pytest.mark.parametrize(("max_blur", "kept"), [(2, [0, 1, 2]), (1, [0, 1]), (0, [0])])
def test_blur_threshold_policy(max_blur, kept):
    rows = faces_of("a/b.jpg\n3\n" + "\n".join(face(10, 10, 5, 5, blur=b) for b in range(3)))
    result = wider.convert_faces(rows, [64, 64], max_blur=max_blur)
    assert [f["blur"] for f in result["ledger"] if f["decision"] == "kept"] == kept
    assert {f["reason"] for f in result["ledger"] if f["decision"] == "dropped"} <= {
        "BLUR_ABOVE_POLICY"
    }


def test_invalid_flag_wins_over_blur_policy():
    rows = faces_of("a/b.jpg\n1\n" + face(10, 10, 5, 5, blur=2, invalid=1))
    result = wider.convert_faces(rows, [64, 64], max_blur=0)
    assert result["ledger"][0]["reason"] == "INVALID_FLAG"


@pytest.mark.parametrize("value", [-1, 3, 1.0, True, "2", None])
def test_blur_policy_value_is_validated(value):
    with pytest.raises(wider.Error, match="INVALID_BLUR_POLICY"):
        wider.convert_faces([], [10, 10], max_blur=value)


@pytest.mark.parametrize(
    ("xywh", "expected"),
    [
        ([-6, 70, 20, 20], [0, 70, 14, 80]),  # crosses left and bottom edges
        ([90, -5, 30, 10], [90, 0, 100, 5]),  # crosses right and top edges
        ([-10, -10, 200, 200], [0, 0, 100, 80]),  # covers the whole frame
    ],
)
def test_partially_outside_boxes_are_clipped_to_frame(xywh, expected):
    rows = faces_of("a/b.jpg\n1\n" + face(*xywh))
    result = wider.convert_faces(rows, [100, 80])
    row = result["ledger"][0]
    assert row["decision"] == "kept" and row["clipped"] is True
    assert row["clipped_xyxy_edges"] == expected
    values = wider.parse_yolo_line(result["lines"][0])
    assert all(0 <= v <= 1 for v in values)
    assert (
        max(abs(a - b) for a, b in zip(wider.from_yolo(values, [100, 80]), expected, strict=True))
        <= 1e-3
    )


@pytest.mark.parametrize(
    ("xywh", "reason"),
    [
        ([100, 10, 5, 5], "OUT_OF_FRAME"),  # starts exactly at the right edge
        ([10, 80, 5, 5], "OUT_OF_FRAME"),
        ([-20, 10, 20, 5], "OUT_OF_FRAME"),  # ends exactly at the left edge
        ([500, 500, 10, 10], "OUT_OF_FRAME"),
        ([10, 10, 0, 5], "DEGENERATE_BOX"),
        ([10, 10, 5, 0], "DEGENERATE_BOX"),
        ([10, 10, -3, 5], "DEGENERATE_BOX"),
    ],
)
def test_outside_and_degenerate_boxes_are_dropped_with_reason(xywh, reason):
    result = wider.convert_faces(faces_of("a/b.jpg\n1\n" + face(*xywh)), [100, 80])
    assert result["lines"] == []
    assert result["ledger"][0]["decision"] == "dropped"
    assert result["ledger"][0]["reason"] == reason
    assert result["roundtrip_max_abs_error_px"] is None


def test_box_geometry_matches_p02_edge_contract():
    rows = faces_of("a/b.jpg\n1\n" + face(10, 20, 30, 40))
    row = wider.convert_faces(rows, [100, 80])["ledger"][0]
    p02 = transform.box(
        transform.IDENTITY, {"format": "xywh_edges", "values": [10, 20, 30, 40]}, [100, 80]
    )
    assert row["clipped_xyxy_edges"] == p02["clipped_xyxy_edges"] == [10, 20, 40, 60]
    assert row["yolo"] == [0.25, 0.5, 0.3, 0.5]


@pytest.mark.parametrize("size", [[0, 10], [10, 0], [8193, 10], [5000, 5000], [10.0, 10]])
def test_image_size_limits_follow_p02(size):
    with pytest.raises(wider.Error, match="RASTER_SIZE_LIMIT"):
        wider.convert_faces([], size)


# --- YOLO text and round trip ---------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "1 0.5 0.5 0.1 0.1",
        "0 0.5 0.5 0.1",
        "0 0.5 0.5 0.1 0.1 0.1",
        "0 1.5 0.5 0.1 0.1",
        "0 0.5 0.5 0 0.1",
        "0 0.5 0.5 0.1 -0.1",
        "0 a 0.5 0.1 0.1",
    ],
)
def test_yolo_line_contract(line):
    with pytest.raises(wider.Error, match="YOLO_"):
        wider.parse_yolo_line(line)


def test_yolo_line_format():
    assert wider.yolo_line([0.25, 0.5, 0.3, 0.5]) == "0 0.250000 0.500000 0.300000 0.500000"


def roundtrip_errors(rng, count):
    """Pixel -> written YOLO text -> pixel, against the P02 clipped pixel edges."""
    worst = 0.0
    sizes = [(1, 1), (7, 5), (640, 480), (1024, 683), (1024, 1024), (8192, 2048), (2048, 8192)]
    for _ in range(count):
        width, height = rng.choice(sizes)
        x1, y1 = rng.randint(-50, width), rng.randint(-50, height)
        w, h = rng.randint(1, width + 60), rng.randint(1, height + 60)
        rows = faces_of("a/b.jpg\n1\n" + face(x1, y1, w, h))
        result = wider.convert_faces(rows, [width, height])
        row = result["ledger"][0]
        if row["decision"] != "kept":
            assert row["reason"] == "OUT_OF_FRAME"
            continue
        back = wider.from_yolo(wider.parse_yolo_line(result["lines"][0]), [width, height])
        error = max(abs(a - b) for a, b in zip(back, row["clipped_xyxy_edges"], strict=True))
        if row["clipped"] is False:  # fully inside: compare with the raw WIDER box too
            raw = [x1, y1, x1 + w, y1 + h]
            error = max(error, *(abs(a - b) for a, b in zip(back, raw, strict=True)))
        assert error <= row["roundtrip_abs_error_px"] + 1e-9
        worst = max(worst, error)
    return worst


def test_roundtrip_error_is_within_half_pixel():
    worst = roundtrip_errors(random.Random(20261116), 20_000)
    assert worst <= wider.MAX_ROUNDTRIP_PX
    # Six decimals: |d edge| <= (0.5e-6 + 0.25e-6) * 8192 px ~= 6.1e-3 px.
    assert worst <= 0.75e-6 * 8192 + 1e-9


def test_roundtrip_guard_rejects_excess_error(monkeypatch):
    monkeypatch.setattr(wider, "YOLO_DECIMALS", 0)
    rows = faces_of("a/b.jpg\n1\n" + face(10, 20, 30, 40))
    with pytest.raises(wider.Error, match="ROUNDTRIP_ERROR_EXCEEDED|YOLO_RANGE"):
        wider.convert_faces(rows, [100, 80])


# --- end to end with K5 ledger ------------------------------------------------------


def test_convert_writes_labels_report_and_unassigned_k5_manifest(tmp_path):
    digest = build(tmp_path)
    report = run(tmp_path, digest)
    assert report["status"] == "passed" and report["inputs_stable"] is True
    summary = report["summary"]
    assert summary == {
        "images": 3,
        "converted": 3,
        "failed": 0,
        "failed_by_code": {},
        "zero_face_images": 1,
        "faces_declared": 6,
        "faces_kept": 4,
        "faces_clipped": 2,
        "faces_dropped_by_reason": {"INVALID_FLAG": 1, "OUT_OF_FRAME": 1},
        "faces_not_processed": 0,
        "k5_records": 3,
        "roundtrip_max_abs_error_px": summary["roundtrip_max_abs_error_px"],
    }
    assert summary["roundtrip_max_abs_error_px"] <= wider.MAX_ROUNDTRIP_PX
    labels = tmp_path / OUTPUT / "labels"
    first = (labels / "0--Parade/0_Parade_marchingband_1_1.txt").read_text().splitlines()
    assert first[0] == "0 0.250000 0.500000 0.300000 0.500000"
    assert len(first) == 3
    assert (labels / "0--Parade/0_Parade_Parade_0_2.txt").read_bytes() == b""
    third = (labels / "1--Handshaking/1_Handshaking_3.txt").read_text().splitlines()
    assert third == ["0 0.875000 0.888889 0.250000 0.222222"]

    saved = json.loads((tmp_path / OUTPUT / "report.json").read_text())
    assert saved["summary"] == summary and saved["split_assignment_performed"] is False
    assert saved["policy"]["invalid"] == "drop" and saved["policy"]["max_blur_kept"] == 2
    rows = saved["records"]
    assert rows[1]["declared_faces"] == 0 and rows[1]["faces"] == []

    manifest_path = tmp_path / OUTPUT / "manifest.json"
    manifest = metadata.validate_manifest(json.loads(manifest_path.read_text()))
    assert manifest["origin"] == {"path": GT, "bytes": len(SAMPLE.encode()), "sha256": digest}
    assert [r["sample_id"] for r in manifest["records"]] == [
        "wider-train:0--Parade:0_Parade_marchingband_1_1",
        "wider-train:0--Parade:0_Parade_Parade_0_2",
        "wider-train:1--Handshaking:1_Handshaking_3",
    ]
    assert {r["use"] for r in manifest["records"]} == {"unassigned"}
    assert {r["processing"]["status"] for r in manifest["records"]} == {"not_checked"}
    for record in manifest["records"]:
        path = tmp_path / record["file"]["path"]
        assert record["file"]["sha256"] == sha(path.read_bytes())
    audit = json.loads((tmp_path / OUTPUT / "audit.json").read_text())
    assert audit["status"] == report["k5_audit_status"]
    assert "FORMAL_SPLITS_NOT_DEFINED" in {f["code"] for f in audit["findings"]}


def test_label_pins_match_written_files(tmp_path):
    report = run(tmp_path, build(tmp_path))
    for row in report["records"]:
        body = (tmp_path / row["label"]["path"]).read_bytes()
        assert row["label"] == {
            "path": row["label"]["path"],
            "bytes": len(body),
            "sha256": sha(body),
        }


def test_blur_policy_is_recorded_end_to_end(tmp_path):
    report = run(tmp_path, build(tmp_path), max_blur=1)
    assert report["policy"]["max_blur_kept"] == 1
    assert report["summary"]["faces_dropped_by_reason"] == {
        "BLUR_ABOVE_POLICY": 1,
        "INVALID_FLAG": 1,
        "OUT_OF_FRAME": 1,
    }


def test_missing_and_rotated_images_fail_per_row_without_hiding_others(tmp_path):
    sizes = dict(SIZES)
    sizes.pop("1--Handshaking/1_Handshaking_3.png")
    digest = build(tmp_path, sizes=sizes, orientation=6)
    report = run(tmp_path, digest)
    assert report["status"] == "failed"
    codes = [r["error_code"] for r in report["records"]]
    assert codes == ["EXIF_ORIENTATION_NOT_IDENTITY"] * 2 + ["IMAGE_MISSING"]
    assert report["summary"]["faces_not_processed"] == 6
    manifest = json.loads((tmp_path / OUTPUT / "manifest.json").read_text())
    assert len(manifest["records"]) == 2  # a missing image has no file to pin
    assert {r["processing"]["status"] for r in manifest["records"]} == {"failed"}
    assert not (tmp_path / OUTPUT / "labels").exists()


def test_corrupt_image_is_a_row_failure(tmp_path):
    digest = build(tmp_path)
    (tmp_path / IMAGES / "0--Parade/0_Parade_Parade_0_2.jpg").write_bytes(b"not an image")
    report = run(tmp_path, digest)
    assert [r["error_code"] for r in report["records"]] == [None, "IMAGE_UNREADABLE", None]
    assert report["status"] == "failed"


def test_all_images_missing_writes_report_without_manifest(tmp_path):
    digest = build(tmp_path, sizes={})
    report = run(tmp_path, digest)
    assert report["status"] == "failed" and report["k5_manifest"] is None
    assert not (tmp_path / OUTPUT / "manifest.json").exists()


def test_input_change_after_hashing_marks_report_unstable(tmp_path, monkeypatch):
    digest = build(tmp_path)
    original = wider.convert_faces

    def mutate(*args, **kwargs):
        # The first image is already hashed when its faces are converted.
        (tmp_path / IMAGES / "0--Parade/0_Parade_marchingband_1_1.jpg").write_bytes(b"changed")
        return original(*args, **kwargs)

    monkeypatch.setattr(wider, "convert_faces", mutate)
    report = run(tmp_path, digest)
    assert report["inputs_stable"] is False and report["status"] == "failed"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"gt_sha256": "0" * 64}, "GT_SHA256_MISMATCH"),
        ({"gt_sha256": "xyz"}, "INVALID_ROOT_OR_GT_PIN"),
        ({"split": "test"}, "INVALID_SPLIT"),
        ({"output": "output/elsewhere"}, "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY"),
        ({"images_dir": "../images"}, "INVALID_PATH"),
        ({"max_blur": 5}, "INVALID_BLUR_POLICY"),
    ],
)
def test_convert_rejects_bad_arguments_before_writing(tmp_path, kwargs, code):
    digest = build(tmp_path)
    args = {
        "gt_name": GT,
        "gt_sha256": digest,
        "images_dir": IMAGES,
        "split": "train",
        "output": OUTPUT,
        **kwargs,
    }
    max_blur = args.pop("max_blur", 2)
    with pytest.raises(wider.Error, match=code):
        wider.convert(tmp_path, **args, max_blur=max_blur)
    assert not (tmp_path / "output").exists()


def test_existing_output_is_never_overwritten(tmp_path):
    digest = build(tmp_path)
    run(tmp_path, digest)
    with pytest.raises(wider.Error, match="OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY"):
        run(tmp_path, digest)


def test_malformed_gt_rejects_before_any_output(tmp_path):
    digest = build(tmp_path, text=SAMPLE + "\nbroken/path.jpg\n2\n" + face(1, 1, 2, 2))
    with pytest.raises(wider.Error, match="GT_TRUNCATED_BLOCK"):
        run(tmp_path, digest)
    assert not (tmp_path / "output").exists()


def test_split_assignment_is_never_performed(tmp_path):
    report = run(tmp_path, build(tmp_path))
    assert report["split_assignment_performed"] is False
    assert report["policy"]["k5_use"] == "unassigned"
    assert report["formal_dataset_ready"] is False and report["training_authorized"] is False
    source = (ROOT / "preprocessing" / "wider_annotations.py").read_text()
    assert "split_freeze" not in source


# --- CLI ----------------------------------------------------------------------------


def cli(root, *extra):
    return [
        "--root",
        str(root),
        "--gt",
        GT,
        "--images-dir",
        IMAGES,
        "--split",
        "train",
        "--output-dir",
        OUTPUT,
        *extra,
    ]


def test_cli_passed_failed_and_rejected_exit_codes(tmp_path, capsys):
    digest = build(tmp_path)
    assert wider.main(cli(tmp_path, "--gt-sha256", digest)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert wider.main(cli(tmp_path, "--gt-sha256", digest)) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["status"] == "rejected"
    assert rejected["error_code"] == "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY"
    (tmp_path / IMAGES / "0--Parade/0_Parade_Parade_0_2.jpg").unlink()
    args = cli(tmp_path, "--gt-sha256", digest)
    args[args.index(OUTPUT)] = OUTPUT + "-2"
    assert wider.main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_cli_runs_as_module(tmp_path):
    digest = build(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "preprocessing.wider_annotations", *cli(tmp_path)]
        + ["--gt-sha256", digest],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["summary"]["faces_kept"] == 4
