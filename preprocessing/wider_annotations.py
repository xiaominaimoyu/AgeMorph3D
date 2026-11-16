"""WIDER FACE bbx_gt.txt parsing and YOLO label export with a full K5 ledger.

Run from the project root: python -m preprocessing.wider_annotations --help
Own parser per dataset plan v3 §5 item 3 ("§5.3"; no Bingsu or other third-party YOLO
conversion). Boxes reuse the P02 pixel-edge contract; images are only header-read and
hashed, never decoded or assigned to a new split. No model inference, training or
download is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from PIL import Image

from . import annotation_transform as transform
from . import archive_preparation as preparation
from . import dataset_manifest as metadata
from . import resource_acquisition as acquisition

SCHEMA = "agemorph3d-wider-annotations-v1"
MAX_GT_BYTES = 32 * 1024**2
MAX_IMAGES = metadata.MAX_RECORDS
MAX_FACES_PER_IMAGE = 4096
MAX_IMAGE_BYTES = transform.MAX_IMAGE_BYTES
MAX_REPORT_BYTES = 512 * 1024**2
MAX_ROUNDTRIP_PX = 0.5
YOLO_DECIMALS = 6
FACE_CLASS = 0
SPLITS = ("train", "val")
# Official readme value ranges, in column order after x1 y1 w h.
ATTRIBUTES = {
    "blur": (0, 2),
    "expression": (0, 1),
    "illumination": (0, 1),
    "invalid": (0, 1),
    "occlusion": (0, 2),
    "pose": (0, 1),
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FLAGS = {
    **acquisition.FLAGS,
    "split_assignment_performed": False,
    "annotation_quality_assessed": False,
    "human_review_completed": False,
    "box_convention_verified_on_real_data": False,
    "model_inference_run": False,
}
Error, require, safe = preparation.Error, preparation.require, preparation.safe
_INT = re.compile(r"[+-]?\d{1,9}")


def _fail(code, line):
    raise Error(f"{code}:line={line}")


def _ints(text, count, code, line):
    tokens = text.split()
    if len(tokens) != count or not all(_INT.fullmatch(t) for t in tokens):
        _fail(code, line)
    return [int(t) for t in tokens]


def _image_path(text, line):
    try:
        path = acquisition._relative(text)
    except Error:
        _fail("GT_IMAGE_PATH_INVALID", line)
    if path.suffix.lower() not in IMAGE_SUFFIXES or len(path.parts) > 4:
        _fail("GT_IMAGE_PATH_INVALID", line)
    return path.as_posix()


def parse_bbx_gt(text):
    """Parse the official block layout strictly; any malformed block rejects the file.

    Each block: image path, face count, then max(count, 1) rows of ten integers.
    A zero-face image keeps exactly one all-zero placeholder row, which is not a face.
    """
    require(type(text) is str, "GT_NOT_TEXT")
    lines = [line.strip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    require(bool(lines), "GT_EMPTY")
    entries, seen, stems, n = [], set(), set(), 0
    while n < len(lines):
        path = _image_path(lines[n], n + 1)
        if path in seen:
            _fail("GT_DUPLICATE_IMAGE_PATH", n + 1)
        stem = PurePosixPath(path).with_suffix("").as_posix().lower()
        if stem in stems:  # a.jpg and a.png would share one label file and sample ID
            _fail("GT_DUPLICATE_IMAGE_STEM", n + 1)
        seen.add(path)
        stems.add(stem)
        if n + 1 >= len(lines):
            _fail("GT_TRUNCATED_BLOCK", n + 2)
        (count,) = _ints(lines[n + 1], 1, "GT_FACE_COUNT_INVALID", n + 2)
        if not 0 <= count <= MAX_FACES_PER_IMAGE:
            _fail("GT_FACE_COUNT_INVALID", n + 2)
        rows = max(count, 1)
        if n + 2 + rows > len(lines):
            _fail("GT_TRUNCATED_BLOCK", len(lines) + 1)
        faces = []
        for k in range(rows):
            number = n + 3 + k
            values = _ints(lines[n + 2 + k], 10, "GT_FACE_ROW_INVALID", number)
            if count == 0:
                if any(values):
                    _fail("GT_ZERO_FACE_PLACEHOLDER_INVALID", number)
                continue
            attributes = dict(zip(ATTRIBUTES, values[4:], strict=True))
            if not all(lo <= attributes[k] <= hi for k, (lo, hi) in ATTRIBUTES.items()):
                _fail("GT_ATTRIBUTE_OUT_OF_RANGE", number)
            faces.append({"index": k, "line": number, "xywh": values[:4], **attributes})
        entries.append({"image": path, "line": n + 1, "declared_faces": count, "faces": faces})
        require(len(entries) <= MAX_IMAGES, "GT_TOO_MANY_IMAGES")
        n += 2 + rows
    return entries


def to_yolo(edges, size):
    """Pixel-edge xyxy -> normalized (cx, cy, w, h)."""
    left, top, right, bottom = edges
    width, height = size
    return [
        (left + right) / 2 / width,
        (top + bottom) / 2 / height,
        (right - left) / width,
        (bottom - top) / height,
    ]


def from_yolo(values, size):
    """Normalized (cx, cy, w, h) -> pixel-edge xyxy."""
    cx, cy, w, h = values
    width, height = size
    return [
        (cx - w / 2) * width,
        (cy - h / 2) * height,
        (cx + w / 2) * width,
        (cy + h / 2) * height,
    ]


def yolo_line(values):
    return " ".join([str(FACE_CLASS), *(f"{v:.{YOLO_DECIMALS}f}" for v in values)])


def parse_yolo_line(line):
    tokens = line.split()
    require(len(tokens) == 5 and tokens[0] == str(FACE_CLASS), "YOLO_LINE_INVALID")
    try:
        values = [float(t) for t in tokens[1:]]
    except ValueError as error:
        raise Error("YOLO_LINE_INVALID") from error
    require(
        all(0 <= v <= 1 for v in values) and values[2] > 0 and values[3] > 0,
        "YOLO_RANGE",
    )
    return values


def convert_faces(faces, size, *, max_blur=2):
    """Apply the export policy; every declared face is kept in the ledger with a decision.

    Policy: invalid=1 is dropped; blur above ``max_blur`` is dropped (default keeps all);
    zero/negative size is dropped; boxes are clipped to the frame via the P02 edge
    contract and dropped when nothing remains inside.
    """
    require(type(max_blur) is int and 0 <= max_blur <= 2, "INVALID_BLUR_POLICY")
    transform._size(list(size))
    ledger, lines, errors = [], [], []
    for face in faces:
        row = {
            **face,
            "decision": "dropped",
            "reason": None,
            "clipped": False,
            "yolo": None,
        }
        ledger.append(row)
        if face["invalid"] == 1:
            row["reason"] = "INVALID_FLAG"
            continue
        if face["blur"] > max_blur:
            row["reason"] = "BLUR_ABOVE_POLICY"
            continue
        try:
            box = transform.box(
                transform.IDENTITY,
                {"format": "xywh_edges", "values": face["xywh"]},
                list(size),
            )
        except Error as error:
            row["reason"] = str(error)
            continue
        if box["clipped_xyxy_edges"] is None:
            row["reason"] = "OUT_OF_FRAME"
            continue
        edges = box["clipped_xyxy_edges"]
        line = yolo_line(to_yolo(edges, size))
        written = parse_yolo_line(line)
        back = from_yolo(written, size)
        again = to_yolo(back, size)
        error = max(
            *(abs(a - b) for a, b in zip(back, edges, strict=True)),
            *(abs(a - b) * s for a, b, s in zip(again, written, (*size, *size), strict=True)),
        )
        require(error <= MAX_ROUNDTRIP_PX, "ROUNDTRIP_ERROR_EXCEEDED")
        errors.append(error)
        row.update(
            decision="kept",
            clipped=not box["fully_inside"],
            clipped_xyxy_edges=edges,
            yolo=written,
            roundtrip_abs_error_px=error,
        )
        lines.append(line)
    return {
        "ledger": ledger,
        "lines": lines,
        "roundtrip_max_abs_error_px": max(errors, default=None),
    }


def _image_info(path):
    count, digest = acquisition._hash_file(path, MAX_IMAGE_BYTES)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        # Header only; pixels are not decoded. Other formats are never probed.
        with Image.open(path, formats=["JPEG", "PNG"]) as image:
            fmt, size = image.format, [*image.size]
            orientation = image.getexif().get(0x0112)
    return {"bytes": count, "sha256": digest.hexdigest()}, fmt, size, orientation


def _sample_id(split, image):
    stem = PurePosixPath(image).with_suffix("").as_posix().replace("/", ":")
    value = f"wider-{split}:{stem}"
    if metadata._identifier(value):
        return value
    return f"wider-{split}:sha256-{hashlib.sha256(image.encode()).hexdigest()[:40]}"


def _record(split, sample_id, file, failure):
    return {
        "sample_id": sample_id,
        "dataset_id": f"wider-face-{split}",
        "file": file,
        "subject_id": None,
        "linked_subject_id": None,
        "parent_id": None,
        "kind": "original",
        "use": "unassigned",
        "age": metadata.age_label("unknown"),
        "age_source": "unknown",
        "exposure": {
            "preprocessing": "yes",
            "model_selection": "unknown",
            "result_inspection": "unknown",
        },
        "processing": {
            "status": "failed" if failure else "not_checked",
            "reason": "wider_conversion:" + failure if failure else None,
        },
    }


def _write(root, name, body):
    path = safe(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(body)


def convert(root, gt_name, gt_sha256, images_dir, split, output, *, max_blur=2):
    root = Path(root).absolute()
    require(
        root.is_dir() and root == root.resolve() and acquisition._sha(gt_sha256),
        "INVALID_ROOT_OR_GT_PIN",
    )
    require(type(split) is str and split in SPLITS, "INVALID_SPLIT")
    require(type(max_blur) is int and 0 <= max_blur <= 2, "INVALID_BLUR_POLICY")
    acquisition._relative(images_dir)
    gt_path = safe(root, gt_name)
    body = acquisition._read(gt_path, MAX_GT_BYTES)
    require(hashlib.sha256(body).hexdigest() == gt_sha256, "GT_SHA256_MISMATCH")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError as error:
        raise Error("GT_NOT_UTF8") from error
    entries = parse_bbx_gt(text)
    sample_ids = [_sample_id(split, entry["image"]) for entry in entries]
    require(len(set(sample_ids)) == len(sample_ids), "SAMPLE_ID_COLLISION")
    target = safe(root, output)
    require(
        output.startswith("output/research/") and not target.exists(),
        "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY",
    )
    created = target
    while not created.parent.exists():
        created = created.parent
    target.mkdir(parents=True, exist_ok=False)
    try:
        return _run(
            root,
            gt_name,
            gt_sha256,
            gt_path,
            body,
            images_dir,
            split,
            output,
            entries,
            sample_ids,
            max_blur,
        )
    except BaseException:
        # A rejection leaves nothing behind: remove only what this run created.
        shutil.rmtree(target, ignore_errors=True)
        path = target.parent
        while path != created.parent and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            path = path.parent
        raise


def _run(
    root,
    gt_name,
    gt_sha256,
    gt_path,
    body,
    images_dir,
    split,
    output,
    entries,
    sample_ids,
    max_blur,
):
    """Convert after the output directory exists; any raise is cleaned up by convert()."""
    rows, records = [], []
    for entry, sample_id in zip(entries, sample_ids, strict=True):
        image_name = images_dir + "/" + entry["image"]
        row = {
            "sample_id": sample_id,
            "image": image_name,
            "gt_line": entry["line"],
            "declared_faces": entry["declared_faces"],
            "status": "failed",
            "error_code": None,
            "file": None,
            "image_size": None,
            "exif_orientation": None,
            "label": None,
            "faces": [{**f, "decision": "not_processed"} for f in entry["faces"]],
            "kept_faces": 0,
            "roundtrip_max_abs_error_px": None,
        }
        rows.append(row)
        try:
            path = safe(root, image_name)
            require(path.is_file(), "IMAGE_MISSING")
            file, fmt, size, orientation = _image_info(path)
            row.update(file={"path": image_name, **file}, image_size=size)
            row["exif_orientation"] = orientation
            require(fmt in {"JPEG", "PNG"}, "IMAGE_FORMAT_UNSUPPORTED")
            # Annotations are in stored-pixel order; rotated EXIF would silently mismatch.
            require(orientation in (None, 1), "EXIF_ORIENTATION_NOT_IDENTITY")
            result = convert_faces(entry["faces"], size, max_blur=max_blur)
            label = (
                output + "/labels/" + PurePosixPath(entry["image"]).with_suffix(".txt").as_posix()
            )
            payload = "".join(line + "\n" for line in result["lines"]).encode()
            _write(root, label, payload)
            row.update(
                status="converted",
                faces=result["ledger"],
                kept_faces=len(result["lines"]),
                roundtrip_max_abs_error_px=result["roundtrip_max_abs_error_px"],
                label=preparation._file_pin(root, safe(root, label)),
            )
        except (
            Error,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as error:
            row["error_code"] = str(error) if isinstance(error, Error) else "IMAGE_UNREADABLE"
        if row["file"] is not None:
            records.append(_record(split, sample_id, row["file"], row["error_code"]))
    manifest = audit = manifest_body = None
    if records:
        manifest = metadata.validate_manifest(
            {
                "schema_id": metadata.SCHEMA,
                "schema_version": 1,
                "task": metadata.TASK,
                "manifest_id": f"wider-face-{split}-annotations-v1",
                "origin": {"path": gt_name, "bytes": len(body), "sha256": gt_sha256},
                "datasets": [
                    {
                        "dataset_id": f"wider-face-{split}",
                        "version": f"WIDER_FACE:official_{split}:bbx_gt_sha256={gt_sha256}",
                        "purpose_registration": {
                            "status": "unresolved",
                            "evidence": None,
                        },
                        "identity_review": {"status": "pending", "evidence": None},
                        "training_overlap": {"status": "unknown", "evidence": None},
                        "near_duplicate_review": {
                            "status": "pending",
                            "evidence": None,
                        },
                    }
                ],
                "records": records,
            }
        )
        audit = metadata.audit_manifest(manifest)
        manifest_body = metadata._encode(manifest)
        # Keep the K5 packet loadable by the dataset_manifest CLI budget.
        require(len(manifest_body) <= metadata.MAX_JSON_BYTES, "K5_MANIFEST_TOO_LARGE")
        _write(root, output + "/manifest.json", manifest_body)
        _write(root, output + "/audit.json", metadata._encode(audit))
    stable = True
    try:
        require(
            hashlib.sha256(acquisition._read(gt_path, MAX_GT_BYTES)).hexdigest() == gt_sha256,
            "INPUT_CHANGED",
        )
        for record in records:
            count, digest = acquisition._hash_file(
                safe(root, record["file"]["path"]), MAX_IMAGE_BYTES
            )
            require(
                count == record["file"]["bytes"] and digest.hexdigest() == record["file"]["sha256"],
                "INPUT_CHANGED",
            )
    except (Error, OSError):
        stable = False
    faces = [f for r in rows for f in r["faces"]]
    reasons = {}
    for face in faces:
        if face["decision"] == "dropped":
            reasons[face["reason"]] = reasons.get(face["reason"], 0) + 1
    errors = [
        r["roundtrip_max_abs_error_px"] for r in rows if r["roundtrip_max_abs_error_px"] is not None
    ]
    failures = {}
    for row in rows:
        if row["status"] == "failed":
            failures[row["error_code"]] = failures.get(row["error_code"], 0) + 1
    report = {
        "schema_id": SCHEMA,
        "split": split,
        "gt": {"path": gt_name, "bytes": len(body), "sha256": gt_sha256},
        "images_dir": images_dir,
        "producer_sha256": PRODUCER_SHA256,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "inputs_stable": stable,
        "policy": {
            "box_convention": "x1,y1,w,h as pixel edges [x1, x1+w) per P02 xywh_edges",
            "invalid": "drop",
            "max_blur_kept": max_blur,
            "out_of_frame": "clip_to_frame_then_drop_if_empty",
            "degenerate": "drop",
            "zero_face_image": "empty_label_file",
            "exif_orientation": "fail_unless_identity",
            "yolo_class": {str(FACE_CLASS): "face"},
            "yolo_decimals": YOLO_DECIMALS,
            "k5_use": "unassigned",
        },
        "summary": {
            "images": len(rows),
            "converted": sum(r["status"] == "converted" for r in rows),
            "failed": sum(r["status"] == "failed" for r in rows),
            "failed_by_code": dict(sorted(failures.items())),
            "zero_face_images": sum(r["declared_faces"] == 0 for r in rows),
            "faces_declared": len(faces),
            "faces_kept": sum(f["decision"] == "kept" for f in faces),
            "faces_clipped": sum(f.get("clipped") is True for f in faces),
            "faces_dropped_by_reason": dict(sorted(reasons.items())),
            "faces_not_processed": sum(f["decision"] == "not_processed" for f in faces),
            "k5_records": len(records),
            "roundtrip_max_abs_error_px": max(errors, default=None),
        },
        "k5_manifest": output + "/manifest.json" if manifest else None,
        "k5_audit_status": audit["status"] if audit else None,
        "records": rows,
        **FLAGS,
    }
    report["status"] = "passed" if stable and report["summary"]["failed"] == 0 else "failed"
    encoded = acquisition._encoded(report)
    require(len(encoded) <= MAX_REPORT_BYTES, "REPORT_TOO_LARGE")
    _write(root, output + "/report.json", encoded)
    return {**report, "receipt": output + "/report.json"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--gt", required=True, help="wider_face_<split>_bbx_gt.txt, relative")
    parser.add_argument("--gt-sha256", required=True)
    parser.add_argument("--images-dir", required=True, help="e.g. data/WIDER_train/images")
    parser.add_argument("--split", required=True, choices=SPLITS)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-blur", type=int, default=2, choices=(0, 1, 2))
    args = parser.parse_args(argv)
    try:
        report = convert(
            args.root,
            args.gt,
            args.gt_sha256,
            args.images_dir,
            args.split,
            args.output_dir,
            max_blur=args.max_blur,
        )
    except (ValueError, OSError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **FLAGS}))
        return 2
    print(json.dumps({"status": report["status"], "summary": report["summary"], **FLAGS}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
