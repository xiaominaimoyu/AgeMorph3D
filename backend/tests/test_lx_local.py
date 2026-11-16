"""LX-1..LX-3 local pack: whitelist summary, resume, and no filename/name leakage.

All inputs are synthetic files with fictional names in temporary folders. No AgeDB
archive, mirror, dump or /workspace/hf path is read or downloaded.
"""

import hashlib
import importlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
lx = importlib.import_module("preprocessing.lx_local")
agedb = importlib.import_module("preprocessing.agedb_filenames")
metadata = importlib.import_module("preprocessing.dataset_manifest")
screening = importlib.import_module("preprocessing.duplicate_screening")
preparation = importlib.import_module("preprocessing.archive_preparation")

ARCHIVE = "data/datasets/AgeDB.zip"
IMAGES = "data/datasets/agedb"
TERMS = "output/research/input/terms-snapshot.html"
OUTPUT = "output/research/lx-fixture"
# Distinctive fictional tokens that must never appear in summary.json bytes.
LEAK_NAME = "SECRET_NAME_TOKEN_XYZ"
LEAK_PERSON = "Test_Subject_01"
FILES = {
    "0_PersonA_19_f.jpg": (300, 200),
    "1_PersonA_20_f.jpg": (200, 300),
    "2_PersonA_70_f.jpg": (128, 128),
    f"3_{LEAK_PERSON}_40_m.jpg": (256, 256),
    f"4_{LEAK_PERSON}_71_m.jpg": (64, 90),
    f"5_{LEAK_PERSON}_69_m.jpg": (512, 512),
    "6_PersonB_30_m.jpg": (200, 200),
    "7_PersonB_60_m.jpg": (256, 300),
    "8_AlphaPerson_35_f.jpg": (400, 400),
    "9_AlphaPerson_65_f.jpg": (180, 220),
    f"10_{LEAK_NAME}_40_m.jpg": (140, 140),
    "11_BetaPerson_25_m.jpg": (160, 160),
    "12_BetaPerson_55_m.jpg": (192, 192),
}


def sha(body):
    return hashlib.sha256(body).hexdigest()


def jpeg(path, size=(32, 32)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (90, 120, 150)).save(path, format="JPEG")


def write_images(root, files=FILES):
    folder = root / IMAGES
    for name, size in files.items():
        jpeg(folder / name, size)
    return folder


def _mark_zip_encrypted(path):
    """Set the encrypt flag in local and central headers without storing a password."""
    with zipfile.ZipFile(path) as container:
        local_offsets = [info.header_offset for info in container.infolist()]
        start_dir = container.start_dir
    data = bytearray(path.read_bytes())
    for offset in local_offsets:
        flags = int.from_bytes(data[offset + 6 : offset + 8], "little") | 1
        data[offset + 6 : offset + 8] = flags.to_bytes(2, "little")
    cursor = start_dir
    for _ in local_offsets:
        assert data[cursor : cursor + 4] == b"PK\x01\x02"
        flags = int.from_bytes(data[cursor + 8 : cursor + 10], "little") | 1
        data[cursor + 8 : cursor + 10] = flags.to_bytes(2, "little")
        name_len = int.from_bytes(data[cursor + 28 : cursor + 30], "little")
        extra_len = int.from_bytes(data[cursor + 30 : cursor + 32], "little")
        comment_len = int.from_bytes(data[cursor + 32 : cursor + 34], "little")
        cursor += 46 + name_len + extra_len + comment_len
    path.write_bytes(data)


def make_zip(root, files=FILES, name=ARCHIVE, *, encrypted=False, slip=None):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as container:
        if slip is not None:
            info = zipfile.ZipInfo(slip)
            container.writestr(info, b"escaped")
        for filename, size in files.items():
            stream = Path(root / "._imgcache")
            jpeg(stream, size)
            body = stream.read_bytes()
            container.writestr(filename, body)
        if stream.exists():
            stream.unlink()
    if encrypted:
        _mark_zip_encrypted(path)
    return path


def terms(root):
    path = root / TERMS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<html>synthetic terms snapshot; fictional only</html>\n", encoding="utf-8")
    return path


def cli(root, output=OUTPUT, extra=None):
    args = [
        "--root",
        str(root),
        "--archive",
        ARCHIVE,
        "--images-dir",
        IMAGES,
        "--terms-snapshot",
        TERMS,
        "--output-dir",
        output,
        "--local-only-ack",
    ]
    if extra:
        args.extend(extra)
    return args


