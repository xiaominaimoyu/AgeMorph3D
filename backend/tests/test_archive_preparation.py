"""Bounded synthetic archives, K5 provenance, decoder and EXIF pixel-center checks."""

import copy
import hashlib
import importlib
import io
import json
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
data = importlib.import_module("preprocessing.archive_preparation")
metadata = importlib.import_module("preprocessing.dataset_manifest")

OUTPUT = "output/research/prepared-v1"
SOURCE = "output/research/input"
PIXELS = [(11, 0, 0), (22, 0, 0), (33, 0, 0), (44, 0, 0), (55, 0, 0), (66, 0, 0)]


def sha(body):
    return hashlib.sha256(body).hexdigest()


def image_bytes(orientation=None, mode="RGB", format="PNG", size=(2, 3)):
    with Image.new(mode, size) as image:
        if mode == "RGB" and size == (2, 3):
            image.putdata(PIXELS)
        elif mode == "RGBA":
            image.putdata([(10, 20, 30, 40)] * (size[0] * size[1]))
        stream = io.BytesIO()
        kwargs = {}
        if orientation is not None:
            exif = Image.Exif()
            exif[274] = orientation
            exif[315] = "synthetic author must not propagate"
            kwargs["exif"] = exif
        image.save(stream, format=format, **kwargs)
        return stream.getvalue()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def pin(root, path):
    body = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "bytes": len(body), "sha256": sha(body)}


def make_case(root, kind="zip", members=None, *, orientation=None):
    base = root / SOURCE
    base.mkdir(parents=True)
    if members is None:
        members = [("images/a.png", image_bytes(orientation)), ("notes.txt", b"synthetic only")]
    archive = base / (
        "source.zip" if kind == "zip" else "source.tar.gz" if kind == "tar_gz" else "source.tar"
    )
    if kind == "zip":
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as container:
            for name, body in members:
                container.writestr(name, body)
    else:
        with tarfile.open(
            archive, "w:gz" if kind == "tar_gz" else "w", format=tarfile.USTAR_FORMAT
        ) as container:
            for name, body in members:
                info = tarfile.TarInfo(name)
                info.size = len(body)
                container.addfile(info, io.BytesIO(body))
    archive.chmod(stat.S_IREAD)
    archive_pin = pin(root, archive)
    acquisition = {
        "schema_id": data.acquisition.SCHEMA,
        "status": "passed",
        "records": [
            {
                "path": archive_pin["path"],
                "expected_bytes": archive_pin["bytes"],
                "expected_sha256": archive_pin["sha256"],
                "status": "downloaded",
                "integrity_verified": True,
                "published_read_only": True,
            }
        ],
    }
    receipt = base / "acquisition.json"
    save_json(receipt, acquisition)
    records = []
    for name, body in members:
        if Path(name).suffix.lower() not in data.IMAGE_SUFFIXES:
            continue
        records.append(
            {
                "sample_id": f"sample:{len(records)}",
                "dataset_id": "synthetic",
                "file": {
                    "path": OUTPUT + "/files/" + name,
                    "bytes": len(body),
                    "sha256": sha(body),
                },
                "subject_id": None,
                "linked_subject_id": None,
                "parent_id": None,
                "kind": "original",
                "use": "development",
                "age": metadata.age_label("unknown"),
                "age_source": "unknown",
                "exposure": {
                    "preprocessing": "unknown",
                    "model_selection": "unknown",
                    "result_inspection": "unknown",
                },
                "processing": {"status": "not_checked", "reason": None},
            }
        )
    manifest = {
        "schema_id": metadata.SCHEMA,
        "schema_version": 1,
        "task": metadata.TASK,
        "manifest_id": "synthetic-unassigned",
        "origin": None,
        "datasets": [
            {
                "dataset_id": "synthetic",
                "version": "fixture-v1",
                "purpose_registration": {"status": "unresolved", "evidence": None},
                "identity_review": {"status": "pending", "evidence": None},
                "training_overlap": {"status": "unknown", "evidence": None},
                "near_duplicate_review": {"status": "pending", "evidence": None},
            }
        ],
        "records": records,
    }
    manifest_path = base / "metadata.json"
    save_json(manifest_path, manifest)
    plan = {
        "schema_id": data.SCHEMA,
        "plan_id": "synthetic-v1",
        "archive": {**archive_pin, "format": kind},
        "acquisition_receipt": pin(root, receipt),
        "metadata_manifest": pin(root, manifest_path),
        "limits": {
            "members": 32,
            "member_bytes": 1024**2,
            "total_bytes": 4 * 1024**2,
            "image_bytes": 1024**2,
            "image_pixels": 1024**2,
            "normalized_bytes": 1024**2,
            "reserve_bytes": 0,
        },
    }
    return {
        "root": root,
        "archive": archive,
        "plan": plan,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "acquisition": acquisition,
        "receipt_path": receipt,
        "members": members,
    }


def refresh(case):
    root, plan = case["root"], case["plan"]
    archive_pin = pin(root, case["archive"])
    plan["archive"].update(archive_pin)
    row = case["acquisition"]["records"][0]
    row.update(expected_bytes=archive_pin["bytes"], expected_sha256=archive_pin["sha256"])
    save_json(case["receipt_path"], case["acquisition"])
    save_json(case["manifest_path"], case["manifest"])
    plan["acquisition_receipt"] = pin(root, case["receipt_path"])
    plan["metadata_manifest"] = pin(root, case["manifest_path"])
    path = root / SOURCE / "plan.json"
    save_json(path, plan)
    return path, sha(path.read_bytes())


