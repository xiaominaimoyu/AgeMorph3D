"""AgeDB official filename parsing, local statistics, K5 ledger and safe output.

All inputs are synthetic file names and tiny generated images in temporary folders; no
AgeDB archive, mirror or dump is read or downloaded.
"""

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
agedb = importlib.import_module("preprocessing.agedb_filenames")
metadata = importlib.import_module("preprocessing.dataset_manifest")
IMAGES = "data/datasets/agedb"
OUTPUT = "output/research/agedb-fixture"
LEAVES = {"stats.json", "rejected.json", "manifest.json", "audit.json"}

# Synthetic people; "Test_Subject_01" exercises underscores inside a name.
SAMPLE = {
    "0_AlphaPerson_19_f.jpg": (300, 200),
    "1_AlphaPerson_20_f.jpg": (200, 300),
    "2_AlphaPerson_49_f.jpg": (127, 400),
    "3_AlphaPerson_70_f.jpg": (128, 128),
    "4_Test_Subject_01_40_m.jpg": (64, 90),
    "5_Test_Subject_01_71_m.jpg": (1024, 2048),
    "6_Test_Subject_01_69_m.jpg": (512, 512),
    "7_BetaPerson_30_m.jpg": (63, 63),
    "8_BetaPerson_60_m.jpg": (256, 300),
}


def sha(body):
    return hashlib.sha256(body).hexdigest()


def image(path, size=(32, 32), fmt="JPEG", orientation=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    picture = Image.new("RGB", size, (90, 120, 150))
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        picture.save(path, format=fmt, exif=exif)
    else:
        picture.save(path, format=fmt)


def build(root, files=SAMPLE):
    for name, size in files.items():
        image(root / IMAGES / name, size)
    return root


def run(root, output=OUTPUT):
    return agedb.export(root, IMAGES, output)


def load(root, leaf, output=OUTPUT):
    return json.loads((root / output / leaf).read_text(encoding="utf-8"))


def cli(root, output=OUTPUT, *, ack=True):
    args = ["--root", str(root), "--images-dir", IMAGES, "--output-dir", output]
    if ack:
        args.append("--local-only-ack")
    return args


# --- filename parsing ------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("0_PersonM_35_f.jpg", (0, "PersonM", 35, "f")),
        ("16487_Some_Long_Name_70_m.jpg", (16487, "Some_Long_Name", 70, "m")),
        ("12_Name_With_Digits_1990_20_m.jpg", (12, "Name_With_Digits_1990", 20, "m")),
        ("3_A_0_f.jpg", (3, "A", 0, "f")),
        ("4_Person'O-Test_120_m.jpg", (4, "Person'O-Test", 120, "m")),
        ("5_Personë Test_33_f.JPG", (5, "Personë Test", 33, "f")),
        ("6_名字_44_m.jpg", (6, "名字", 44, "m")),
    ],
)
def test_valid_official_names_parse_id_left_and_age_gender_right(name, expected):
    row = agedb.parse_filename(name)
    assert (row["image_id"], row["name"], row["age"], row["gender"]) == expected


