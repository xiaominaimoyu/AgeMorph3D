"""AgeDB official filename parsing, local-folder statistics and a K5 metadata ledger.

Run from the project root: python -m preprocessing.agedb_filenames --help
The CLI refuses to run unless ``--local-only-ack`` is passed. On start it warns
that filename-containing outputs stay on the user's machine only.
Dataset plan v3 §4 item 4 ("§4.4"): recount the §2-A figures from the official
``<id>_<name>_<age>_<gender>.jpg`` names. Meant to run only on the user's own machine
over the locally extracted official folder. Images are header-read and hashed, never
decoded, uploaded or assigned to a split. No network, model inference or training.

Outputs (one new ``output/research/`` directory, written only after every check passed):
``stats.json`` aggregates only (no file names, person names or image IDs);
``rejected.json`` and ``audit.json`` contain file names, are marked ``local_only``
and stay local; ``manifest.json`` is the K5 ledger (also contains file names, stays
local) and keeps the unchanged K5 field set — no ``local_only`` key is added there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import statistics
import sys
import unicodedata
import warnings
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from PIL import Image

from . import annotation_transform as transform
from . import archive_preparation as preparation
from . import dataset_manifest as metadata
from . import resource_acquisition as acquisition

SCHEMA = "agemorph3d-agedb-filenames-v1"
STATS_SCHEMA = "agemorph3d-agedb-stats-v1"
DATASET_ID = "agedb-official"
MAX_FILES = metadata.MAX_RECORDS
MAX_DEPTH = 4
MAX_IMAGE_BYTES = transform.MAX_IMAGE_BYTES
MAX_OUTPUT_BYTES = 64 * 1024**2
MAX_NAME_CHARS = 200
MAX_ID_DIGITS = 9
AGE_MIN, AGE_MAX = 0, 120  # dataset_manifest.age_label accepts 0..120
AGE_LOW, AGE_HIGH = 20, 70  # task range (dataset_manifest.TASK)
SPAN_YEARS = 30
MIN_SHORT_SIDE = 128
GENDERS = {"m": "male", "f": "female"}  # official lowercase letters only
SHORT_SIDE_BINS = (64, 128, 256, 512, 1024)
PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FLAGS = {
    **acquisition.FLAGS,
    "split_assignment_performed": False,
    "model_inference_run": False,
    "verified_on_real_data": False,
    "identity_from_name_verified_on_real_data": False,
}
Error, require, safe = preparation.Error, preparation.require, preparation.safe


def _digits(text):
    return bool(text) and text.isascii() and text.isdigit()


def parse_filename(filename):
    """Parse one base name; return a dict or raise Error(<reason code>).

    The id is the first ``_`` token and age/gender are the last two, so the name is
    everything between them and may itself contain underscores (a trailing ``_<digits>``
    therefore stays part of the name). Identity is the NFC-normalized name, exactly as
    spelled (case-sensitive); the numeric id identifies the image, not the person.
    """
    require(type(filename) is str and filename, "FILENAME_PATTERN_MISMATCH")
    try:
        filename.encode("utf-8")
    except UnicodeError as error:
        raise Error("FILENAME_NOT_UTF8") from error
    path = PurePosixPath(filename)
    require(path.name == filename and path.suffix.lower() == ".jpg", "SUFFIX_NOT_JPG")
    tokens = filename[: -len(path.suffix)].split("_")
    require(len(tokens) >= 4, "FILENAME_PATTERN_MISMATCH")
    image_id, age, gender = tokens[0], tokens[-2], tokens[-1]
    name = "_".join(tokens[1:-2])
    require(
        _digits(image_id) and len(image_id) <= MAX_ID_DIGITS and str(int(image_id)) == image_id,
        "ID_INVALID",
    )
    require(
        bool(name.strip())
        and name == name.strip()
        and not name.startswith("_")
        and not name.endswith("_")
        and len(name) <= MAX_NAME_CHARS
        and all(unicodedata.category(c)[0] != "C" for c in name),
        "NAME_INVALID",
    )
    require(_digits(age) and len(age) <= 3, "AGE_NOT_INTEGER")
    require(str(int(age)) == age, "AGE_LEADING_ZERO")
    require(AGE_MIN <= int(age) <= AGE_MAX, "AGE_OUT_OF_RANGE")
    require(gender in GENDERS, "GENDER_INVALID")
    return {
        "image_id": int(image_id),
        "name": unicodedata.normalize("NFC", name),
        "age": int(age),
        "gender": gender,
    }


def subject_id(name):
    """Stable K5 identifier for a name. A pseudonym for ID syntax, not anonymization."""
    return "agedb-subject:" + hashlib.sha256(name.encode()).hexdigest()[:24]


def _display(name):
    return name.encode("utf-8", "backslashreplace").decode("utf-8")


def scan(root, images_dir):
    """List every entry below images_dir without following links; nothing is skipped."""
    base = safe(root, images_dir)
    require(base.is_dir(), "IMAGES_DIR_MISSING")
    files, rejected, stack = [], [], [(base, images_dir, 1)]
    while stack:
        folder, rel, depth = stack.pop()
        with os.scandir(folder) as entries:
            items = sorted(entries, key=lambda e: e.name)
        for entry in items:
            name = rel + "/" + entry.name
            require(len(files) + len(rejected) < MAX_FILES, "TOO_MANY_FILES")
            meta = entry.stat(follow_symlinks=False)
            reparse = getattr(meta, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            if stat.S_ISLNK(meta.st_mode) or reparse:
                rejected.append({"path": _display(name), "reason": "LINK_OR_REPARSE_PATH"})
            elif stat.S_ISDIR(meta.st_mode):
                if depth >= MAX_DEPTH:
                    rejected.append({"path": _display(name), "reason": "PATH_TOO_DEEP"})
                else:
                    stack.append((Path(entry.path), name, depth + 1))
            elif not stat.S_ISREG(meta.st_mode):
                rejected.append({"path": _display(name), "reason": "NOT_REGULAR_FILE"})
            else:
                files.append(name)
    return sorted(files), rejected


def _header(path):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        # Header only; pixels are not decoded. Non-JPEG content is never probed.
        with Image.open(path, formats=["JPEG"]) as image:
            size, orientation = [*image.size], image.getexif().get(0x0112)
    return size, orientation


def _short_side_stats(sides):
    if not sides:
        return {"count": 0, "min": None, "max": None, "median": None, "quantiles": None}
    ordered = sorted(sides)

    def nearest(q):  # nearest-rank quantile, always an observed value
        return ordered[max(0, -(-len(ordered) * q // 100) - 1)]

    edges = (0, *SHORT_SIDE_BINS)
    histogram = {
        f"{lo}-{hi - 1}": sum(lo <= s < hi for s in ordered)
        for lo, hi in zip(edges, (*SHORT_SIDE_BINS, None), strict=True)
        if hi is not None
    }
    histogram[f">={SHORT_SIDE_BINS[-1]}"] = sum(s >= SHORT_SIDE_BINS[-1] for s in ordered)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "median": statistics.median(ordered),
        "quantiles": {f"p{q}": nearest(q) for q in (5, 25, 50, 75, 95)},
        f"below_{MIN_SHORT_SIDE}": sum(s < MIN_SHORT_SIDE for s in ordered),
        "histogram": histogram,
    }


def _identity_stats(rows):
    ages = defaultdict(list)
    for row in rows:
        ages[row["name"]].append(row["age"])
    spans = [max(v) - min(v) for v in ages.values()]
    return {
        "images": len(rows),
        "identities": len(ages),
        f"identities_span_ge_{SPAN_YEARS}": sum(s >= SPAN_YEARS for s in spans),
        f"images_age_exact_{AGE_HIGH}": sum(r["age"] == AGE_HIGH for r in rows),
    }


def summarize(rows):
    """Aggregate counts over parsed rows ({name, age, gender, short_side|None}).

    Age/identity figures use every parsed filename; size figures use readable images.
    Span is max-min age per identity, computed once over all ages and once inside 20-70.
    """
    in_range = [r for r in rows if AGE_LOW <= r["age"] <= AGE_HIGH]
    sized = [r for r in rows if r["short_side"] is not None]
    large = [r for r in sized if r["short_side"] >= MIN_SHORT_SIDE]
    names = {r["name"] for r in rows}
    folded = Counter(n.casefold() for n in names)
    decades = Counter(f"{r['age'] // 10 * 10}-{r['age'] // 10 * 10 + 9}" for r in rows)
    all_ages = _identity_stats(rows)
    return {
        "images": len(rows),
        "identities": len(names),
        "identities_differing_only_by_case": sum(c for c in folded.values() if c > 1),
        "age_min": min((r["age"] for r in rows), default=None),
        "age_max": max((r["age"] for r in rows), default=None),
        "images_by_age_decade": dict(
            sorted(decades.items(), key=lambda i: int(i[0].split("-")[0]))
        ),
        "images_by_gender": {
            GENDERS[g]: sum(r["gender"] == g for r in rows) for g in sorted(GENDERS)
        },
        f"images_age_{AGE_LOW}_{AGE_HIGH}": len(in_range),
        f"images_age_exact_{AGE_HIGH}": all_ages[f"images_age_exact_{AGE_HIGH}"],
        f"identities_span_ge_{SPAN_YEARS}": all_ages[f"identities_span_ge_{SPAN_YEARS}"],
        f"identities_span_ge_{SPAN_YEARS}_within_{AGE_LOW}_{AGE_HIGH}": _identity_stats(in_range)[
            f"identities_span_ge_{SPAN_YEARS}"
        ],
        "short_side_px": _short_side_stats([r["short_side"] for r in sized]),
        "images_without_size": len(rows) - len(sized),
        "filter_short_ge_128_age_20_70": _identity_stats(
            [r for r in large if AGE_LOW <= r["age"] <= AGE_HIGH]
        ),
        "filter_short_ge_128": _identity_stats(large),
    }


def _record(sample_id, file, row, failure):
    return {
        "sample_id": sample_id,
        "dataset_id": DATASET_ID,
        "file": file,
        "subject_id": subject_id(row["name"]),
        "linked_subject_id": None,
        "parent_id": None,
        "kind": "original",
        "use": "unassigned",
        "age": metadata.age_label("exact", row["age"]),
        "age_source": "dataset_annotation",
        "exposure": {
            "preprocessing": "yes",
            "model_selection": "unknown",
            "result_inspection": "unknown",
        },
        "processing": {
            "status": "failed" if failure else "not_checked",
            "reason": "agedb_header:" + failure if failure else None,
        },
    }


def collect(root, images_dir):
    """Read-only pass: parse, hash and header-read every file; nothing is written."""
    files, rejected = scan(root, images_dir)
    parsed, by_id = [], defaultdict(list)
    for name in files:
        try:
            row = parse_filename(PurePosixPath(name).name)
            try:
                name.encode("utf-8")
            except UnicodeError as error:  # an undecodable parent folder name
                raise Error("PATH_NOT_UTF8") from error
        except Error as error:
            rejected.append({"path": _display(name), "reason": str(error)})
            continue
        parsed.append({"path": name, **row})
        by_id[row["image_id"]].append(name)
    rows = []
    for row in parsed:
        if len(by_id[row["image_id"]]) > 1:  # no copy is preferred over another
            rejected.append({"path": _display(row["path"]), "reason": "DUPLICATE_IMAGE_ID"})
            continue
        try:
            path = safe(root, row["path"])
        except Error:
            rejected.append({"path": _display(row["path"]), "reason": "PATH_INVALID"})
            continue
        try:
            count, digest = acquisition._hash_file(path, MAX_IMAGE_BYTES)
        except Error:
            rejected.append({"path": _display(row["path"]), "reason": "IMAGE_TOO_LARGE"})
            continue
        except OSError:
            rejected.append({"path": _display(row["path"]), "reason": "FILE_UNREADABLE"})
            continue
        if count == 0:  # a K5 file pin needs bytes > 0
            rejected.append({"path": _display(row["path"]), "reason": "FILE_EMPTY"})
            continue
        row.update(
            file={"path": row["path"], "bytes": count, "sha256": digest.hexdigest()},
            size=None,
            short_side=None,
            orientation=None,
            failure=None,
        )
        try:
            size, orientation = _header(path)
        except (
            OSError,  # includes PIL.UnidentifiedImageError
            ValueError,
            SyntaxError,
            EOFError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            row["failure"] = "IMAGE_UNREADABLE"
        else:
            row.update(size=size, short_side=min(size), orientation=orientation)
        rows.append(row)
    rejected.sort(key=lambda r: (r["path"], r["reason"]))
    return files, rows, rejected


def _stable(root, rows):
    try:
        for row in rows:
            count, digest = acquisition._hash_file(safe(root, row["path"]), MAX_IMAGE_BYTES)
            if count != row["file"]["bytes"] or digest.hexdigest() != row["file"]["sha256"]:
                return False
    except (Error, OSError):
        return False
    return True


def _inventory_sha256(rows, rejected):
    lines = [f"{r['file']['sha256']} {r['file']['bytes']} {r['path']}" for r in rows]
    lines += [f"REJECTED {r['reason']} {r['path']}" for r in rejected]
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


def _counts(values):
    return dict(sorted(Counter(values).items()))


def build(root, images_dir):
    """Collect and build every payload in memory; raises Error before any write."""
    files, rows, rejected = collect(root, images_dir)
    require(bool(rows), "NO_AGEDB_IMAGES")
    stable = _stable(root, rows)
    inventory = _inventory_sha256(rows, rejected)
    records = [
        _record(f"agedb:{r['image_id']}", r["file"], r, r["failure"])
        for r in sorted(rows, key=lambda r: r["image_id"])
    ]
    manifest = metadata.validate_manifest(
        {
            "schema_id": metadata.SCHEMA,
            "schema_version": 1,
            "task": metadata.TASK,
            "manifest_id": "agedb-official-filenames-v1",
            "origin": None,
            "datasets": [
                {
                    "dataset_id": DATASET_ID,
                    "version": f"AgeDB:official_filenames:inventory_sha256={inventory}",
                    "purpose_registration": {"status": "unresolved", "evidence": None},
                    "identity_review": {"status": "pending", "evidence": None},
                    "training_overlap": {"status": "unknown", "evidence": None},
                    "near_duplicate_review": {"status": "pending", "evidence": None},
                }
            ],
            "records": records,
        }
    )
    audit = metadata.audit_manifest(manifest)
    # Outer report marker only. Do not add fields to the K5 manifest (strict schema).
    audit["local_only"] = True
    manifest_body = metadata._encode(manifest)
    # Keep the K5 packet loadable by the dataset_manifest CLI budget.
    require(len(manifest_body) <= metadata.MAX_JSON_BYTES, "K5_MANIFEST_TOO_LARGE")
    failures = _counts(r["failure"] for r in rows if r["failure"])
    status = "passed" if stable and not rejected and not failures else "needs_review"
    stats = {
        "schema_id": STATS_SCHEMA,
        "status": status,
        "producer_sha256": PRODUCER_SHA256,
        "python_runtime": sys.version.split()[0],
        "pillow_version": Image.__version__,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "images_dir": images_dir,
        "inventory_sha256": inventory,
        "k5_manifest_sha256": hashlib.sha256(manifest_body).hexdigest(),
        "k5_audit_status": audit["status"],
        "inputs_stable": stable,
        "policy": {
            "filename": "<id>_<name>_<age>_<gender>.jpg; id from the left, age/gender from "
            "the right, name = the rest (may contain '_')",
            "identity": "NFC-normalized name, case-sensitive; id is a per-image key",
            "age_valid": f"canonical integer {AGE_MIN}-{AGE_MAX}; outside "
            f"{AGE_LOW}-{AGE_HIGH} is kept and counted, never rejected",
            "gender_valid": GENDERS,
            "duplicate_image_id": "reject_all_copies",
            "unreadable_header": "k5_failed_and_excluded_from_size_stats",
            "span": "max-min age per identity",
            "k5_use": "unassigned",
        },
        "counts": {
            "entries_scanned": len(files)
            + sum(
                r["reason"] in {"LINK_OR_REPARSE_PATH", "PATH_TOO_DEEP", "NOT_REGULAR_FILE"}
                for r in rejected
            ),
            "k5_records": len(records),
            "rejected": len(rejected),
            "rejected_by_reason": _counts(r["reason"] for r in rejected),
            "image_failures_by_code": failures,
            "exif_orientation_not_identity": sum(
                r["orientation"] not in (None, 1) for r in rows if r["failure"] is None
            ),
        },
        "summary": summarize(rows),
        "contains_file_names_or_person_names": False,
        **FLAGS,
    }
    rejected_doc = {
        "schema_id": SCHEMA,
        "local_only": True,
        "images_dir": images_dir,
        "inventory_sha256": inventory,
        "rejected": rejected,
    }
    payloads = {
        "stats.json": acquisition._encoded(stats),
        "rejected.json": acquisition._encoded(rejected_doc),
        "manifest.json": manifest_body,
        "audit.json": metadata._encode(audit),
    }
    require(all(len(body) <= MAX_OUTPUT_BYTES for body in payloads.values()), "REPORT_TOO_LARGE")
    return stats, payloads


def export(root, images_dir, output):
    """Validate, collect and build first; only then create the new output directory."""
    root = Path(root).absolute()
    require(root.is_dir() and root == root.resolve(), "INVALID_ROOT")
    base = safe(root, images_dir)
    target = safe(root, output)
    require(
        output.startswith("output/research/") and not target.exists(),
        "OUTPUT_MUST_BE_NEW_IGNORED_DIRECTORY",
    )
    require(
        not target.is_relative_to(base) and not base.is_relative_to(target),
        "OUTPUT_OVERLAPS_INPUT",
    )
    stats, payloads = build(root, images_dir)
    created = target
    while not created.parent.exists():
        created = created.parent
    target.mkdir(parents=True, exist_ok=False)
    try:
        for leaf, body in payloads.items():
            with safe(root, output + "/" + leaf).open("xb") as stream:
                stream.write(body)
    except BaseException:
        # A rejection leaves nothing behind: remove only what this run created.
        shutil.rmtree(target, ignore_errors=True)
        path = target.parent
        while path != created.parent and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            path = path.parent
        raise
    return {**stats, "output_dir": output}


LOCAL_ONLY_WARNING = "含文件名的输出仅限用户本机"
LOCAL_ONLY_ACK_REQUIRED = "LOCAL_ONLY_ACK_REQUIRED"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "未传入 --local-only-ack 时拒绝运行且不写任何文件。"
            "含文件名的输出（rejected.json、audit.json、manifest.json）仅限用户本机。"
        ),
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--images-dir", required=True, help="e.g. data/datasets/agedb")
    parser.add_argument("--output-dir", required=True, help="new output/research/... directory")
    parser.add_argument(
        "--local-only-ack",
        action="store_true",
        help=(
            "必须显式传入才会执行。确认含文件名的输出仅限用户本机、不得外传。"
            "未传此参数时拒绝运行且不写任何文件。"
        ),
    )
    args = parser.parse_args(argv)
    if not args.local_only_ack:
        print(
            "拒绝执行：未传入 --local-only-ack。"
            "本工具会写出含文件名的本机专用报告，默认禁止运行。"
            "请仅在用户本机确认后显式传入 --local-only-ack。",
            file=sys.stderr,
        )
        print(json.dumps({"status": "rejected", "error_code": LOCAL_ONLY_ACK_REQUIRED, **FLAGS}))
        return 2
    print(f"==========\n{LOCAL_ONLY_WARNING}\n==========", file=sys.stderr)
    try:
        stats = export(args.root, args.images_dir, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **FLAGS}))
        return 2
    print(
        json.dumps(
            {
                "status": stats["status"],
                "output_dir": stats["output_dir"],
                "counts": stats["counts"],
                "summary": stats["summary"],
                **FLAGS,
            },
            ensure_ascii=False,
        )
    )
    return 0 if stats["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