def run(case, output=OUTPUT):
    path, checksum = refresh(case)
    return data.prepare(case["root"], path.relative_to(case["root"]).as_posix(), checksum, output)


@pytest.fixture(autouse=True)
def clean_readonly(tmp_path):
    yield
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("kind", ["zip", "tar", "tar_gz"])
def test_inventory_bytes_k5_and_readonly_outputs(tmp_path, kind):
    case = make_case(tmp_path, kind)
    before = case["archive"].read_bytes()
    manifest = copy.deepcopy(case["manifest"])
    result = run(case)
    assert result["status"] == "passed" and result["inputs_stable"]
    assert result["summary"] == {
        "archive_members": 2,
        "regular_files": 2,
        "requested_images": 1,
        "decoded_images": 1,
        "failed_images": 0,
        "historical_failed_records_retained": 0,
    }
    assert len(result["inventory"]) == 2
    for row in result["inventory"]:
        path = tmp_path / row["file"]["path"]
        assert pin(tmp_path, path) == row["file"] and not path.stat().st_mode & 0o222
    assert case["archive"].read_bytes() == before
    prepared = json.loads((tmp_path / OUTPUT / "prepared-manifest.json").read_text())
    assert prepared["records"][0]["age"] == manifest["records"][0]["age"]
    original = copy.deepcopy(manifest["records"][0])
    original["exposure"]["preprocessing"] = "yes"
    assert prepared["records"] == [original]
    metadata.validate_manifest(prepared)
    audit = json.loads((tmp_path / OUTPUT / "metadata-audit.json").read_text())
    assert not audit["binary_integrity_verified"] and not audit["formal_dataset_ready"]
    assert all(result[key] is False for key in data.acquisition.FLAGS)
    assert result["records"][0]["source_orientation"] is None
    assert result["permission_assessment"] == result["full_quality_assessment"] == "not_performed"


@pytest.mark.parametrize(
    "orientation,expected,width",
    [
        (1, [11, 22, 33, 44, 55, 66], 2),
        (2, [22, 11, 44, 33, 66, 55], 2),
        (3, [66, 55, 44, 33, 22, 11], 2),
        (4, [55, 66, 33, 44, 11, 22], 2),
        (5, [11, 33, 55, 22, 44, 66], 3),
        (6, [55, 33, 11, 66, 44, 22], 3),
        (7, [66, 44, 22, 55, 33, 11], 3),
        (8, [22, 44, 66, 11, 33, 55], 3),
    ],
)
def test_all_exif_orientations_match_native_pixels_and_coordinate_matrix(
    tmp_path, orientation, expected, width
):
    result = run(make_case(tmp_path, orientation=orientation))
    assert result["status"] == "passed"
    row = result["records"][0]
    with Image.open(tmp_path / row["normalized"]["path"]) as image:
        assert (
            image.width == width
            and [image.getpixel((x, y))[0] for y in range(image.height) for x in range(image.width)]
            == expected
        )
        assert not image.getexif() and not image.info
        matrix = row["original_to_normalized"]
        for index, pixel in enumerate(PIXELS):
            x, y = index % 2, index // 2
            xx = matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]
            yy = matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]
            assert image.getpixel((xx, yy)) == pixel


def test_rgba_alpha_retained(tmp_path):
    case = make_case(tmp_path, members=[("alpha.png", image_bytes(mode="RGBA"))])
    result = run(case)
    with Image.open(tmp_path / result["records"][0]["normalized"]["path"]) as image:
        assert image.mode == "RGBA" and image.getpixel((0, 0)) == (10, 20, 30, 40)


def test_jpeg_is_fully_decoded_and_normalized(tmp_path):
    result = run(make_case(tmp_path, members=[("photo.jpg", image_bytes(6, format="JPEG"))]))
    assert result["status"] == "passed"
    assert result["records"][0]["normalized_size"] == [3, 2]


def test_failure_denominator_labels_and_historical_failures_retained(tmp_path):
    body = image_bytes()
    members = [("a.png", body), ("b.png", b"broken"), ("c.png", body), ("d.png", body)]
    case = make_case(tmp_path, members=members)
    rows = case["manifest"]["records"]
    rows[0].update(age=metadata.age_label("exact", 70), age_source="dataset_annotation")
    rows[0]["processing"] = {"status": "failed", "reason": "NO_FACE"}
    rows[2].update(
        age=metadata.age_label("interval", lower=50, upper=69), age_source="dataset_annotation"
    )
    rows[3]["file"]["sha256"] = "0" * 64
    result = run(case)
    assert result["status"] == "failed" and result["summary"]["requested_images"] == 4
    assert [r["status"] for r in result["records"]] == ["decoded", "failed", "decoded", "failed"]
    assert result["records"][1]["error_code"] == "IMAGE_DECODE_FAILED"
    assert result["records"][3]["error_code"] == "IMAGE_PIN_MISMATCH"
    prepared = json.loads((tmp_path / OUTPUT / "prepared-manifest.json").read_text())
    for old, new in zip(rows, prepared["records"], strict=True):
        for field in [
            "age",
            "age_source",
            "subject_id",
            "linked_subject_id",
            "parent_id",
            "kind",
            "use",
            "processing",
            "file",
        ]:
            assert new[field] == old[field]
        assert new["exposure"]["preprocessing"] == "yes"
    assert result["summary"]["historical_failed_records_retained"] == 1