def test_names_are_nfc_normalized_for_identity():
    decomposed = agedb.parse_filename("1_Persone\u0301_30_f.jpg")["name"]
    composed = agedb.parse_filename("2_Person\u00e9_30_f.jpg")["name"]
    assert decomposed == composed
    assert agedb.subject_id(decomposed) == agedb.subject_id(composed)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Thumbs.db", "SUFFIX_NOT_JPG"),
        ("0_Name_30_m.png", "SUFFIX_NOT_JPG"),
        ("0_Name_30_m.jpeg", "SUFFIX_NOT_JPG"),
        ("0_Name_30_m", "SUFFIX_NOT_JPG"),
        ("0_Name_30_m.jpg.txt", "SUFFIX_NOT_JPG"),
        (".jpg", "SUFFIX_NOT_JPG"),
        ("0_Name_30.jpg", "FILENAME_PATTERN_MISMATCH"),
        ("Name.jpg", "FILENAME_PATTERN_MISMATCH"),
        ("0-Name-30-m.jpg", "FILENAME_PATTERN_MISMATCH"),
        ("x_Name_30_m.jpg", "ID_INVALID"),
        ("-1_Name_30_m.jpg", "ID_INVALID"),
        ("01_Name_30_m.jpg", "ID_INVALID"),
        ("1234567890_Name_30_m.jpg", "ID_INVALID"),
        ("٣_Name_30_m.jpg", "ID_INVALID"),
        ("_Name_30_m.jpg", "ID_INVALID"),
        ("0__30_m.jpg", "NAME_INVALID"),
        ("0___30_m.jpg", "NAME_INVALID"),
        ("0__Name_30_m.jpg", "NAME_INVALID"),
        ("0_Name__30_m.jpg", "NAME_INVALID"),
        ("0_ Name_30_m.jpg", "NAME_INVALID"),
        ("0_Na\u200bme_30_m.jpg", "NAME_INVALID"),
        ("0_Na\x7fme_30_m.jpg", "NAME_INVALID"),
        ("0_" + "N" * 201 + "_30_m.jpg", "NAME_INVALID"),
        ("0_Name_thirty_m.jpg", "AGE_NOT_INTEGER"),
        ("0_Name_-5_m.jpg", "AGE_NOT_INTEGER"),
        ("0_Name_30.5_m.jpg", "AGE_NOT_INTEGER"),
        ("0_Name__m.jpg", "AGE_NOT_INTEGER"),
        ("0_Name_1000_m.jpg", "AGE_NOT_INTEGER"),
        ("0_Name_٣٠_m.jpg", "AGE_NOT_INTEGER"),
        ("0_Name_030_m.jpg", "AGE_LEADING_ZERO"),
        ("0_Name_00_m.jpg", "AGE_LEADING_ZERO"),
        ("0_Name_121_m.jpg", "AGE_OUT_OF_RANGE"),
        ("0_Name_999_m.jpg", "AGE_OUT_OF_RANGE"),
        ("0_Name_30_M.jpg", "GENDER_INVALID"),
        ("0_Name_30_F.jpg", "GENDER_INVALID"),
        ("0_Name_30_x.jpg", "GENDER_INVALID"),
        ("0_Name_30_.jpg", "GENDER_INVALID"),
        ("0_Name_30_male.jpg", "GENDER_INVALID"),
        ("0_Name_30_m .jpg", "GENDER_INVALID"),
        ("0_Name_30_mf.jpg", "GENDER_INVALID"),
        ("0_Name_\udcff_m.jpg", "FILENAME_NOT_UTF8"),
        ("dir/0_Name_30_m.jpg", "SUFFIX_NOT_JPG"),
        ("", "FILENAME_PATTERN_MISMATCH"),
    ],
)
def test_bad_names_raise_specific_reason(name, code):
    with pytest.raises(agedb.Error, match=f"^{code}$"):
        agedb.parse_filename(name)


@pytest.mark.parametrize(("letter", "label"), [("m", "male"), ("f", "female")])
def test_gender_letters_are_the_official_lowercase_pair(letter, label):
    assert agedb.parse_filename(f"0_Name_30_{letter}.jpg")["gender"] == letter
    assert agedb.GENDERS == {"m": "male", "f": "female"}
    assert agedb.GENDERS[letter] == label


@pytest.mark.parametrize("age", [0, 1, 19, 20, 70, 71, 101, 120])
def test_every_canonical_age_0_to_120_is_valid_not_only_20_70(age):
    assert agedb.parse_filename(f"0_Name_{age}_m.jpg")["age"] == age


# --- statistics ------------------------------------------------------------------


def row(name, age, side=200, gender="m"):
    return {"name": name, "age": age, "gender": gender, "short_side": side}


