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


def run_module(args):
    """Run the CLI as ``python -B -m`` from this worktree; never writes bytecode."""
    return subprocess.run(
        [sys.executable, "-B", "-m", "preprocessing.lx_local", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
    )


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
    completed = run_module(cli(tmp_path, OUTPUT + "-mod"))
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
    assert lx.project_summary(data) == data
    assert data["pending_user_decisions"] == list(lx.PENDING_USER_DECISIONS)
    assert data["near_duplicate_checked_at_full_scale"] is False


# ---- Sentinel FG-8 rework (MAJOR-1..3, MINOR-1..9, FG-4 partial equivalence) ----

NO_ARCHIVE_STAGES = ("lx1", "lx2", "lx3")


def _unlock(path):
    for item in [path, *path.rglob("*")]:
        item.chmod(stat.S_IRWXU if item.is_dir() else stat.S_IREAD | stat.S_IWRITE)


def _no_archive_run(root, **kwargs):
    return lx.run_pack(root, OUTPUT, images_dir=IMAGES, terms_snapshot=TERMS, **kwargs)


def test_summary_value_whitelist_rejects_name_like_values():
    base = {"schema_id": lx.SCHEMA, "status": "passed"}
    bad = [
        ({"k5_audit_status": "PersonA"}, "SUMMARY_FIELD_VALUE"),
        ({"lx2_status": "PersonA"}, "SUMMARY_FIELD_VALUE"),
        ({"error_code": "0_PersonA_20_f.jpg"}, "SUMMARY_FIELD_VALUE"),
        ({"rejected_by_reason": {"PersonA 20": 1}}, "SUMMARY_FIELD_VALUE"),
        ({"images_by_gender": {"PersonA": 1}}, "SUMMARY_FIELD_VALUE"),
        ({"images": -1}, "SUMMARY_FIELD_VALUE"),
        ({"images": True}, "SUMMARY_FIELD_TYPE"),
        ({"screening_status": "PersonA"}, "SUMMARY_FIELD_VALUE"),
        ({"split_freeze_status": "frozen"}, "SUMMARY_FIELD_VALUE"),
        ({"k5_audit_finding_codes": ["agedb:1"]}, "SUMMARY_FIELD_VALUE"),
        ({"near_duplicate_checked_at_full_scale": True}, "SUMMARY_DISCLOSURE_ALTERED"),
        ({"split_age_stratified": 0}, "SUMMARY_DISCLOSURE_ALTERED"),
        ({"pending_user_decisions": ["SPLIT_RULE"]}, "SUMMARY_DISCLOSURE_ALTERED"),
        ({"near_duplicate_method_status": "done"}, "SUMMARY_DISCLOSURE_ALTERED"),
    ]
    for extra, code in bad:
        with pytest.raises(lx.Error, match=code):
            lx.project_summary({**base, **extra})


def test_summary_discloses_pending_user_decisions_and_unchecked_near_duplicates(tmp_path):
    terms(tmp_path)
    make_zip(tmp_path)
    data = lx.run_pack(tmp_path, OUTPUT, archive=ARCHIVE, images_dir=IMAGES, terms_snapshot=TERMS)
    assert data["cross_split_exact_duplicate_groups"] == 0
    assert data["exact_duplicate_zero_does_not_prove_no_leakage"] is True
    assert data["near_duplicate_screening_performed"] is False
    assert data["near_duplicate_checked_at_full_scale"] is False
    assert data["near_duplicate_method_status"] == "pending_user_decision"
    assert data["p01_quality_checks_performed"] is False
    assert data["split_rule_status"] == "provisional_pending_user_decision"
    assert data["split_ratio_has_source"] is False
    assert data["split_age_stratified"] is False
    assert data["small_cell_suppression_applied"] is False
    assert data["small_cell_suppression_status"] == "pending_user_decision"
    assert data["pending_user_decisions"] == [
        "NEAR_DUPLICATE_METHOD",
        "SPLIT_RULE",
        "SMALL_CELL_SUPPRESSION",
    ]
    assert data["freeze_authorized"] is False
    assert "NEAR_DUPLICATE_REVIEW_PENDING" in data["k5_audit_finding_codes"]
    _assert_clean((tmp_path / OUTPUT / "summary.json").read_bytes())


def test_rejected_summary_still_carries_the_disclosures(tmp_path):
    terms(tmp_path)
    (tmp_path / ARCHIVE).parent.mkdir(parents=True)
    (tmp_path / ARCHIVE).write_bytes(b"not a zip at all")
    with pytest.raises(lx.Error, match="ARCHIVE_NOT_ZIP"):
        lx.run_pack(tmp_path, OUTPUT, archive=ARCHIVE, images_dir=IMAGES, terms_snapshot=TERMS)
    data = _assert_clean((tmp_path / OUTPUT / "summary.json").read_bytes())
    assert data["status"] == "rejected" and data["error_code"] == "ARCHIVE_NOT_ZIP"
    assert data["pending_user_decisions"] == list(lx.PENDING_USER_DECISIONS)
    assert data["near_duplicate_checked_at_full_scale"] is False


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"PK\x03\x04" + b"\x00" * 64, "ZIP_END_INVALID"),
        (b"PK\x05\x06" + b"\xff" * 30, "ZIP_LAYOUT_UNSUPPORTED"),
        (b"plain text, not an archive", "ARCHIVE_NOT_ZIP"),
    ],
)
def test_cli_corrupt_archive_exits_2_with_fixed_code_and_no_leak(tmp_path, body, code):
    terms(tmp_path)
    leaky = f"data/datasets/{LEAK_NAME}_{LEAK_PERSON}.zip"
    (tmp_path / leaky).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / leaky).write_bytes(body)
    args = cli(tmp_path)
    args[args.index(ARCHIVE)] = leaky
    completed = run_module(args)
    assert completed.returncode == 2
    for stream in (completed.stdout, completed.stderr):
        assert "Traceback" not in stream
        assert LEAK_NAME not in stream and LEAK_PERSON not in stream
        assert str(tmp_path) not in stream
    printed = json.loads(completed.stdout)
    assert printed == {"status": "rejected", "error_code": code, **lx.acquisition.FLAGS}
    data = _assert_clean((tmp_path / OUTPUT / "summary.json").read_bytes())
    assert data["error_code"] == code