@pytest.mark.parametrize("kind", ["zip", "tar", "tar_gz"])
@pytest.mark.parametrize(
    "bad",
    [
        "../escape.png",
        "/escape.png",
        "C:/escape.png",
        "a\\escape.png",
        "a/../x.png",
        "a//x.png",
        "NUL.png",
        "a./x.png",
    ],
)
def test_unsafe_member_rejected_before_output(tmp_path, kind, bad):
    case = make_case(tmp_path, kind, members=[("ok.png", image_bytes()), (bad, b"bad")])
    # Keep K5 valid so rejection is about archive structure.
    case["manifest"]["records"] = case["manifest"]["records"][:1]
    with pytest.raises((ValueError, tarfile.TarError)):
        run(case)
    assert not (tmp_path / OUTPUT).exists() and not (tmp_path / "escape.png").exists()


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    "members",
    [
        [("a.png", b"one"), ("A.PNG", b"two")],
        [("a.png", b"one"), ("a.png/child", b"two")],
        [("dir/child.png", b"one"), ("dir", b"two")],
    ],
)
def test_member_duplicates_and_file_directory_conflicts(tmp_path, kind, members):
    case = make_case(tmp_path, kind, members=members)
    case["manifest"]["records"] = case["manifest"]["records"][:1]
    with pytest.raises(data.Error):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize("special", ["symlink", "hardlink", "fifo", "device", "pax"])
def test_tar_links_devices_and_extended_headers_rejected(tmp_path, special):
    case = make_case(tmp_path, "tar")
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as container:
        info = tarfile.TarInfo("images/a.png")
        if special == "pax":
            info.pax_headers = {"comment": "unsupported"}
        else:
            info.type = {
                "symlink": tarfile.SYMTYPE,
                "hardlink": tarfile.LNKTYPE,
                "fifo": tarfile.FIFOTYPE,
                "device": tarfile.CHRTYPE,
            }[special]
            info.linkname = "../../outside"
        container.addfile(info)
    path.chmod(stat.S_IREAD)
    with pytest.raises(data.Error):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_zip_symlink_rejected(tmp_path):
    case = make_case(tmp_path)
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    with zipfile.ZipFile(path, "w") as container:
        info = zipfile.ZipInfo("images/a.png")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        container.writestr(info, "../../outside")
    path.chmod(stat.S_IREAD)
    with pytest.raises(data.Error, match="SPECIAL_MEMBER"):
        run(case)


@pytest.mark.parametrize("field,value", [("members", 1), ("member_bytes", 1), ("total_bytes", 1)])
@pytest.mark.parametrize("kind", ["zip", "tar_gz"])
def test_declared_archive_limits_before_writes(tmp_path, kind, field, value):
    case = make_case(tmp_path, kind)
    case["plan"]["limits"][field] = value
    with pytest.raises(data.Error):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("image_bytes", 1, "IMAGE_BYTE_LIMIT"),
        ("image_pixels", 1, "IMAGE_PIXEL_LIMIT"),
        ("normalized_bytes", 1, "NORMALIZED_SIZE_LIMIT"),
    ],
)
def test_image_and_derived_size_limits_keep_failure_record(tmp_path, field, value, code):
    case = make_case(tmp_path)
    case["plan"]["limits"][field] = value
    result = run(case)
    assert result["records"][0]["error_code"] == code
    assert result["summary"]["failed_images"] == 1 and result["records"][0]["normalized"] is None


@pytest.mark.parametrize("orientation", [0, 9])
def test_invalid_orientation_not_silently_normalized(tmp_path, orientation):
    result = run(make_case(tmp_path, orientation=orientation))
    assert result["records"][0]["error_code"] == "INVALID_EXIF_ORIENTATION"


def test_unsupported_and_animated_formats_fail_explicitly(tmp_path):
    stream = io.BytesIO()
    with Image.new("RGB", (2, 2), "red") as a, Image.new("RGB", (2, 2), "blue") as b:
        a.save(stream, format="PNG", save_all=True, append_images=[b])
    case = make_case(
        tmp_path,
        members=[("animated.png", stream.getvalue()), ("image.bmp", image_bytes(format="BMP"))],
    )
    result = run(case)
    assert [r["error_code"] for r in result["records"]] == [
        "ANIMATED_IMAGE_UNSUPPORTED",
        "IMAGE_FORMAT_UNSUPPORTED",
    ]


def test_metadata_pins_and_acquisition_row_must_match(tmp_path):
    case = make_case(tmp_path)
    case["acquisition"]["records"][0]["integrity_verified"] = False
    with pytest.raises(data.Error, match="ARCHIVE_RECEIPT_PIN_MISMATCH"):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_unsafe_source_readonly_or_existing_output_refused(tmp_path):
    case = make_case(tmp_path)
    case["archive"].chmod(stat.S_IREAD | stat.S_IWRITE)
    with pytest.raises(data.Error, match="ARCHIVE_NOT_READ_ONLY"):
        run(case)
    case["archive"].chmod(stat.S_IREAD)
    result = run(case)
    preserved = (tmp_path / result["receipt"]).read_bytes()
    with pytest.raises(data.Error, match="OUTPUT_MUST_BE_NEW"):
        run(case)
    assert (tmp_path / result["receipt"]).read_bytes() == preserved