def test_age_boundaries_19_20_70_71():
    summary = agedb.summarize([row("A", 19), row("A", 20), row("A", 70), row("A", 71)])
    assert summary["images_age_20_70"] == 2
    assert summary["images_age_exact_70"] == 1
    assert summary["age_min"] == 19 and summary["age_max"] == 71
    assert summary["images_by_age_decade"] == {"10-19": 1, "20-29": 1, "70-79": 2}


@pytest.mark.parametrize(
    ("ages", "span_all", "span_inside"),
    [
        ([20, 49], 0, 0),
        ([20, 50], 1, 1),
        ([30], 0, 0),
        ([19, 49], 1, 0),
        ([45, 75], 1, 0),
        ([10, 20, 30, 40, 50], 1, 1),
        ([40, 41, 70], 1, 1),
    ],
)
def test_identity_span_threshold_is_inclusive_30(ages, span_all, span_inside):
    summary = agedb.summarize([row("Same_Person", a) for a in ages])
    assert summary["identities"] == 1
    assert summary["identities_span_ge_30"] == span_all
    assert summary["identities_span_ge_30_within_20_70"] == span_inside


def test_span_is_per_identity_never_pooled_across_people():
    summary = agedb.summarize([row("A", 20), row("B", 60), row("C_D", 25), row("C_D", 55)])
    assert summary["identities"] == 3
    assert summary["identities_span_ge_30"] == 1


def test_short_side_distribution_and_filters():
    sides = [26, 63, 64, 127, 128, 213, 255, 256, 511, 512, 1023, 1024, 2232]
    rows = [row(f"P{i}", 20 + i, side) for i, side in enumerate(sides)]
    rows.append(row("NoSize", 40, None))
    summary = agedb.summarize(rows)
    stats = summary["short_side_px"]
    assert stats["count"] == 13
    assert (stats["min"], stats["max"], stats["median"]) == (26, 2232, 255)
    assert stats["below_128"] == 4
    assert stats["quantiles"] == {"p5": 26, "p25": 127, "p50": 255, "p75": 512, "p95": 2232}
    assert stats["histogram"] == {
        "0-63": 2,
        "64-127": 2,
        "128-255": 3,
        "256-511": 2,
        "512-1023": 2,
        ">=1024": 2,
    }
    assert summary["images_without_size"] == 1
    assert summary["images"] == 14
    assert summary["filter_short_ge_128"]["images"] == 9
    # ages 20+i: sides >= 128 have ages 24..32, all inside 20-70
    assert summary["filter_short_ge_128_age_20_70"]["images"] == 9


def test_even_count_median_and_empty_distribution():
    assert (
        agedb.summarize([row("A", 30, 100), row("B", 30, 201)])["short_side_px"]["median"] == 150.5
    )
    empty = agedb.summarize([row("A", 30, None)])["short_side_px"]
    assert empty == {"count": 0, "min": None, "max": None, "median": None, "quantiles": None}


def test_filter_calibers_recount_span_after_filtering():
    rows = [row("A", 20, 500), row("A", 55, 100), row("A", 60, 300), row("B", 70, 128)]
    summary = agedb.summarize(rows)
    assert summary["identities_span_ge_30"] == 1
    assert summary["filter_short_ge_128"] == {
        "images": 3,
        "identities": 2,
        "identities_span_ge_30": 1,
        "images_age_exact_70": 1,
    }
    rows[2]["short_side"] = 127
    assert agedb.summarize(rows)["filter_short_ge_128_age_20_70"]["identities_span_ge_30"] == 0


def test_gender_and_case_only_name_counts():
    rows = [row("Anna", 30, gender="f"), row("anna", 40, gender="f"), row("Bob", 50)]
    summary = agedb.summarize(rows)
    assert summary["images_by_gender"] == {"female": 2, "male": 1}
    assert summary["identities"] == 3  # exact spelling, flagged for manual review
    assert summary["identities_differing_only_by_case"] == 2


# --- end-to-end export -----------------------------------------------------------