def test_cli_bad_crc_member_is_caught_without_traceback_or_names(tmp_path):
    terms(tmp_path)
    archive = make_zip(tmp_path)
    with zipfile.ZipFile(archive) as container:
        info = next(i for i in container.infolist() if LEAK_PERSON in i.filename)
        start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    data = bytearray(archive.read_bytes())
    data[start + info.compress_size // 2] ^= 0xFF
    archive.write_bytes(bytes(data))
    completed = run_module(cli(tmp_path))
    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr and LEAK_PERSON not in completed.stderr
    assert LEAK_PERSON not in completed.stdout
    assert json.loads(completed.stdout)["error_code"] in {
        "ARCHIVE_CORRUPT_OR_NOT_ZIP",
        "ARCHIVE_DECOMPRESS_FAILED",
    }
    assert not (tmp_path / IMAGES).exists()


def test_cli_argument_errors_do_not_echo_values(tmp_path):
    completed = run_module(cli(tmp_path) + ["--password", "should-not-be-accepted"])
    assert completed.returncode == 2
    assert "should-not-be-accepted" not in completed.stderr + completed.stdout
    assert json.loads(completed.stdout)["error_code"] == "ARGUMENT_REJECTED"


def _zip_with(root, entries):
    path = root / ARCHIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as container:
        for info, body in entries:
            container.writestr(info, body)
    return path


def _lx1(root):
    return lx.run_pack(root, OUTPUT, archive=ARCHIVE, images_dir=IMAGES, stages=("lx1",))


def test_safe_extract_rejects_symlink_and_device_members(tmp_path):
    for mode in (stat.S_IFLNK | 0o777, stat.S_IFCHR | 0o644):
        info = zipfile.ZipInfo("0_PersonA_20_f.jpg")
        info.external_attr = mode << 16
        _zip_with(tmp_path, [(info, b"target")])
        with pytest.raises(lx.Error, match="SPECIAL_MEMBER"):
            _lx1(tmp_path)
        assert not (tmp_path / IMAGES).exists()


def test_safe_extract_rejects_nfc_and_casefold_duplicate_names(tmp_path):
    for first, second in (("1_Ze\u0301ta_20_f.jpg", "1_Z\u00e9ta_20_f.jpg"), ("A.jpg", "a.jpg")):
        _zip_with(tmp_path, [(first, b"one"), (second, b"two")])
        with pytest.raises(lx.Error, match="DUPLICATE_MEMBER_PATH"):
            _lx1(tmp_path)
        assert not (tmp_path / IMAGES).exists()


def test_safe_extract_rejects_high_compression_ratio(tmp_path):
    _zip_with(tmp_path, [("0_PersonA_20_f.jpg", b"\x00" * (2 * 1024**2))])
    with pytest.raises(lx.Error, match="COMPRESSION_RATIO_LIMIT"):
        _lx1(tmp_path)
    assert not (tmp_path / IMAGES).exists()


def test_safe_extract_rejects_prepended_data_and_overlapping_entries(tmp_path):
    archive = make_zip(tmp_path)
    original = archive.read_bytes()
    archive.write_bytes(b"MZ-stub" + original)
    with pytest.raises(lx.Error, match="ARCHIVE_NOT_ZIP"):
        _lx1(tmp_path)
    # Point the second central entry at the first local header (overlap bomb shape).
    data = bytearray(original)
    archive.write_bytes(original)
    with zipfile.ZipFile(archive) as container:
        start = container.start_dir
    second = start + 46 + int.from_bytes(data[start + 28 : start + 30], "little")
    second += int.from_bytes(data[start + 30 : start + 32], "little")
    second += int.from_bytes(data[start + 32 : start + 34], "little")
    assert data[second : second + 4] == b"PK\x01\x02"
    data[second + 42 : second + 46] = (0).to_bytes(4, "little")
    archive.write_bytes(bytes(data))
    with pytest.raises(lx.Error, match="ZIP_ENTRY_OVERLAP|ZIP_LOCAL_HEADER_MISMATCH"):
        _lx1(tmp_path)
    assert not (tmp_path / IMAGES).exists()


@pytest.mark.parametrize(
    "images_dir",
    [
        "data",
        "data/datasets",
        "data/datasets/photos",
        "data/datasets/agedb/inner",
        "../agedb",
        "data/datasets/../agedb",
        "/abs/agedb",
        "data\\datasets\\agedb",
    ],
)
def test_images_dir_scope_is_restricted(tmp_path, images_dir):
    with pytest.raises(lx.Error, match="IMAGES_DIR_SCOPE"):
        lx.run_pack(tmp_path, OUTPUT, images_dir=images_dir, stages=("lx1",))


def test_reused_folder_is_verified_against_zip_central_directory(tmp_path):
    terms(tmp_path)
    make_zip(tmp_path, encrypted=True)
    folder = write_images(tmp_path)
    victim = folder / "6_PersonB_30_m.jpg"
    body = bytearray(victim.read_bytes())
    body[-3] ^= 0xFF
    victim.write_bytes(bytes(body))
    with pytest.raises(lx.Error, match="EXTRACTED_ARCHIVE_CRC_MISMATCH"):
        _lx1(tmp_path)
    # The check runs before chmod: a mismatching folder is not made read-only.
    assert victim.stat().st_mode & 0o200
    victim.unlink()
    with pytest.raises(lx.Error, match="EXTRACTED_ARCHIVE_COUNT_MISMATCH"):
        _lx1(tmp_path)


def test_reused_folder_matches_zip_with_a_top_level_folder(tmp_path):
    files = {"AgeDB/" + name: size for name, size in FILES.items()}
    make_zip(tmp_path, files=files, encrypted=True)
    write_images(tmp_path)
    summary = _lx1(tmp_path)
    assert summary["extracted_archive_consistent"] is True
    assert summary["extracted_archive_crc_checked"] is True


def test_resume_recomputes_lx2_when_an_input_image_changes(tmp_path):
    terms(tmp_path)
    folder = write_images(tmp_path)
    first = _no_archive_run(tmp_path)
    again = _no_archive_run(tmp_path)
    assert again["lx2_resumed"] is True and again["inputs_stable"] is True
    _unlock(folder)
    jpeg(folder / "6_PersonB_30_m.jpg", (210, 210))
    changed = _no_archive_run(tmp_path)
    assert changed["lx2_resumed"] is False and changed["inputs_stable"] is False
    assert changed["inventory_sha256"] != first["inventory_sha256"]
    state = json.loads((tmp_path / OUTPUT / "local/state.json").read_text())
    assert state["stages"]["lx2"]["inventory_sha256"] == changed["inventory_sha256"]


def test_resume_discards_edited_lx2_outputs(tmp_path):
    terms(tmp_path)
    write_images(tmp_path)
    first = _no_archive_run(tmp_path)
    manifest = tmp_path / OUTPUT / "local/agedb-stats/manifest.json"
    _unlock(manifest.parent)
    manifest.write_text(manifest.read_text() + " ", encoding="utf-8")
    with pytest.raises(lx.Error, match="LX2_OUTPUT_CHANGED"):
        _no_archive_run(tmp_path, stages=("lx3",))
    rerun = _no_archive_run(tmp_path)
    assert rerun["lx2_resumed"] is False
    assert rerun["k5_manifest_sha256"] == first["k5_manifest_sha256"]


def test_lx3_alone_refuses_when_inputs_changed_since_lx2(tmp_path):
    terms(tmp_path)
    folder = write_images(tmp_path)
    _no_archive_run(tmp_path)
    _unlock(folder)
    jpeg(folder / "13_GammaPerson_33_f.jpg", (150, 150))
    with pytest.raises(lx.Error, match="LX2_STALE_RERUN_REQUIRED"):
        _no_archive_run(tmp_path, stages=("lx3",))
    data = _assert_clean((tmp_path / OUTPUT / "summary.json").read_bytes(), ("GammaPerson",))
    assert data["status"] == "rejected"


def test_failed_lx3_leaves_no_stale_ledger_and_stashes_old_summary(tmp_path, monkeypatch):
    terms(tmp_path)
    write_images(tmp_path)
    _no_archive_run(tmp_path)
    leftover = tmp_path / OUTPUT / "local/p03-screen"
    leftover.mkdir()
    (leftover / "half.json").write_text("{}", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise lx.Error("SYNTHETIC_LX3_FAILURE")

    monkeypatch.setattr(lx, "assign_identities", boom)
    with pytest.raises(lx.Error, match="SYNTHETIC_LX3_FAILURE"):
        _no_archive_run(tmp_path)
    local = tmp_path / OUTPUT / "local"
    assert not (local / "assignment-ledger.json").exists()
    assert not leftover.exists()
    state = json.loads((local / "state.json").read_text())
    assert "lx3" not in state["stages"] and state["last_error_code"] == "SYNTHETIC_LX3_FAILURE"
    current = json.loads((tmp_path / OUTPUT / "summary.json").read_text())
    assert current["status"] == "rejected"
    assert json.loads((local / "summary.stale.json").read_text())["status"] == "passed"


def test_lx2_needs_review_propagates_to_summary_status_and_exit_code(tmp_path, capsys):
    terms(tmp_path)
    folder = write_images(tmp_path)
    jpeg(folder / "not-an-agedb-name.jpg")
    args = cli(tmp_path)
    del args[args.index("--archive") : args.index("--archive") + 2]
    assert lx.main(args) == 1
    data = _assert_clean((tmp_path / OUTPUT / "summary.json").read_bytes(), ("not-an-agedb",))
    assert data["status"] == "needs_review" and data["lx2_status"] == "needs_review"
    assert data["k5_audit_status"] in lx.K5_AUDIT_VALUES
    capsys.readouterr()


def test_small_cell_suppression_is_refused_until_the_user_decides(tmp_path, capsys):
    terms(tmp_path)
    make_zip(tmp_path)
    assert lx.main(cli(tmp_path, extra=["--suppress-small-cells"])) == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["error_code"] == "SMALL_CELL_SUPPRESSION_POLICY_UNSETTLED"
    assert not (tmp_path / IMAGES).exists()


def test_powershell_entry_keeps_exit_codes_and_caller_state():
    text = (ROOT / "tools/lx-local.ps1").read_text(encoding="utf-8")
    assert text.startswith("#Requires -Version 5.1")
    assert "Write-Error" not in text  # would turn the exit-2 path into a terminating error
    assert "Push-Location -LiteralPath $Root" in text and "Pop-Location" in text
    assert "-B -m preprocessing.lx_local @args" in text and "exit $Code" in text
    assert "WindowsApps" in text and "-3.11" in text
    assert "password" not in text.replace("does not accept or store a password", "").lower()