@pytest.mark.parametrize(
    "change,code",
    [
        ("record_path", "K5_PATH_OUTSIDE_OUTPUT"),
        ("missing_member", "K5_MEMBER_MISSING_OR_DUPLICATE"),
        ("unbound_image", "UNBOUND_IMAGE_MEMBER"),
        ("output", "OUTPUT_MUST_BE_NEW"),
    ],
)
def test_k5_binding_and_output_scope(tmp_path, change, code):
    case = make_case(tmp_path, members=[("a.png", image_bytes()), ("b.png", image_bytes())])
    output = OUTPUT
    if change == "record_path":
        case["manifest"]["records"][0]["file"]["path"] = "data/unrelated.png"
    elif change == "missing_member":
        case["manifest"]["records"][0]["file"]["path"] = OUTPUT + "/files/missing.png"
    elif change == "unbound_image":
        case["manifest"]["records"].pop()
    else:
        output = "docs/generated"
    with pytest.raises(data.Error, match=code):
        run(case, output)
    assert not (tmp_path / output).exists()


def test_low_space_no_output(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        data.shutil, "disk_usage", lambda _: type(usage)(usage.total, usage.used, 0)
    )
    with pytest.raises(data.Error, match="INSUFFICIENT_SPACE"):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_zip_crc_failure_is_recorded_and_other_members_continue(tmp_path):
    case = make_case(tmp_path)
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as container:
        for name, body in case["members"]:
            container.writestr(name, body)
    body = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as container:
        info = container.infolist()[0]
        start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    body[start] ^= 1
    path.write_bytes(body)
    path.chmod(stat.S_IREAD)
    result = run(case)
    assert result["status"] == "failed" and len(result["inventory"]) == 2
    assert result["inventory"][0]["status"] == "failed"
    assert result["inventory"][1]["status"] == "extracted"
    assert result["records"][0]["error_code"] == "SOURCE_NOT_EXTRACTED"


def test_zip_directory_budget_is_checked_before_zipfile_allocation(tmp_path):
    case = make_case(tmp_path)
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    body = bytearray(path.read_bytes())
    end = body.rfind(b"PK\x05\x06")
    struct.pack_into("<L", body, end + 12, 1024**2 + 1)
    path.write_bytes(body)
    path.chmod(stat.S_IREAD)
    with pytest.raises(data.Error, match="ZIP_DIRECTORY_LIMIT"):
        run(case)


def test_tar_nonzero_tail_and_gzip_crc_are_rejected(tmp_path):
    case = make_case(tmp_path, "tar_gz")
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    body = bytearray(path.read_bytes())
    body[-8] ^= 1
    path.write_bytes(body)
    path.chmod(stat.S_IREAD)
    with pytest.raises((OSError, EOFError)):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_tar_nonzero_tail_is_not_silently_ignored(tmp_path):
    case = make_case(tmp_path, "tar")
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    body = bytearray(path.read_bytes())
    body[-1] = 1
    path.write_bytes(body)
    path.chmod(stat.S_IREAD)
    with pytest.raises(data.Error, match="TRAILING_TAR_DATA"):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_tar_extension_payload_is_bounded_before_interpretation(tmp_path):
    case = make_case(tmp_path, "tar")
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    info = tarfile.TarInfo("large-metadata")
    info.type = tarfile.XHDTYPE
    info.size = 512 * 1024
    path.write_bytes(info.tobuf() + b"0" * info.size + b"\0" * 1024)
    path.chmod(stat.S_IREAD)
    case["plan"]["limits"]["total_bytes"] = 1024
    with pytest.raises(data.Error, match="TAR_STREAM_LIMIT"):
        run(case)
    assert not (tmp_path / OUTPUT).exists()


def test_out_of_scope_label_and_research_use_not_filtered_or_reassigned(tmp_path):
    case = make_case(tmp_path)
    record = case["manifest"]["records"][0]
    record.update(
        age=metadata.age_label("exact", 17),
        age_source="dataset_annotation",
        use="calibration_research",
    )
    assert run(case)["status"] == "passed"
    prepared = json.loads((tmp_path / OUTPUT / "prepared-manifest.json").read_text())
    assert prepared["records"][0]["age"] == record["age"]
    assert prepared["records"][0]["use"] == "calibration_research"


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_real_directory_entry_is_in_complete_inventory(tmp_path, kind):
    case = make_case(tmp_path, kind)
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as container:
            container.writestr("images/", b"")
            for name, body in case["members"]:
                container.writestr(name, body)
    else:
        with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as container:
            directory = tarfile.TarInfo("images")
            directory.type = tarfile.DIRTYPE
            container.addfile(directory)
            for name, body in case["members"]:
                info = tarfile.TarInfo(name)
                info.size = len(body)
                container.addfile(info, io.BytesIO(body))
    path.chmod(stat.S_IREAD)
    result = run(case)
    assert result["status"] == "passed" and result["summary"]["archive_members"] == 3
    assert result["inventory"][0]["status"] == "directory"


def test_directory_members_and_member_named_part_do_not_collide_with_staging(tmp_path):
    case = make_case(
        tmp_path, members=[("a.part", b"keep"), ("a", b"plain"), ("photo.png", image_bytes())]
    )
    assert run(case)["status"] == "passed"
    assert (tmp_path / OUTPUT / "files/a.part").read_bytes() == b"keep"


@pytest.mark.parametrize(
    "field,value",
    [("members", True), ("total_bytes", 0), ("image_pixels", 2**40), ("reserve_bytes", -1)],
)
def test_invalid_limit_types_rejected(tmp_path, field, value):
    case = make_case(tmp_path)
    case["plan"]["limits"][field] = value
    with pytest.raises(data.Error, match="INVALID_LIMITS"):
        run(case)