def test_export_counts_k5_and_aggregate_only_stats(tmp_path):
    build(tmp_path)
    stats = run(tmp_path)
    assert stats["status"] == "passed"
    assert {p.name for p in (tmp_path / OUTPUT).iterdir()} == LEAVES
    summary = stats["summary"]
    assert summary["images"] == 9 and summary["identities"] == 3
    assert summary["images_age_20_70"] == 7
    assert summary["images_age_exact_70"] == 1
    # Alpha 19..70 (51/50), TestSubject01 40..71 (31; 29 inside 20-70), Beta 30..60 (30/30)
    assert summary["identities_span_ge_30"] == 3
    assert summary["identities_span_ge_30_within_20_70"] == 2
    assert summary["short_side_px"]["min"] == 63
    assert summary["short_side_px"]["max"] == 1024
    assert summary["short_side_px"]["below_128"] == 3
    assert summary["filter_short_ge_128_age_20_70"] == {
        "images": 4,
        "identities": 3,
        "identities_span_ge_30": 1,
        "images_age_exact_70": 1,
    }
    assert stats["counts"]["k5_records"] == 9 and stats["counts"]["rejected"] == 0
    assert load(tmp_path, "stats.json")["summary"] == summary
    assert stats["python_runtime"] == sys.version.split()[0]
    assert stats["pillow_version"] == Image.__version__


def test_stats_json_contains_no_file_names_person_names_or_ids(tmp_path):
    files = {**SAMPLE, "9_Very_Unusual_Name_33_f.jpg": (40, 40)}
    build(tmp_path, files)
    (tmp_path / IMAGES / "notes_Secret_Name.txt").write_text("x")
    run(tmp_path)
    text = (tmp_path / OUTPUT / "stats.json").read_text(encoding="utf-8")
    for token in (
        "AlphaPerson",
        "Test_Subject",
        "BetaPerson",
        "Unusual",
        "Secret",
        "_f.jpg",
        "_m.jpg",
    ):
        assert token not in text
    assert "agedb:" not in text and "agedb-subject:" not in text
    assert load(tmp_path, "stats.json")["contains_file_names_or_person_names"] is False
    rejected = load(tmp_path, "rejected.json")
    assert rejected["local_only"] is True
    assert rejected["rejected"] == [
        {"path": IMAGES + "/notes_Secret_Name.txt", "reason": "SUFFIX_NOT_JPG"}
    ]


def test_k5_manifest_is_valid_and_loadable_by_dataset_manifest_cli(tmp_path):
    build(tmp_path)
    stats = run(tmp_path)
    body = (tmp_path / OUTPUT / "manifest.json").read_bytes()
    assert sha(body) == stats["k5_manifest_sha256"]
    manifest = metadata.validate_manifest(json.loads(body))
    records = manifest["records"]
    assert [r["sample_id"] for r in records] == [f"agedb:{i}" for i in range(9)]
    assert {r["use"] for r in records} == {"unassigned"}
    assert {r["kind"] for r in records} == {"original"}
    assert {r["age_source"] for r in records} == {"dataset_annotation"}
    assert all(r["age"]["kind"] == "exact" and r["parent_id"] is None for r in records)
    assert records[4]["age"]["value"] == 40
    subject01 = {r["subject_id"] for r in records[4:7]}
    assert len(subject01) == 1 and subject01 == {agedb.subject_id("Test_Subject_01")}
    assert len({r["subject_id"] for r in records}) == 3
    for record in records:
        raw = (tmp_path / record["file"]["path"]).read_bytes()
        assert record["file"]["bytes"] == len(raw) and record["file"]["sha256"] == sha(raw)
    audit = metadata.export_manifest(
        tmp_path, OUTPUT + "/manifest.json", sha(body), "output/research/k5-recheck"
    )
    assert audit["summary"]["records"] == 9
    assert audit["summary"]["local_subjects"] == 3
    assert audit["summary"]["formal_split_records"] == {"train": 0, "validation": 0, "test": 0}
    assert audit["split_assignment_performed"] is False
    scopes = {c["sample_id"]: c["age_scope"] for c in load(tmp_path, "audit.json")["record_checks"]}
    assert scopes["agedb:0"] == "outside" and scopes["agedb:5"] == "outside"
    assert scopes["agedb:1"] == "inside" and scopes["agedb:3"] == "inside"