@pytest.fixture(autouse=True)
def clean_readonly(tmp_path):
    yield
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                path.chmod(stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                pass
        elif path.is_dir():
            try:
                path.chmod(stat.S_IRWXU)
            except OSError:
                pass


def test_cli_refuses_without_local_only_ack_and_writes_nothing(tmp_path, capsys):
    assert lx.main(["--root", str(tmp_path), "--output-dir", OUTPUT, "--images-dir", IMAGES]) == 2
    captured = capsys.readouterr()
    assert "--local-only-ack" in captured.err and "拒绝执行" in captured.err
    printed = json.loads(captured.out)
    assert printed["status"] == "rejected"
    assert printed["error_code"] == lx.LOCAL_ONLY_ACK_REQUIRED
    assert not (tmp_path / OUTPUT).exists()
    assert not (tmp_path / "output").exists()


def test_cli_help_lists_ack_and_does_not_mention_a_password(capsys):
    with pytest.raises(SystemExit) as exc:
        lx.main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--local-only-ack" in help_text
    assert "不接收" in help_text and "密码" in help_text
    assert "--password" not in help_text
    assert "--passwd" not in help_text


def test_source_has_no_password_network_or_trust_remote_code():
    source = (ROOT / "preprocessing/lx_local.py").read_text(encoding="utf-8")
    for banned in (
        "urllib",
        "requests",
        "socket",
        "pickle",
        "eval(",
        "exec(",
        "torch",
        "--password",
        "getpass",
    ):
        assert banned not in source
    assert source.count("pwd=") == 1 and "pwd=None" in source
    assert source.count("trust_remote_code") == 1
    assert "no ``trust_remote_code``" in source or "never enable" in source


def test_whitelist_rejects_extra_fields():
    with pytest.raises(lx.Error, match="SUMMARY_EXTRA_FIELDS"):
        lx.project_summary({"schema_id": lx.SCHEMA, "filename": "0_PersonA_20_f.jpg"})
    body = lx.encode_summary({"schema_id": lx.SCHEMA, "images": 3, "status": "passed"})
    text = body.decode("utf-8")
    assert "PersonA" not in text and "filename" not in text
    assert json.loads(body)["images"] == 3


def test_lx1_safe_extracts_unencrypted_zip_and_sets_readonly(tmp_path):
    terms(tmp_path)
    archive = make_zip(tmp_path)
    summary = lx.run_pack(
        tmp_path,
        OUTPUT,
        archive=ARCHIVE,
        images_dir=IMAGES,
        terms_snapshot=TERMS,
        stages=("lx1",),
    )
    assert summary["extraction_method"] == "safe_unencrypted_zip"
    assert summary["archive_bytes"] == archive.stat().st_size
    assert summary["archive_sha256"] == sha(archive.read_bytes())
    assert summary["extracted_file_count"] == len(FILES)
    assert summary["extracted_readonly"] is True
    assert summary["terms_snapshot_sha256"] == sha((tmp_path / TERMS).read_bytes())
    sample = tmp_path / IMAGES / "0_PersonA_19_f.jpg"
    assert sample.is_file() and not (sample.stat().st_mode & 0o222)


def test_lx1_rejects_zip_slip_and_writes_nothing_outside(tmp_path):
    terms(tmp_path)
    make_zip(tmp_path, slip="../escape.jpg")
    with pytest.raises(lx.Error, match="INVALID_PATH"):
        lx.run_pack(
            tmp_path,
            OUTPUT,
            archive=ARCHIVE,
            images_dir=IMAGES,
            terms_snapshot=TERMS,
            stages=("lx1",),
        )
    assert not (tmp_path / "escape.jpg").exists()
    assert not (tmp_path / IMAGES).exists()


def test_lx1_encrypted_zip_without_folder_asks_for_system_extractor(tmp_path):
    terms(tmp_path)
    make_zip(tmp_path, encrypted=True)
    with pytest.raises(lx.Error, match="SYSTEM_EXTRACTOR_REQUIRED"):
        lx.run_pack(
            tmp_path,
            OUTPUT,
            archive=ARCHIVE,
            images_dir=IMAGES,
            terms_snapshot=TERMS,
            stages=("lx1",),
        )
    assert not (tmp_path / IMAGES).exists()


def test_lx1_encrypted_zip_reuses_already_extracted_folder(tmp_path):
    terms(tmp_path)
    make_zip(tmp_path, encrypted=True)
    write_images(tmp_path)
    summary = lx.run_pack(
        tmp_path,
        OUTPUT,
        archive=ARCHIVE,
        images_dir=IMAGES,
        terms_snapshot=TERMS,
        stages=("lx1",),
    )
    assert summary["extraction_method"] == "already_extracted"
    assert summary["extracted_file_count"] == len(FILES)
    assert summary["extracted_readonly"] is True


def test_cli_rejects_unknown_password_flag(tmp_path):
    with pytest.raises(SystemExit) as exc:
        lx.main(cli(tmp_path) + ["--password", "should-not-be-accepted"])
    assert exc.value.code == 2


def _assert_clean(body, extra=()):
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    for token in (
        LEAK_NAME,
        LEAK_PERSON,
        "PersonA",
        "PersonB",
        "AlphaPerson",
        "BetaPerson",
        *extra,
    ):
        assert token not in text
    assert "_f.jpg" not in text and "_m.jpg" not in text
    assert "agedb-subject:" not in text and "agedb:" not in text
    data = json.loads(body)
    assert set(data) <= set(lx.SUMMARY_WHITELIST)
    assert data["contains_file_names_or_person_names"] is False
    assert data["password_accepted_or_stored"] is False
    return data


def test_full_pack_summary_has_no_names_and_covers_lx2_lx3(tmp_path):
    terms(tmp_path)
    make_zip(tmp_path)
    summary = lx.run_pack(
        tmp_path, OUTPUT, archive=ARCHIVE, images_dir=IMAGES, terms_snapshot=TERMS
    )
    body = (tmp_path / OUTPUT / "summary.json").read_bytes()
    data = _assert_clean(body)
    assert data == summary
    assert data["status"] == "passed"
    assert data["stages_completed"] == ["lx1", "lx2", "lx3"]
    assert data["images"] == len(FILES)
    assert data["identities"] == 6
    assert data["images_age_20_70"] == 11  # 19 and 71 are outside
    assert data["images_age_exact_70"] == 1
    assert data["k5_records"] == len(FILES)
    assert data["split_unassigned_images"] == 2
    assert data["exclusions_by_reason"] == {"age_outside_20_70": 2}
    formal = (
        data["split_train_images"] + data["split_validation_images"] + data["split_test_images"]
    )
    assert formal + data["split_unassigned_images"] == data["k5_records"]
    assert data["cross_split_exact_duplicate_groups"] == 0
    assert data["p03_p04_invoked"] is False
    assert data["p03_p04_block_reason"] == "PREPARATION_REPORT_REQUIRED"
    assert data["k5_manifest_sha256"] == sha(
        (tmp_path / OUTPUT / "local/agedb-stats/manifest.json").read_bytes()
    )
    local_state = json.loads((tmp_path / OUTPUT / "local/state.json").read_text())
    assert local_state["local_only"] is True
    # Local reports may contain names; they must not be the shareable file.
    rejected = (tmp_path / OUTPUT / "local/agedb-stats/rejected.json").read_text(encoding="utf-8")
    assert "local_only" in rejected


def test_identity_split_keeps_each_subject_in_one_formal_use(tmp_path):
    terms(tmp_path)
    write_images(tmp_path)
    lx.run_pack(
        tmp_path,
        OUTPUT,
        images_dir=IMAGES,
        terms_snapshot=TERMS,
        stages=("lx1", "lx2", "lx3"),
    )
    ledger = json.loads((tmp_path / OUTPUT / "local/assignment-ledger.json").read_text())
    manifest = json.loads((tmp_path / OUTPUT / "local/agedb-stats/manifest.json").read_text())
    by_id = {r["sample_id"]: r for r in manifest["records"]}
    uses = {}
    for item in ledger["assignments"]:
        if item["use"] == "unassigned":
            continue
        subject = by_id[item["sample_id"]]["subject_id"]
        uses.setdefault(subject, set()).add(item["use"])
    assert uses and all(len(value) == 1 for value in uses.values())
    assert ledger["local_only"] is True


def test_cross_split_exact_duplicates_are_counted(tmp_path):
    records = [
        {
            "sample_id": "agedb:1",
            "subject_id": "agedb-subject:aaaa",
            "age": {"kind": "exact", "value": 30},
            "processing": {"status": "not_checked", "reason": None},
            "file": {"path": "x", "bytes": 4, "sha256": "ab" * 32},
        },
        {
            "sample_id": "agedb:2",
            "subject_id": "agedb-subject:bbbb",
            "age": {"kind": "exact", "value": 40},
            "processing": {"status": "not_checked", "reason": None},
            "file": {"path": "y", "bytes": 4, "sha256": "ab" * 32},
        },
    ]
    assignments, _, _, _ = lx.assign_identities(records)
    groups, extra, cross, _ = lx._exact_duplicates(records, assignments)
    assert groups == 1 and extra == 1
    # Two subjects, same bytes; if they landed in different formal uses, count it.
    uses = {item["use"] for item in assignments}
    if len(uses) > 1:
        assert cross == 1
    else:
        assert cross == 0


def test_resume_reuses_lx2_outputs_and_keeps_hashes(tmp_path):
    terms(tmp_path)
    make_zip(tmp_path)
    first = lx.run_pack(
        tmp_path,
        OUTPUT,
        archive=ARCHIVE,
        images_dir=IMAGES,
        terms_snapshot=TERMS,
        stages=("lx1",),
    )
    assert first["stages_completed"] == ["lx1"]
    second = lx.run_pack(tmp_path, OUTPUT, archive=ARCHIVE, images_dir=IMAGES, terms_snapshot=TERMS)
    third = lx.run_pack(tmp_path, OUTPUT, archive=ARCHIVE, images_dir=IMAGES, terms_snapshot=TERMS)
    assert second["k5_manifest_sha256"] == third["k5_manifest_sha256"]
    assert second["inventory_sha256"] == third["inventory_sha256"]
    assert second["assignment_ledger_sha256"] == third["assignment_ledger_sha256"]
    assert second["archive_sha256"] == first["archive_sha256"]
    _assert_clean((tmp_path / OUTPUT / "summary.json").read_bytes())


def test_p03_p04_block_reason_when_over_image_limit(tmp_path, monkeypatch):
    terms(tmp_path)
    make_zip(tmp_path)
    monkeypatch.setattr(preparation, "MAX_IMAGES", 2)
    dummy = {
        "path": "output/research/input/prep.json",
        "bytes": 2,
        "sha256": "ab" * 32,
    }
    # Still no real P01 report on disk; the count limit is checked first when pins exist.
    (tmp_path / "output/research/input").mkdir(parents=True, exist_ok=True)
    summary = lx.run_pack(
        tmp_path,
        OUTPUT,
        archive=ARCHIVE,
        images_dir=IMAGES,
        terms_snapshot=TERMS,
        prep_report=dummy,
        prepared_manifest=dummy,
    )
    assert summary["p03_p04_invoked"] is False
    assert summary["p03_p04_block_reason"] == "P01_P04_RECORD_COUNT_LIMIT"
    _assert_clean((tmp_path / OUTPUT / "summary.json").read_bytes())


def test_run_p03_p04_calls_real_screening_and_precheck(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "_lx_split_fixtures", Path(__file__).with_name("test_split_freeze.py")
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    case = fixtures.make_case(tmp_path)
    prep = case["plan"]["prepared_manifest"]
    # The screening plan on the fixture already has a preparation report pin.
    prep_report = case["screen_plan"]["preparation_report"]
    assignments = case["plan"]["assignments"]
    basis = case["basis"]
    # run_p03_p04 writes into output/research/<output>/local/...; use a fresh leaf
    # and pins that already live under tmp_path.
    output = "output/research/lx-tools"
    (tmp_path / output / "local").mkdir(parents=True, exist_ok=True)
    screen_report, freeze_report = lx.run_p03_p04(
        tmp_path, output, prep_report, prep, assignments, basis
    )
    assert screen_report["status"] in {"passed", "failed"}
    assert "summary" in screen_report
    assert freeze_report["status"] in {"consistent", "blocked"}
    assert freeze_report["freeze_authorized"] is False
    assert freeze_report["split_assignment_performed"] is False


def test_cli_as_module_prints_warning_and_writes_summary(tmp_path):
    terms(tmp_path)
    make_zip(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "preprocessing.lx_local", *cli(tmp_path, OUTPUT + "-mod")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert lx.LOCAL_ONLY_WARNING in completed.stderr
    assert json.loads(completed.stdout)["status"] == "passed"
    _assert_clean((tmp_path / (OUTPUT + "-mod") / "summary.json").read_bytes())


def test_cli_warning_printed_when_ack_given(tmp_path, capsys):
    terms(tmp_path)
    make_zip(tmp_path)
    assert lx.main(cli(tmp_path)) == 0
    captured = capsys.readouterr()
    assert lx.LOCAL_ONLY_WARNING in captured.err
    printed = json.loads(captured.out)
    assert printed["status"] == "passed"
    _assert_clean((tmp_path / OUTPUT / "summary.json").read_bytes())


def test_committed_sample_summary_is_clean_and_whitelisted():
    path = ROOT / "docs/lx-summary-sample.json"
    assert path.is_file()
    body = path.read_bytes()
    data = _assert_clean(body)
    assert data["schema_id"] == lx.SCHEMA
    assert "lx1" in data["stages_completed"]