def test_cli_success_record_failure_and_input_rejection(tmp_path):
    case = make_case(tmp_path)
    path, checksum = refresh(case)

    def cli(expected, output):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "preprocessing.archive_preparation",
                "--root",
                str(tmp_path),
                "--plan",
                path.relative_to(tmp_path).as_posix(),
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

    invalid = cli("0" * 64, OUTPUT)
    assert invalid.returncode == 2 and json.loads(invalid.stdout)["status"] == "rejected"
    valid = cli(checksum, OUTPUT)
    assert valid.returncode == 0 and json.loads(valid.stdout)["status"] == "passed"
    assert not valid.stderr and not invalid.stderr


# --- FG-4: dataset plan v3 §5 item 4 safe-loading negatives -----------------------
# Every malicious archive must be refused before the output directory exists, leaving the
# whole workspace byte-identical and nothing written next to or above it.

ESCAPES = ("escape.png", "escape.txt", "evil.txt", "outside", "passwd")


def snapshot(root):
    state = {}
    for path in sorted(root.rglob("*")):
        key = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[key] = ("link", str(path.readlink()))
        elif path.is_file():
            state[key] = ("file", path.read_bytes())
        else:
            state[key] = ("dir", None)
    return state


def assert_rejected_cleanly(case, code):
    root = case["root"]
    path, checksum = refresh(case)
    before = snapshot(root)
    with pytest.raises(data.Error, match=code):
        data.prepare(root, path.relative_to(root).as_posix(), checksum, OUTPUT)
    assert snapshot(root) == before
    assert not (root / OUTPUT).exists() and not (root / "output/research/prepared-v1").exists()
    for name in ESCAPES:
        assert not (root.parent / name).exists() and not (root / name).exists()


def rewrite(case, write):
    path = case["archive"]
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    write(path)
    path.chmod(stat.S_IREAD)


def zip_with(case, entries, compression=zipfile.ZIP_DEFLATED):
    def write(path):
        with zipfile.ZipFile(path, "w", compression) as container:
            container.writestr("ok.png", image_bytes())
            for entry, body in entries:
                container.writestr(entry, body)

    rewrite(case, write)


def tar_with(case, infos, kind="tar", fmt=tarfile.USTAR_FORMAT):
    def write(path):
        mode = "w:gz" if kind == "tar_gz" else "w"
        with tarfile.open(path, mode, format=fmt) as container:
            body = image_bytes()
            ok = tarfile.TarInfo("ok.png")
            ok.size = len(body)
            container.addfile(ok, io.BytesIO(body))
            for info, body in infos:
                container.addfile(info, io.BytesIO(body) if body is not None else None)

    rewrite(case, write)


def one_image_case(root, kind="zip"):
    case = make_case(root, kind, members=[("ok.png", image_bytes())])
    return case


ZIP_SLIP_NAMES = [
    "../evil.txt",
    "../../../../evil.txt",
    "a/../../evil.txt",
    "/evil.txt",
    "//server/share/evil.txt",
    "C:/evil.txt",
    "C:evil.txt",
    "c:\\evil.txt",
    "..\\evil.txt",
    "a\\..\\..\\evil.txt",
    "\\\\server\\share\\evil.txt",
    "a/./evil.txt",
    "a//evil.txt",
    "evil.txt:stream",
    "CON.txt",
    "aux",
    "a /evil.txt",
    "a./evil.txt",
    "evil\x01.txt",
]


@pytest.mark.parametrize("name", ZIP_SLIP_NAMES)
def test_zip_slip_variants_rejected_before_any_write(tmp_path, name):
    case = one_image_case(tmp_path)
    info = zipfile.ZipInfo(name)
    zip_with(case, [(info, b"escape")])
    assert_rejected_cleanly(case, "INVALID_PATH|ZIP_NAME_OR_ENCRYPTION_UNSUPPORTED")


@pytest.mark.parametrize(
    "mode",
    [stat.S_IFLNK | 0o777, stat.S_IFCHR | 0o600, stat.S_IFBLK | 0o600, stat.S_IFIFO | 0o600]
    + [stat.S_IFSOCK | 0o600],
)
@pytest.mark.parametrize("target", ["../../outside", "/etc/passwd", "ok.png"])
def test_zip_links_devices_and_sockets_rejected(tmp_path, mode, target):
    case = one_image_case(tmp_path)
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = mode << 16
    zip_with(case, [(info, target.encode())])
    assert_rejected_cleanly(case, "SPECIAL_MEMBER")


def test_zip_directory_with_payload_and_encryption_flag_rejected(tmp_path):
    case = one_image_case(tmp_path)
    zip_with(case, [(zipfile.ZipInfo("dir/"), b"hidden")])
    assert_rejected_cleanly(case, "MEMBER_SIZE_INVALID")
    case = one_image_case(tmp_path / "enc")

    def write(path):  # zipfile cannot write encrypted entries; set the flag bit directly
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as container:
            container.writestr("ok.png", image_bytes())
            container.writestr("secret.txt", b"x")
        body = bytearray(path.read_bytes())
        central = _central_offsets(body)[1]
        local = struct.unpack_from("<L", body, central + 42)[0]
        body[local + 6] |= 1
        body[central + 8] |= 1
        path.write_bytes(body)

    rewrite(case, write)
    assert_rejected_cleanly(case, "ZIP_NAME_OR_ENCRYPTION_UNSUPPORTED")


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    "names",
    [
        ["dup.txt", "dup.txt"],
        ["Dup.txt", "dUP.TXT"],
        ["caf\u00e9.txt", "cafe\u0301.txt"],
        ["ok.png", "OK.PNG"],
    ],
)
def test_duplicate_names_including_case_and_unicode_forms_rejected(tmp_path, kind, names):
    case = one_image_case(tmp_path, kind)
    if kind == "zip":
        with warnings_ignored():
            zip_with(case, [(n, b"x") for n in names])
    else:
        infos = []
        for n in names:
            info = tarfile.TarInfo(n)
            info.size = 1
            infos.append((info, b"x"))
        tar_with(case, infos, fmt=tarfile.GNU_FORMAT)
    assert_rejected_cleanly(case, "DUPLICATE_MEMBER_PATH")