def test_rejections_are_recorded_and_totals_reconcile(tmp_path):
    files = {
        **SAMPLE,
        "10_Gamma_30_M.jpg": (40, 40),
        "11_Gamma_030_f.jpg": (40, 40),
        "Gamma_30_f.jpg": (40, 40),
        "12_Gamma_200_f.jpg": (40, 40),
    }
    build(tmp_path, files)
    (tmp_path / IMAGES / "desktop.ini").write_text("x")
    stats = run(tmp_path)
    assert stats["status"] == "needs_review"
    assert stats["counts"]["rejected_by_reason"] == {
        "AGE_LEADING_ZERO": 1,
        "AGE_OUT_OF_RANGE": 1,
        "FILENAME_PATTERN_MISMATCH": 1,
        "GENDER_INVALID": 1,
        "SUFFIX_NOT_JPG": 1,
    }
    assert stats["counts"]["entries_scanned"] == 14
    assert stats["counts"]["k5_records"] + stats["counts"]["rejected"] == 14
    paths = [r["path"] for r in load(tmp_path, "rejected.json")["rejected"]]
    assert IMAGES + "/10_Gamma_30_M.jpg" in paths and IMAGES + "/desktop.ini" in paths
    assert stats["summary"]["images"] == 9


def test_duplicate_image_id_rejects_every_copy(tmp_path):
    files = {**SAMPLE, "8_OtherPerson_44_f.jpg": (40, 40)}
    build(tmp_path, files)
    stats = run(tmp_path)
    rejected = load(tmp_path, "rejected.json")["rejected"]
    assert [r["reason"] for r in rejected] == ["DUPLICATE_IMAGE_ID"] * 2
    assert stats["counts"]["k5_records"] == 8
    assert "agedb:8" not in {r["sample_id"] for r in load(tmp_path, "manifest.json")["records"]}


@pytest.mark.parametrize("fmt", ["PNG", "GIF", "BMP", "WEBP"])
def test_non_jpeg_content_is_k5_failed_and_excluded_from_size_stats(tmp_path, fmt):
    build(tmp_path)
    image(tmp_path / IMAGES / "7_BetaPerson_30_m.jpg", (63, 63), fmt=fmt)
    stats = run(tmp_path)
    assert stats["status"] == "needs_review"
    assert stats["counts"]["image_failures_by_code"] == {"IMAGE_UNREADABLE": 1}
    assert stats["summary"]["images"] == 9  # filename-based age counts keep it
    assert stats["summary"]["images_without_size"] == 1
    assert stats["summary"]["short_side_px"]["min"] == 64
    record = load(tmp_path, "manifest.json")["records"][7]
    assert record["processing"] == {"status": "failed", "reason": "agedb_header:IMAGE_UNREADABLE"}


def test_truncated_and_empty_jpeg_are_failed_not_crashing(tmp_path):
    build(tmp_path)
    (tmp_path / IMAGES / "0_AlphaPerson_19_f.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / IMAGES / "1_AlphaPerson_20_f.jpg").write_bytes(b"")
    stats = run(tmp_path)
    assert stats["counts"]["image_failures_by_code"] == {"IMAGE_UNREADABLE": 1}
    assert stats["counts"]["rejected_by_reason"] == {"FILE_EMPTY": 1}
    assert stats["counts"]["k5_records"] == 8


def test_oversized_file_is_rejected_without_pin(tmp_path, monkeypatch):
    build(tmp_path)
    monkeypatch.setattr(agedb, "MAX_IMAGE_BYTES", 700)
    big = tmp_path / IMAGES / "5_Test_Subject_01_71_m.jpg"
    assert big.stat().st_size > 700
    stats = run(tmp_path)
    assert "IMAGE_TOO_LARGE" in stats["counts"]["rejected_by_reason"]


def test_decompression_bomb_header_is_failed(tmp_path, monkeypatch):
    build(tmp_path)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10_000)
    stats = run(tmp_path)
    failures = stats["counts"]["image_failures_by_code"]
    assert failures == {"IMAGE_UNREADABLE": 7}  # all but 64x90 and 63x63 exceed 10,000 px


