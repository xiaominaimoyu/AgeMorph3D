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
