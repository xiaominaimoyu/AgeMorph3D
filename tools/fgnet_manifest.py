"""Extract the research mirror of FG-NET and write a local provenance manifest.

The mirror page states that the dataset is for research use and that its author
does not own it. This tool therefore records an explicit unresolved/research-only
status and never makes the data part of the source tree. It only writes under the
Git-ignored ``data/`` directory.

Usage:
    python tools/fgnet_manifest.py --zip data/datasets/fgnet/FGNET.zip \
        --out data/datasets/fgnet
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

_IMAGE_RE = re.compile(
    r"^(?P<subject>\d{3})A(?P<age>\d{2})(?P<suffix>[A-Za-z]?)\.JPG$", re.IGNORECASE
)
_CSV_FIELDS = ("subject_id", "age", "image", "sha256", "size_bytes")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract(zip_path: Path, out_dir: Path) -> None:
    out_root = out_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            name = member.filename
            if not name.startswith("FGNET/") or name.startswith("__MACOSX"):
                continue
            target = (out_dir / name).resolve()
            if out_root not in target.parents and target != out_root:
                raise ValueError(f"archive member escapes the output directory: {name}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size == member.file_size:
                continue
            with archive.open(member) as source, target.open("wb") as destination:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    destination.write(block)


def _rows(images_dir: Path, out_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(images_dir.iterdir()):
        match = _IMAGE_RE.fullmatch(path.name)
        if not match:
            continue
        relative = path.relative_to(out_dir).as_posix()
        rows.append(
            {
                "subject_id": match.group("subject"),
                "age": int(match.group("age")),
                "image": relative,
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    rows.sort(key=lambda row: (row["subject_id"], row["age"], row["image"]))
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    zip_path = args.zip.resolve()
    out_dir = args.out.resolve()
    if not zip_path.is_file():
        raise SystemExit(f"missing archive: {zip_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    _extract(zip_path, out_dir)
    images_dir = out_dir / "FGNET" / "images"
    rows = _rows(images_dir, out_dir)
    if not rows:
        raise SystemExit("no FGNET images matched the expected naming pattern")
    adult = [row for row in rows if 20 <= int(row["age"]) <= 70]
    if not adult:
        raise SystemExit("no adult 20-70 samples found")

    _write_csv(out_dir / "all-images.csv", rows)
    _write_csv(out_dir / "adult-20-70.csv", adult)

    manifest = {
        "schema_version": 1,
        "dataset_id": "fgnet-research-mirror",
        "source_page": "https://yanweifu.github.io/FG_NET_data/",
        "source_url": "http://yanweifu.github.io/FG_NET_data/FGNET.zip",
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "archive": {
            "path": "FGNET.zip",
            "sha256": _sha256(zip_path),
            "size_bytes": zip_path.stat().st_size,
        },
        "extracted_root": "FGNET",
        "counts": {
            "images": len(rows),
            "subjects": len({row["subject_id"] for row in rows}),
            "adult_20_70_images": len(adult),
            "adult_20_70_subjects": len({row["subject_id"] for row in adult}),
        },
        "age_range": {
            "min": min(int(row["age"]) for row in rows),
            "max": max(int(row["age"]) for row in rows),
        },
        "adult_age_range": {
            "min": min(int(row["age"]) for row in adult),
            "max": max(int(row["age"]) for row in adult),
        },
        "label_provenance": (
            "Filename encodes subject ID and age at photo (e.g. 078A11.JPG = "
            "subject 78 at age 11), as documented by the source page. Labels "
            "were not independently re-verified against birth records."
        ),
        "license": {
            "status": "research-only-unresolved",
            "statement": (
                'The mirror page states "This dataset is just used for research '
                'purpose" and that its author does not own the dataset. The '
                "original FG-NET site is no longer the distribution point. This "
                "is not a formal license grant or proof of consent for "
                "redistribution."
            ),
            "allowed_use": (
                "Local, non-commercial academic research and calibration/sanity "
                "checks only."
            ),
            "redistribution": (
                "Do not redistribute images or derived copies. Files stay under "
                "Git-ignored data/."
            ),
        },
        "limitations": [
            "Only 82 subjects total; the 20-70 subset has 55 subjects and 292 images.",
            "Most images are children; ages 40-69 are sparse and age 70 is absent.",
            "Third-party mirror, not a first-party licensed distribution.",
            "No subject consent documentation is included.",
            "Not sufficient by itself to claim G3 age calibration or "
            "identity-preservation acceptance.",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["counts"], ensure_ascii=False))
    print(f"wrote {out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