def test_exif_orientation_is_counted_and_does_not_change_short_side(tmp_path):
    build(tmp_path)
    image(tmp_path / IMAGES / "2_AlphaPerson_49_f.jpg", (127, 400), orientation=6)
    stats = run(tmp_path)
    assert stats["counts"]["exif_orientation_not_identity"] == 1
    assert stats["status"] == "passed"
    assert stats["summary"]["short_side_px"]["below_128"] == 3


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_links_are_rejected_and_never_followed(tmp_path):
    build(tmp_path)
    outside = tmp_path / "elsewhere/20_Linked_40_m.jpg"
    image(outside)
    (tmp_path / IMAGES / "20_Linked_40_m.jpg").symlink_to(outside)
    (tmp_path / IMAGES / "linkdir").symlink_to(outside.parent, target_is_directory=True)
    stats = run(tmp_path)
    assert stats["counts"]["rejected_by_reason"] == {"LINK_OR_REPARSE_PATH": 2}
    assert stats["summary"]["images"] == 9


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_linked_images_dir_is_rejected_whole(tmp_path):
    real = tmp_path / "real"
    for name in SAMPLE:
        image(real / name)
    (tmp_path / "data/datasets").mkdir(parents=True)
    (tmp_path / IMAGES).symlink_to(real, target_is_directory=True)
    with pytest.raises(agedb.Error, match="LINK_OR_REPARSE_PATH"):
        run(tmp_path)
    assert not (tmp_path / "output").exists()


def test_nested_folders_are_scanned_and_too_deep_is_recorded(tmp_path):
    build(tmp_path)
    image(tmp_path / IMAGES / "AgeDB/30_Nested_40_m.jpg")
    image(tmp_path / IMAGES / "a/b/c/31_Deepest_allowed_40_m.jpg")
    image(tmp_path / IMAGES / "a/b/c/d/32_Too_Deep_40_m.jpg")
    stats = run(tmp_path)
    assert stats["summary"]["images"] == 11
    rejected = load(tmp_path, "rejected.json")["rejected"]
    assert rejected == [{"path": IMAGES + "/a/b/c/d", "reason": "PATH_TOO_DEEP"}]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux allows non-UTF-8 byte names")
def test_non_utf8_file_name_is_recorded_not_crashing(tmp_path):
    build(tmp_path)
    folder = os.fsencode(tmp_path / IMAGES)
    with open(os.path.join(folder, b"40_Bad\xff_30_m.jpg"), "wb") as stream:
        stream.write(b"x")
    stats = run(tmp_path)
    assert stats["counts"]["rejected_by_reason"] == {"FILENAME_NOT_UTF8": 1}
    rejected = load(tmp_path, "rejected.json")["rejected"]
    assert rejected[0]["path"].endswith("40_Bad\\udcff_30_m.jpg")


def test_windows_reserved_or_invalid_path_parts_are_rejected(tmp_path):
    build(tmp_path)
    image(tmp_path / IMAGES / "41_Trailing._30_m.jpg")  # ok name, ok path
    image(tmp_path / IMAGES / "42_Que?stion_30_m.jpg")
    stats = run(tmp_path)
    assert stats["counts"]["rejected_by_reason"] == {"PATH_INVALID": 1}
    assert stats["summary"]["images"] == 10


def test_inputs_changed_during_run_marks_unstable(tmp_path, monkeypatch):
    build(tmp_path)
    original = agedb._stable

    def tamper(root, rows):
        (tmp_path / IMAGES / "0_AlphaPerson_19_f.jpg").write_bytes(b"changed")
        return original(root, rows)

    monkeypatch.setattr(agedb, "_stable", tamper)
    stats = run(tmp_path)
    assert stats["inputs_stable"] is False and stats["status"] == "needs_review"


