"""Explicit offline scalar-ledger summarization; no assets or models are loaded."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

from agemorph3d import age_statistics, evaluation_metrics
from agemorph3d.evaluation_metrics import FLAGS, summarize_study

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 16 * 1024**2
SOURCES = (
    Path(__file__).resolve(),
    Path(age_statistics.__file__).resolve(),
    Path(evaluation_metrics.__file__).resolve(),
)
LOADED = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}


def _path(root, name):
    if (
        type(name) is not str
        or not name
        or "\\" in name
        or ":" in name
        or PurePosixPath(name).is_absolute()
        or PurePosixPath(name).as_posix() != name
        or ".." in PurePosixPath(name).parts
    ):
        raise ValueError("Use canonical workspace-relative paths.")
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes workspace.")
    return path


def _read(path, maximum=MAX_BYTES):
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Selected JSON is missing/nonregular/oversized.")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Input grew beyond its budget.")
    return raw


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Nonfinite JSON value.")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def export(root, name, digest, output):
    source = _path(root, name)
    if source.suffix != ".json":
        raise ValueError("Select a JSON packet.")
    raw = _read(source)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Input SHA-256 mismatch.")
    report = summarize_study(_json(raw))
    report.update(
        input={"path": name, "bytes": len(raw), "sha256": digest},
        producer_sources=[
            {"path": p.relative_to(ROOT).as_posix(), "sha256": LOADED[str(p)]} for p in SOURCES
        ],
    )
    payload = (json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()
    if len(payload) > MAX_BYTES:
        raise ValueError("Output JSON exceeds its budget.")
    target = _path(root, output)
    if not output.startswith("output/research/") or source.is_relative_to(target):
        raise ValueError("Use a fresh ignored research directory outside the selected input.")

    def recheck():
        if _read(source, len(raw)) != raw or any(
            hashlib.sha256(p.read_bytes()).hexdigest() != LOADED[str(p)] for p in SOURCES
        ):
            raise ValueError("Input or producer changed during computation.")

    recheck()
    target.mkdir(parents=True, exist_ok=False)
    owned = []
    try:
        path = target / "report.json"
        with path.open("xb") as stream:
            owned.append(path)
            stream.write(payload)
        recheck()
    except BaseException:
        for path in owned:
            path.unlink()
        if not any(target.iterdir()):
            target.rmdir()
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = export(ROOT, args.packet, args.sha256, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as error:
        print(
            json.dumps({"status": "invalid_input", "error": str(error), **FLAGS}), file=sys.stderr
        )
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "requests": report["requested_pairs"],
                "identities": report["requested_identities"],
                **FLAGS,
            }
        )
    )
    return 1 if report["status"] == "completed_with_failures" else 0


if __name__ == "__main__":
    raise SystemExit(main())