def warnings_ignored():
    import warnings

    manager = warnings.catch_warnings()
    manager.__enter__()
    warnings.simplefilter("ignore")

    class _Exit:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            manager.__exit__(*exc)

    return _Exit()


def _central_offsets(body):
    found, start = [], 0
    while (index := body.find(b"PK\x01\x02", start)) >= 0:
        found.append(index)
        start = index + 4
    return found


def test_zip_overlapping_entries_rejected(tmp_path):
    case = one_image_case(tmp_path)

    def write(path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as container:
            container.writestr("ok.png", image_bytes())
            container.writestr("a.txt", b"same")
            container.writestr("b.txt", b"same")
        body = bytearray(path.read_bytes())
        central = _central_offsets(body)
        a_offset = struct.unpack_from("<L", body, central[1] + 42)[0]
        struct.pack_into("<L", body, central[2] + 42, a_offset)  # b.txt reuses a.txt bytes
        path.write_bytes(body)

    rewrite(case, write)
    assert_rejected_cleanly(case, "ZIP_ENTRY_OVERLAP|ZIP_LOCAL_HEADER_MISMATCH")


def test_zip_local_header_name_differing_from_directory_rejected(tmp_path):
    case = one_image_case(tmp_path)

    def write(path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as container:
            container.writestr("ok.png", image_bytes())
            container.writestr("safe.txt", b"x")
        body = bytearray(path.read_bytes())
        local = body.find(b"safe.txt")
        body[local : local + 8] = b"../e.txt"
        path.write_bytes(body)

    rewrite(case, write)
    assert_rejected_cleanly(case, "ZIP_LOCAL_HEADER_MISMATCH")


def test_zip_entry_reaching_into_central_directory_rejected(tmp_path):
    case = one_image_case(tmp_path)

    def write(path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as container:
            container.writestr("ok.png", image_bytes())
            container.writestr("a.txt", b"abcd")
        body = bytearray(path.read_bytes())
        central = _central_offsets(body)
        struct.pack_into("<L", body, central[1] + 20, 4096)  # compressed size overruns
        path.write_bytes(body)

    rewrite(case, write)
    assert_rejected_cleanly(case, "ZIP_ENTRY_OVERLAP")


def test_zip_compression_bomb_rejected_by_ratio(tmp_path):
    case = one_image_case(tmp_path)
    case["plan"]["limits"].update(member_bytes=8 * 1024**2, total_bytes=16 * 1024**2)
    zip_with(case, [("zeros.bin", b"\0" * (4 * 1024**2))])
    assert_rejected_cleanly(case, "ZIP_COMPRESSION_RATIO_LIMIT")


def test_zip_declared_size_bomb_rejected(tmp_path):
    case = one_image_case(tmp_path)

    def write(path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as container:
            container.writestr("ok.png", image_bytes())
            container.writestr("big.bin", b"x" * 2048)
        body = bytearray(path.read_bytes())
        central = _central_offsets(body)
        struct.pack_into("<L", body, central[1] + 24, 0x7FFFFFFF)  # declared uncompressed
        path.write_bytes(body)

    rewrite(case, write)
    assert_rejected_cleanly(case, "ZIP_COMPRESSION_RATIO_LIMIT|MEMBER_SIZE_LIMIT")


def test_zip_member_count_bomb_rejected(tmp_path):
    case = one_image_case(tmp_path)
    zip_with(case, [(f"f{i}.txt", b"") for i in range(40)])
    assert_rejected_cleanly(case, "ZIP_DIRECTORY_LIMIT|MEMBER_COUNT_LIMIT")


def test_zip_with_data_descriptors_and_distinct_unicode_names_still_passes(tmp_path):
    case = one_image_case(tmp_path)

    class Unseekable(io.RawIOBase):
        def __init__(self, target):
            self.target = target

        def writable(self):
            return True

        def write(self, chunk):
            return self.target.write(chunk)

    def write(path):
        with path.open("wb") as raw:
            with zipfile.ZipFile(Unseekable(raw), "w", zipfile.ZIP_DEFLATED) as container:
                container.writestr("ok.png", image_bytes())
                container.writestr("caf\u00e9.txt", b"one")
                container.writestr("cafe.txt", b"two")

    rewrite(case, write)
    with zipfile.ZipFile(case["archive"]) as container:
        assert all(info.flag_bits & 0x08 for info in container.infolist())
    result = run(case)
    assert result["status"] == "passed" and result["summary"]["archive_members"] == 3


TAR_SLIP_NAMES = [
    "../evil.txt",
    "../../../../evil.txt",
    "a/../../evil.txt",
    "/evil.txt",
    "/etc/passwd",
    "C:/evil.txt",
    "..\\evil.txt",
    "a/./evil.txt",
    "evil.txt:stream",
    "NUL",
]


@pytest.mark.parametrize("kind", ["tar", "tar_gz"])
@pytest.mark.parametrize("name", TAR_SLIP_NAMES)
def test_tar_slip_variants_rejected_before_any_write(tmp_path, kind, name):
    case = one_image_case(tmp_path, kind)
    info = tarfile.TarInfo(name)
    info.size = 6
    tar_with(case, [(info, b"escape")], kind)
    assert_rejected_cleanly(case, "INVALID_PATH|TAR_DATA_FILTER_REJECTED")


@pytest.mark.parametrize(
    "kind,link",
    [
        (tarfile.SYMTYPE, "../../outside"),
        (tarfile.SYMTYPE, "/etc/passwd"),
        (tarfile.LNKTYPE, "/etc/passwd"),
        (tarfile.LNKTYPE, "../outside"),
        (tarfile.LNKTYPE, "ok.png"),
        (tarfile.CHRTYPE, ""),
        (tarfile.BLKTYPE, ""),
        (tarfile.FIFOTYPE, ""),
        (tarfile.CONTTYPE, ""),
    ],
)
def test_tar_links_and_device_members_rejected(tmp_path, kind, link):
    case = one_image_case(tmp_path, "tar")
    info = tarfile.TarInfo("escape.txt")
    info.type, info.linkname = kind, link
    tar_with(case, [(info, None)])
    assert_rejected_cleanly(case, "SPECIAL_OR_EXTENDED_TAR_MEMBER|TAR_DATA_FILTER_REJECTED")


def test_tar_gnu_longname_and_pax_path_override_rejected(tmp_path):
    case = one_image_case(tmp_path, "tar")
    info = tarfile.TarInfo("d" * 120 + "/../../../evil.txt")
    info.size = 1
    tar_with(case, [(info, b"x")], fmt=tarfile.GNU_FORMAT)
    assert_rejected_cleanly(case, "SPECIAL_OR_EXTENDED_TAR_MEMBER")
    case = one_image_case(tmp_path / "pax", "tar")
    info = tarfile.TarInfo("innocent.txt")
    info.size, info.pax_headers = 1, {"path": "../../evil.txt"}
    tar_with(case, [(info, b"x")], fmt=tarfile.PAX_FORMAT)
    assert_rejected_cleanly(case, "SPECIAL_OR_EXTENDED_TAR_MEMBER")


@pytest.mark.parametrize("field", ["member_bytes", "total_bytes"])
def test_gzip_bomb_rejected_before_output(tmp_path, field):
    case = one_image_case(tmp_path, "tar_gz")
    info = tarfile.TarInfo("zeros.bin")
    info.size = 3 * 1024**2
    tar_with(case, [(info, b"\0" * info.size)], "tar_gz")
    assert case["archive"].stat().st_size < 64 * 1024
    assert_rejected_cleanly(case, "MEMBER_SIZE_LIMIT|TOTAL_UNPACKED_LIMIT|TAR_STREAM_LIMIT")


def test_gzip_stream_bomb_hidden_from_headers_rejected(tmp_path):
    case = one_image_case(tmp_path, "tar_gz")
    case["plan"]["limits"]["total_bytes"] = 64 * 1024
    body = image_bytes()
    ok = tarfile.TarInfo("ok.png")
    ok.size = len(body)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as container:
        container.addfile(ok, io.BytesIO(body))
    payload = stream.getvalue() + b"\0" * (8 * 1024**2)  # zero "padding" inflates the stream

    def write(path):
        import gzip

        path.write_bytes(gzip.compress(payload))

    rewrite(case, write)
    assert_rejected_cleanly(case, "TAR_STREAM_LIMIT")


@pytest.mark.parametrize(
    "name,kind,link,code",
    [
        ("/abs.txt", tarfile.REGTYPE, "", None),  # filter strips "/": repository rejects name
        ("../up.txt", tarfile.REGTYPE, "", "OutsideDestinationError"),
        ("link", tarfile.SYMTYPE, "../../outside", "LinkOutsideDestinationError"),
        ("link", tarfile.SYMTYPE, "/etc/passwd", "AbsoluteLinkError"),
        ("hard", tarfile.LNKTYPE, "/etc/passwd", "AbsoluteLinkError"),
        ("dev", tarfile.CHRTYPE, "", "SpecialFileError"),
        ("fifo", tarfile.FIFOTYPE, "", "SpecialFileError"),
    ],
)
def test_tar_data_filter_gate_matches_stdlib_policy(tmp_path, name, kind, link, code):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, link
    destination = tmp_path / "dest"
    if code is None:
        filtered = data.tar_data_filter(info, destination)
        assert filtered.name == "abs.txt"  # end-to-end "/evil.txt" is refused by name rules
        return
    with pytest.raises(data.Error, match="TAR_DATA_FILTER_REJECTED") as caught:
        data.tar_data_filter(info, destination)
    assert type(caught.value.__cause__).__name__ == code
    with pytest.raises(data.Error, match="TAR_FILTER_DESTINATION_REQUIRED"):
        data.tar_data_filter(tarfile.TarInfo("ok.txt"), None)


@pytest.mark.parametrize("kind", ["tar", "tar_gz"])
def test_every_tar_member_passes_data_filter_in_scan_and_extract(tmp_path, monkeypatch, kind):
    case = make_case(tmp_path, kind)
    seen, original = [], tarfile.data_filter

    def spy(member, destination):
        seen.append((member.name, Path(destination)))
        return original(member, destination)

    monkeypatch.setattr(tarfile, "data_filter", spy)
    assert run(case)["status"] == "passed"
    names = [name for name, _ in case["members"]]
    assert [name for name, _ in seen] == names + names
    assert {destination for _, destination in seen} == {tmp_path / OUTPUT / "files"}


@pytest.mark.parametrize("kind", ["tar", "tar_gz"])
def test_missing_tar_data_filter_refuses_with_explicit_code(tmp_path, monkeypatch, kind):
    """Python < 3.11.4 has no ``tarfile.data_filter``: refuse, never silently skip it."""
    case = make_case(tmp_path, kind)
    monkeypatch.delattr(tarfile, "data_filter")
    with pytest.raises(data.Error, match="TAR_DATA_FILTER_UNAVAILABLE"):
        data.tar_data_filter(tarfile.TarInfo("ok.txt"), tmp_path / "dest")
    assert_rejected_cleanly(case, "TAR_DATA_FILTER_UNAVAILABLE")


def test_zip_does_not_need_tar_data_filter(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.delattr(tarfile, "data_filter")
    assert run(case)["status"] == "passed"


def test_zip_member_failure_leaves_no_staging_part(tmp_path):
    case = make_case(tmp_path)

    def write(path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as container:
            for name, body in case["members"]:
                container.writestr(name, body)
        body = bytearray(path.read_bytes())
        with zipfile.ZipFile(path) as container:
            info = container.infolist()[0]
            start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        body[start] ^= 1
        path.write_bytes(body)

    rewrite(case, write)
    result = run(case)
    assert result["inventory"][0]["error_code"] == "MEMBER_READ_FAILED"
    assert list((tmp_path / OUTPUT / "stage").iterdir()) == []
    assert not (tmp_path / OUTPUT / "files/images/a.png").exists()


# ---- SN-6 round 2: strict, contiguous zip layout (concatenated/prefixed/gapped) ----


def _plain_zip_bytes(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as container:
        for name, body in members:
            container.writestr(name, body)
    return buffer.getvalue()


def _shift_offsets(body, prefix):
    """Prepend bytes and fix every central/end offset (self-consistent, like zip -A)."""
    body = bytearray(body)
    end = body.rfind(b"PK\x05\x06")
    for central in _central_offsets(body):
        offset = struct.unpack_from("<L", body, central + 42)[0]
        struct.pack_into("<L", body, central + 42, offset + len(prefix))
    start = struct.unpack_from("<L", body, end + 16)[0]
    struct.pack_into("<L", body, end + 16, start + len(prefix))
    return bytes(prefix) + bytes(body)


def test_zip_concatenated_archive_rejected_not_partially_read(tmp_path):
    case = one_image_case(tmp_path)
    hidden = _plain_zip_bytes([("hidden.png", image_bytes())])
    shown = _plain_zip_bytes([("ok.png", image_bytes())])
    rewrite(case, lambda path: path.write_bytes(hidden + shown))
    assert_rejected_cleanly(case, "ZIP_END_AMBIGUOUS|ZIP_DIRECTORY_NOT_ADJACENT")


def test_zip_self_consistent_prefix_is_a_gap(tmp_path):
    case = one_image_case(tmp_path)
    body = _plain_zip_bytes([("ok.png", image_bytes())])
    shifted = _shift_offsets(body, b"PK\x03\x04" + b"\0" * 60)
    rewrite(case, lambda path: path.write_bytes(shifted))
    assert_rejected_cleanly(case, "ZIP_ENTRY_GAP")


def test_zip_gap_before_central_directory_rejected(tmp_path):
    case = one_image_case(tmp_path)
    body = bytearray(_plain_zip_bytes([("ok.png", image_bytes())]))
    end = body.rfind(b"PK\x05\x06")
    start = struct.unpack_from("<L", body, end + 16)[0]
    gapped = body[:start] + b"\0" * 16 + body[start:]
    struct.pack_into("<L", gapped, end + 16 + 16, start + 16)
    rewrite(case, lambda path: path.write_bytes(bytes(gapped)))
    assert_rejected_cleanly(case, "ZIP_ENTRY_GAP")


def test_zip_trailing_bytes_and_comment_hiding_end_record_rejected(tmp_path):
    case = one_image_case(tmp_path)
    body = _plain_zip_bytes([("ok.png", image_bytes())])
    rewrite(case, lambda path: path.write_bytes(body + b"trailing"))
    assert_rejected_cleanly(case, "ZIP_END_INVALID|ZIP_LAYOUT_UNSUPPORTED")
    tricked = bytearray(body)
    struct.pack_into("<H", tricked, len(tricked) - 2, 22)
    tricked += b"PK\x05\x06" + b"\0" * 18
    rewrite(case, lambda path: path.write_bytes(bytes(tricked)))
    assert_rejected_cleanly(case, "ZIP_END_AMBIGUOUS|ZIP_LAYOUT_UNSUPPORTED")


def test_zip_strict_layout_still_accepts_a_normal_archive(tmp_path):
    case = one_image_case(tmp_path)
    for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        zip_with(case, [("notes.txt", b"synthetic only")], compression)
        path, checksum = refresh(case)
        report = data.prepare(
            case["root"], path.relative_to(case["root"]).as_posix(), checksum, OUTPUT
        )
        assert report["receipt"] == OUTPUT + "/report.json"
        assert any(row["member"] == "notes.txt" for row in report["inventory"])
        shutil.rmtree(case["root"] / OUTPUT)