def test_inventory_hash_tracks_content_and_rejections(tmp_path):
    build(tmp_path)
    first = run(tmp_path)["inventory_sha256"]
    assert run(tmp_path, OUTPUT + "-same")["inventory_sha256"] == first
    image(tmp_path / IMAGES / "8_BetaPerson_60_m.jpg", (257, 300))
    second = run(tmp_path, OUTPUT + "-changed")["inventory_sha256"]
    (tmp_path / IMAGES / "readme.txt").write_text("x")
    third = run(tmp_path, OUTPUT + "-rejected")["inventory_sha256"]
    assert len({first, second, third}) == 3


# --- rejection leaves no output --------------------------------------------------


@pytest.mark.parametrize("research_exists", [False, True])
def test_no_valid_images_rejects_without_output(tmp_path, research_exists):
    (tmp_path / IMAGES).mkdir(parents=True)
    (tmp_path / IMAGES / "bad.jpg").write_bytes(b"x")
    keep = tmp_path / "output/research/other/keep.txt"
    if research_exists:
        keep.parent.mkdir(parents=True)
        keep.write_text("not ours")
    with pytest.raises(agedb.Error, match="NO_AGEDB_IMAGES"):
        run(tmp_path)
    assert not (tmp_path / OUTPUT).exists()
    assert keep.exists() if research_exists else not (tmp_path / "output").exists()


def _reject_manifest_size(monkeypatch):
    monkeypatch.setattr(metadata, "MAX_JSON_BYTES", 100)
    return "K5_MANIFEST_TOO_LARGE"


def _reject_report_size(monkeypatch):
    monkeypatch.setattr(agedb, "MAX_OUTPUT_BYTES", 100)
    return "REPORT_TOO_LARGE"


def _reject_many_files(monkeypatch):
    monkeypatch.setattr(agedb, "MAX_FILES", 3)
    return "TOO_MANY_FILES"


@pytest.mark.parametrize(
    "arrange", [_reject_manifest_size, _reject_report_size, _reject_many_files]
)
@pytest.mark.parametrize("research_exists", [False, True])
def test_budget_rejection_leaves_no_output(tmp_path, monkeypatch, arrange, research_exists):
    build(tmp_path)
    keep = tmp_path / "output/research/other/keep.txt"
    if research_exists:
        keep.parent.mkdir(parents=True)
        keep.write_text("not ours")
    code = arrange(monkeypatch)
    with pytest.raises(agedb.Error, match=code):
        run(tmp_path)
    assert not (tmp_path / OUTPUT).exists()
    assert keep.read_text() == "not ours" if research_exists else not (tmp_path / "output").exists()


@pytest.mark.parametrize("fail_at", [1, 2, 4])
def test_write_failure_midway_removes_created_directories(tmp_path, monkeypatch, fail_at):
    build(tmp_path)
    real_open, calls = Path.open, []

    def flaky(self, mode="r", *args, **kwargs):
        if mode == "xb":
            calls.append(self.name)
            if len(calls) == fail_at:
                raise OSError("disk full")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky)
    with pytest.raises(OSError, match="disk full"):
        run(tmp_path, "output/research/deep/nested/agedb")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    ("output", "code"),
    [
        ("output/other/agedb", "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY"),
        ("data/datasets/agedb/out", "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY"),
        ("../escape", "INVALID_PATH"),
        ("/abs/path", "INVALID_PATH"),
    ],
)
def test_output_location_is_validated_before_any_read(tmp_path, output, code):
    build(tmp_path)
    with pytest.raises(agedb.Error, match=code):
        run(tmp_path, output)


