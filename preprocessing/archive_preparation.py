"""Bounded archive inventory and image/EXIF checks, retaining K5 purposes/failures.

python -m preprocessing.archive_preparation --help
This tool does not grant permission, choose dataset splits, run models or train.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import shutil
import stat
import struct
import sys
import tarfile
import warnings
import zipfile
import zlib
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL import __version__ as PILLOW_VERSION

from . import dataset_manifest as metadata
from . import resource_acquisition as acquisition

SCHEMA = "agemorph3d-archive-preparation-v1"
MAX_ARCHIVE_BYTES = 256 * 1024**2
MAX_JSON_BYTES = 512 * 1024
MAX_REPORT_BYTES = 4 * 1024**2
MAX_IMAGES = 32
CHUNK = 64 * 1024
LIMITS = {
    "members": 1024,
    "member_bytes": 32 * 1024**2,
    "total_bytes": 256 * 1024**2,
    "image_bytes": 16 * 1024**2,
    "image_pixels": 16 * 1024**2,
    "normalized_bytes": 64 * 1024**2,
    "reserve_bytes": 64 * 1024**3,
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
Error = acquisition.AcquisitionError
require = acquisition._require
safe = acquisition._safe
relative = acquisition._relative
PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _pin(value, maximum):
    acquisition._keys(value, ("path", "bytes", "sha256"))
    relative(value["path"])
    require(
        acquisition._integer(value["bytes"], 1, maximum) and acquisition._sha(value["sha256"]),
        "INVALID_PIN",
    )


def _verify(root, pin, maximum):
    path = safe(root, pin["path"])
    count, digest = acquisition._hash_file(path, maximum)
    require(count == pin["bytes"] and digest.hexdigest() == pin["sha256"], "INPUT_PIN_MISMATCH")
    return path


def _load(root, pin):
    path = _verify(root, pin, MAX_JSON_BYTES)
    return acquisition._json(acquisition._read(path, MAX_JSON_BYTES))


def _file_pin(root, path):
    count, digest = acquisition._hash_file(path, MAX_ARCHIVE_BYTES)
    return {"path": path.relative_to(root).as_posix(), "bytes": count, "sha256": digest.hexdigest()}


def _write_json(root, name, value):
    body = acquisition._encoded(value)
    require(len(body) <= MAX_REPORT_BYTES, "REPORT_TOO_LARGE")
    with safe(root, name).open("xb") as stream:
        stream.write(body)


def _zip_guard(path, limits):
    # Bound central-directory allocation before ZipFile constructs its entry objects.
    with path.open("rb") as stream:
        require(stream.read(4) in {b"PK\x03\x04", b"PK\x05\x06"}, "ZIP_PREFIX_UNSUPPORTED")
        size = path.stat().st_size
        stream.seek(max(0, size - 65557))
        tail = stream.read(65557)
    position = tail.rfind(b"PK\x05\x06")
    require(position >= 0 and position + 22 <= len(tail), "ZIP_END_INVALID")
    _, disk, directory_disk, disk_count, count, directory_bytes, offset, comment = struct.unpack(
        "<4s4H2LH", tail[position : position + 22]
    )
    require(
        position + 22 + comment == len(tail)
        and disk == directory_disk == 0
        and disk_count == count
        and count != 65535
        and offset != 0xFFFFFFFF,
        "ZIP_LAYOUT_UNSUPPORTED",
    )
    require(count <= limits["members"] and directory_bytes <= 1024**2, "ZIP_DIRECTORY_LIMIT")
    require(offset + directory_bytes <= size - len(tail) + position, "ZIP_DIRECTORY_INVALID")


class _BoundedReader:
    def __init__(self, stream, maximum):
        self.stream, self.maximum, self.count = stream, maximum, 0

    def read(self, size):
        require(type(size) is int and size >= 0, "UNBOUNDED_TAR_READ")
        body = self.stream.read(min(size, self.maximum - self.count + 1))
        self.count += len(body)
        require(self.count <= self.maximum, "TAR_STREAM_LIMIT")
        return body


@contextmanager
def _container(path, kind, limits):
    if kind == "zip":
        _zip_guard(path, limits)
        with zipfile.ZipFile(path) as container:
            yield container
    else:
        maximum = limits["total_bytes"] + limits["members"] * 1024 + 10240
        with path.open("rb") as original:
            with gzip.GzipFile(fileobj=original) if kind == "tar_gz" else original as stream:
                with tarfile.open(fileobj=_BoundedReader(stream, maximum), mode="r|") as container:
                    yield container


def _member(info, kind):
    if kind == "zip":
        mode = info.external_attr >> 16
        require(
            info.orig_filename == info.filename and not info.flag_bits & 1,
            "ZIP_NAME_OR_ENCRYPTION_UNSUPPORTED",
        )
        require(
            info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            and info.extract_version <= 20,
            "ZIP_METHOD_UNSUPPORTED",
        )
        require(stat.S_IFMT(mode) in {0, stat.S_IFREG, stat.S_IFDIR}, "SPECIAL_MEMBER")
        name, size, directory = info.filename, info.file_size, info.is_dir()
        require(stat.S_IFMT(mode) != stat.S_IFDIR or directory, "DIRECTORY_TYPE_MISMATCH")
    else:
        require(
            info.type in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE}
            and not info.issparse()
            and not info.pax_headers
            and info.offset_data - info.offset == 512,
            "SPECIAL_OR_EXTENDED_TAR_MEMBER",
        )
        name, size, directory = info.name, info.size, info.isdir()
    if directory and name.endswith("/"):
        name = name[:-1]
    relative(name)
    require(type(size) is int and size >= 0 and (not directory or size == 0), "MEMBER_SIZE_INVALID")
    return {"member": name, "bytes": size, "kind": "directory" if directory else "file"}


def _members(container, kind):
    return container.infolist() if kind == "zip" else container


def _tar_tail(container):
    while chunk := container.fileobj.read(CHUNK):
        require(not chunk.strip(b"\0"), "TRAILING_TAR_DATA")


def _scan(path, kind, limits):
    inventory, names, total = [], {}, 0
    with _container(path, kind, limits) as container:
        for info in _members(container, kind):
            row = _member(info, kind)
            require(len(inventory) < limits["members"], "MEMBER_COUNT_LIMIT")
            require(row["bytes"] <= limits["member_bytes"], "MEMBER_SIZE_LIMIT")
            key = row["member"].casefold()
            require(key not in names, "DUPLICATE_MEMBER_PATH")
            for old, old_kind in names.items():
                require(
                    not (old_kind == "file" and key.startswith(old + "/"))
                    and not (row["kind"] == "file" and old.startswith(key + "/")),
                    "MEMBER_PATH_CONFLICT",
                )
            names[key] = row["kind"]
            total += row["bytes"]
            require(total <= limits["total_bytes"], "TOTAL_UNPACKED_LIMIT")
            inventory.append(row)
        if kind != "zip":
            _tar_tail(container)
    return inventory


def _extract(root, archive, kind, limits, output, inventory):
    results = []
    try:
        with _container(archive, kind, limits) as container:
            for index, info in enumerate(_members(container, kind)):
                row = _member(info, kind)
                require(
                    index < len(inventory) and row == inventory[index], "ARCHIVE_MEMBERS_CHANGED"
                )
                row = {**row, "status": "failed", "error_code": None, "file": None}
                name = output + "/files/" + row["member"]
                if row["kind"] == "directory":
                    safe(root, name).mkdir(parents=True, exist_ok=True)
                    row["status"] = "directory"
                else:
                    target = safe(root, name)
                    part = safe(
                        root,
                        output
                        + "/stage/"
                        + hashlib.sha256(row["member"].encode()).hexdigest()
                        + ".part",
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    part.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        source = (
                            container.open(info) if kind == "zip" else container.extractfile(info)
                        )
                        require(source is not None, "MISSING_MEMBER_STREAM")
                        count, hashed = 0, hashlib.sha256()
                        with source, part.open("xb") as stream:
                            while chunk := source.read(min(CHUNK, row["bytes"] - count + 1)):
                                require(count + len(chunk) <= row["bytes"], "MEMBER_BODY_LIMIT")
                                stream.write(chunk)
                                hashed.update(chunk)
                                count += len(chunk)
                        require(count == row["bytes"], "INCOMPLETE_MEMBER")
                        os.link(part, target)
                        part.unlink()
                        target.chmod(target.stat().st_mode & ~0o222)
                        row.update(
                            status="extracted",
                            file={"path": name, "bytes": count, "sha256": hashed.hexdigest()},
                        )
                    except (
                        Error,
                        OSError,
                        zipfile.BadZipFile,
                        tarfile.TarError,
                        EOFError,
                        zlib.error,
                        struct.error,
                    ) as error:
                        row["error_code"] = (
                            str(error) if isinstance(error, Error) else "MEMBER_READ_FAILED"
                        )
                results.append(row)
            require(len(results) == len(inventory), "ARCHIVE_MEMBERS_CHANGED")
            if kind != "zip":
                _tar_tail(container)
    except (
        Error,
        OSError,
        zipfile.BadZipFile,
        tarfile.TarError,
        EOFError,
        zlib.error,
        struct.error,
    ):
        for row in inventory[len(results) :]:
            results.append(
                {**row, "status": "failed", "error_code": "ARCHIVE_READ_FAILED", "file": None}
            )
        if results and all(r["status"] != "failed" for r in results):
            results[-1].update(status="failed", error_code="ARCHIVE_READ_FAILED")
    return results


def orientation_matrix(orientation, width, height):
    """Map integer pixel centers from original raster to the oriented raster."""
    matrices = {
        1: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        2: [[-1, 0, width - 1], [0, 1, 0], [0, 0, 1]],
        3: [[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]],
        4: [[1, 0, 0], [0, -1, height - 1], [0, 0, 1]],
        5: [[0, 1, 0], [1, 0, 0], [0, 0, 1]],
        6: [[0, -1, height - 1], [1, 0, 0], [0, 0, 1]],
        7: [[0, -1, height - 1], [-1, 0, width - 1], [0, 0, 1]],
        8: [[0, 1, 0], [-1, 0, width - 1], [0, 0, 1]],
    }
    require(type(orientation) is int and orientation in matrices, "INVALID_EXIF_ORIENTATION")
    return matrices[orientation]


class _LimitedWriter:
    def __init__(self, stream, maximum):
        self.stream, self.maximum, self.count = stream, maximum, 0

    def write(self, body):
        require(self.count + len(body) <= self.maximum, "NORMALIZED_SIZE_LIMIT")
        written = self.stream.write(body)
        self.count += written
        return written

    def flush(self):
        self.stream.flush()


def _image(root, record, extracted, limits, output):
    row = {
        "sample_id": record["sample_id"],
        "member": extracted["member"],
        "status": "failed",
        "error_code": None,
        "binary_pin_verified": False,
        "normalized": None,
        "preprocessing_observed": extracted["status"] in {"extracted", "failed"},
    }
    try:
        require(extracted["status"] == "extracted", "SOURCE_NOT_EXTRACTED")
        require(extracted["file"] == record["file"], "IMAGE_PIN_MISMATCH")
        source = safe(root, record["file"]["path"])
        require(source.stat().st_size <= limits["image_bytes"], "IMAGE_BYTE_LIMIT")
        row["binary_pin_verified"] = True
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as image:
                require(image.format in {"JPEG", "PNG"}, "IMAGE_FORMAT_UNSUPPORTED")
                width, height = image.size
                require(0 < width * height <= limits["image_pixels"], "IMAGE_PIXEL_LIMIT")
                require(getattr(image, "n_frames", 1) == 1, "ANIMATED_IMAGE_UNSUPPORTED")
                image.verify()
            with Image.open(source) as image:
                image.load()
                orientation = image.getexif().get(274)
                matrix = orientation_matrix(
                    orientation if orientation is not None else 1, width, height
                )
                with ImageOps.exif_transpose(image) as oriented:
                    require(
                        oriented.mode in {"1", "L", "LA", "P", "RGB", "RGBA", "CMYK"},
                        "IMAGE_MODE_UNSUPPORTED",
                    )
                    mode = (
                        "RGBA"
                        if "A" in oriented.getbands() or "transparency" in oriented.info
                        else "RGB"
                    )
                    with (
                        oriented.convert(mode) as converted,
                        Image.new(mode, oriented.size) as clean,
                    ):
                        clean.paste(
                            converted
                        )  # Fresh image: no EXIF, ICC or text metadata propagated.
                        name = (
                            output
                            + "/normalized/"
                            + hashlib.sha256(record["sample_id"].encode()).hexdigest()
                            + ".png"
                        )
                        target, part = safe(root, name), safe(root, name + ".part")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with part.open("xb") as stream:
                            clean.save(
                                _LimitedWriter(stream, limits["normalized_bytes"]), format="PNG"
                            )
                        require(
                            _file_pin(root, source) == record["file"],
                            "SOURCE_CHANGED_DURING_DECODE",
                        )
                        os.link(part, target)
                        part.unlink()
                        target.chmod(target.stat().st_mode & ~0o222)
                        row.update(
                            status="decoded",
                            normalized=_file_pin(root, target),
                            source_size=[width, height],
                            normalized_size=list(clean.size),
                            source_orientation=orientation,
                            original_to_normalized=matrix,
                            normalized_mode=mode,
                            source_format=image.format,
                        )
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        row["error_code"] = "IMAGE_PIXEL_LIMIT"
    except (Error, OSError, ValueError, SyntaxError, UnidentifiedImageError, struct.error) as error:
        row["error_code"] = str(error) if isinstance(error, Error) else "IMAGE_DECODE_FAILED"
    return row


def prepare(root, plan_name, plan_sha256, output):
    """Prepare a new quarantined directory; K5 claims and old failure reasons persist."""
    root = Path(root).absolute()
    require(root.is_dir() and root == root.resolve(), "INVALID_ROOT")
    require(acquisition._sha(plan_sha256), "INVALID_PLAN_SHA256")
    body = acquisition._read(safe(root, plan_name), MAX_JSON_BYTES)
    require(hashlib.sha256(body).hexdigest() == plan_sha256, "PLAN_SHA256_MISMATCH")
    plan = acquisition._json(body)
    acquisition._keys(
        plan,
        ("schema_id", "plan_id", "archive", "acquisition_receipt", "metadata_manifest", "limits"),
    )
    require(
        plan["schema_id"] == SCHEMA and acquisition._identifier(plan["plan_id"]), "INVALID_PLAN"
    )
    acquisition._keys(plan["archive"], ("path", "bytes", "sha256", "format"))
    archive_pin = {k: plan["archive"][k] for k in ("path", "bytes", "sha256")}
    _pin(archive_pin, MAX_ARCHIVE_BYTES)
    require(
        archive_pin["path"].startswith(("data/datasets/", "output/research/")),
        "ARCHIVE_OUTSIDE_IGNORED_ROOT",
    )
    kind = plan["archive"]["format"]
    require(type(kind) is str and kind in {"zip", "tar", "tar_gz"}, "ARCHIVE_FORMAT_UNSUPPORTED")
    for key in ("acquisition_receipt", "metadata_manifest"):
        _pin(plan[key], MAX_JSON_BYTES)
    limits = plan["limits"]
    acquisition._keys(limits, LIMITS)
    require(
        all(
            acquisition._integer(limits[k], 0 if k == "reserve_bytes" else 1, v)
            for k, v in LIMITS.items()
        ),
        "INVALID_LIMITS",
    )
    archive = _verify(root, archive_pin, MAX_ARCHIVE_BYTES)
    require(not archive.stat().st_mode & 0o222, "ARCHIVE_NOT_READ_ONLY")
    receipt = _load(root, plan["acquisition_receipt"])
    require(
        type(receipt) is dict
        and receipt.get("schema_id") == acquisition.SCHEMA
        and receipt.get("status") == "passed"
        and type(receipt.get("records")) is list,
        "ACQUISITION_RECEIPT_INVALID",
    )
    matches = [
        r for r in receipt["records"] if type(r) is dict and r.get("path") == archive_pin["path"]
    ]
    require(
        len(matches) == 1
        and type(matches[0].get("status")) is str
        and matches[0]["status"] in {"downloaded", "reused"}
        and matches[0].get("expected_bytes") == archive_pin["bytes"]
        and matches[0].get("expected_sha256") == archive_pin["sha256"]
        and matches[0].get("integrity_verified") is True
        and matches[0].get("published_read_only") is True,
        "ARCHIVE_RECEIPT_PIN_MISMATCH",
    )
    manifest = metadata.validate_manifest(_load(root, plan["metadata_manifest"]))
    require(len(manifest["records"]) <= MAX_IMAGES, "IMAGE_COUNT_LIMIT")
    destination = safe(root, output)
    require(
        output.startswith("output/research/") and not destination.exists(),
        "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY",
    )
    inventory = _scan(archive, kind, limits)
    for member in inventory:
        safe(root, output + "/files/" + member["member"])
    by_member = {r["member"]: r for r in inventory if r["kind"] == "file"}
    bindings = []
    for record in manifest["records"]:
        name = record["file"]["path"]
        prefix = output + "/files/"
        require(name.startswith(prefix), "K5_PATH_OUTSIDE_OUTPUT")
        member = name[len(prefix) :]
        require(member in by_member and member not in bindings, "K5_MEMBER_MISSING_OR_DUPLICATE")
        bindings.append(member)
        safe(root, name)
        safe(
            root,
            output
            + "/normalized/"
            + hashlib.sha256(record["sample_id"].encode()).hexdigest()
            + ".png.part",
        )
    require(
        all(
            Path(name).suffix.lower() not in IMAGE_SUFFIXES or name in bindings
            for name in by_member
        ),
        "UNBOUND_IMAGE_MEMBER",
    )
    # Temporary, raw, normalized, and report overhead are budgeted conservatively.
    budget = (
        sum(r["bytes"] for r in inventory)
        + len(bindings) * limits["normalized_bytes"]
        + limits["reserve_bytes"]
        + MAX_REPORT_BYTES
    )
    require(shutil.disk_usage(root).free >= budget, "INSUFFICIENT_SPACE")
    destination.mkdir(parents=True, exist_ok=False)
    extracted = _extract(root, archive, kind, limits, output, inventory)
    extracted_by_name = {r["member"]: r for r in extracted}
    results = [
        _image(root, r, extracted_by_name[name], limits, output)
        for r, name in zip(manifest["records"], bindings, strict=True)
    ]
    prepared = copy.deepcopy(manifest)
    prepared["manifest_id"] = manifest["manifest_id"][:80] + ".prepared-" + plan_sha256[:12]
    for record, result in zip(prepared["records"], results, strict=True):
        if result["preprocessing_observed"]:
            record["exposure"]["preprocessing"] = "yes"
    metadata.validate_manifest(prepared)
    _write_json(root, output + "/prepared-manifest.json", prepared)
    _write_json(root, output + "/metadata-audit.json", metadata.audit_manifest(prepared))
    stable = True
    try:
        require(
            hashlib.sha256(acquisition._read(safe(root, plan_name), MAX_JSON_BYTES)).hexdigest()
            == plan_sha256,
            "INPUT_CHANGED",
        )
        _verify(root, archive_pin, MAX_ARCHIVE_BYTES)
        for key in ("acquisition_receipt", "metadata_manifest"):
            _verify(root, plan[key], MAX_JSON_BYTES)
    except (Error, OSError):
        stable = False
    report = {
        "schema_id": SCHEMA,
        "plan_path": plan_name,
        "archive_format": kind,
        "limits": limits,
        "python": sys.version.split()[0],
        "pillow": PILLOW_VERSION,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan_sha256,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "producer_sha256": PRODUCER_SHA256,
        "inputs": {
            "archive": archive_pin,
            "acquisition_receipt": plan["acquisition_receipt"],
            "metadata_manifest": plan["metadata_manifest"],
        },
        "inputs_stable": stable,
        "inventory": extracted,
        "records": results,
        "summary": {
            "archive_members": len(inventory),
            "regular_files": len(by_member),
            "requested_images": len(results),
            "decoded_images": sum(r["status"] == "decoded" for r in results),
            "failed_images": sum(r["status"] == "failed" for r in results),
            "historical_failed_records_retained": sum(
                r["processing"]["status"] == "failed" for r in prepared["records"]
            ),
        },
        "permission_assessment": "not_performed",
        "full_quality_assessment": "not_performed",
        "split_assignment_performed": False,
        "model_inference_run": False,
        **acquisition.FLAGS,
    }
    report["status"] = (
        "passed"
        if stable and all(r["status"] != "failed" for r in extracted + results)
        else "failed"
    )
    _write_json(root, output + "/report.json", report)
    return {**report, "receipt": output + "/report.json"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare(args.root, args.plan, args.plan_sha256, args.output_dir)
    except (
        Error,
        OSError,
        ValueError,
        tarfile.TarError,
        zipfile.BadZipFile,
        EOFError,
        zlib.error,
        struct.error,
    ) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_OR_ARCHIVE_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **acquisition.FLAGS}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