def test_existing_output_and_overlap_are_rejected(tmp_path, monkeypatch):
    build(tmp_path)
    run(tmp_path)
    before = {p.name: p.read_bytes() for p in (tmp_path / OUTPUT).iterdir()}
    with pytest.raises(agedb.Error, match="OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY"):
        run(tmp_path)
    assert {p.name: p.read_bytes() for p in (tmp_path / OUTPUT).iterdir()} == before
    image(tmp_path / "output/research/imgs/0_Name_30_m.jpg")
    with pytest.raises(agedb.Error, match="OUTPUT_OVERLAPS_INPUT"):
        agedb.export(tmp_path, "output/research/imgs", "output/research/imgs/out")
    with pytest.raises(agedb.Error, match="IMAGES_DIR_MISSING"):
        agedb.export(tmp_path, "data/missing", OUTPUT + "-2")


# --- CLI -------------------------------------------------------------------------


def test_cli_exit_codes_0_1_2(tmp_path, capsys):
    build(tmp_path)
    assert agedb.main(cli(tmp_path)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "passed" and printed["summary"]["images_age_exact_70"] == 1
    assert agedb.main(cli(tmp_path)) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert rejected == {
        "status": "rejected",
        "error_code": "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY",
        **agedb.FLAGS,
    }
    (tmp_path / IMAGES / "bad_name.jpg").write_bytes(b"x")
    assert agedb.main(cli(tmp_path, OUTPUT + "-2")) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "needs_review"
    assert printed["counts"]["rejected_by_reason"] == {"FILENAME_PATTERN_MISMATCH": 1}
    assert "bad_name" not in json.dumps(printed)
    assert agedb.main(["--root", str(tmp_path / "nope"), *cli(tmp_path)[2:]]) == 2


def test_cli_runs_as_module(tmp_path):
    build(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "preprocessing.agedb_filenames", *cli(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert agedb.LOCAL_ONLY_WARNING in completed.stderr
    assert json.loads(completed.stdout)["summary"]["identities"] == 3


def test_cli_refuses_without_local_only_ack_and_writes_nothing(tmp_path, capsys):
    build(tmp_path)
    assert agedb.main(cli(tmp_path, ack=False)) == 2
    captured = capsys.readouterr()
    assert "--local-only-ack" in captured.err
    assert "拒绝执行" in captured.err
    printed = json.loads(captured.out)
    assert printed == {
        "status": "rejected",
        "error_code": agedb.LOCAL_ONLY_ACK_REQUIRED,
        **agedb.FLAGS,
    }
    assert not (tmp_path / "output").exists()


def test_cli_prints_local_only_warning_when_ack_given(tmp_path, capsys):
    build(tmp_path)
    assert agedb.main(cli(tmp_path)) == 0
    captured = capsys.readouterr()
    assert agedb.LOCAL_ONLY_WARNING in captured.err
    assert json.loads(captured.out)["status"] == "passed"


def test_cli_help_lists_required_ack_and_does_not_run(capsys):
    with pytest.raises(SystemExit) as exc:
        agedb.main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--local-only-ack" in help_text
    assert "未传入" in help_text
    assert "不写任何文件" in help_text


def test_outer_reports_mark_local_only_k5_manifest_unchanged(tmp_path):
    build(tmp_path)
    run(tmp_path)
    rejected = load(tmp_path, "rejected.json")
    audit = load(tmp_path, "audit.json")
    manifest = load(tmp_path, "manifest.json")
    assert rejected["local_only"] is True
    assert audit["local_only"] is True
    assert "local_only" not in manifest
    validated = metadata.validate_manifest(manifest)
    assert "local_only" not in validated
    assert validated["schema_id"] == metadata.SCHEMA
    assert validated["manifest_id"] == "agedb-official-filenames-v1"
    # stats.json is aggregate-only (no filenames); it is not a filename-bearing outer report
    assert "local_only" not in load(tmp_path, "stats.json")


def test_source_has_no_network_pickle_eval_or_split_assignment():
    source = (ROOT / "preprocessing/agedb_filenames.py").read_text(encoding="utf-8")
    for banned in ("urllib", "socket", "http", "requests", "pickle", "eval(", "exec(", "torch"):
        assert banned not in source
    assert "split_freeze" not in source
    assert agedb.FLAGS["split_assignment_performed"] is False
