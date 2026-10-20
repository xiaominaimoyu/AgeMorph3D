"""Freeze local age-research identity groups and hash-bound same-age controls.

This standard-library CLI performs no inference, training, calibration or service
changes. Prior FG-NET preprocessing remains disclosed for every identity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path


def _path(root: Path, value: str | Path, base: Path | None = None) -> Path:
    value = Path(str(value).replace("\\", "/"))
    path = (value if value.is_absolute() else (base or root) / value).resolve()
    if path != root and root not in path.parents:
        raise ValueError("Evidence paths must stay within the selected workspace root.")
    return path


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pin(root: Path, path: Path, expected=None, size=None) -> dict:
    digest = _hash(path)
    actual_size = path.stat().st_size
    if expected is not None and digest != expected:
        raise ValueError(f"SHA-256 mismatch: {path.relative_to(root).as_posix()}")
    if size is not None and actual_size != size:
        raise ValueError(f"File size mismatch: {path.relative_to(root).as_posix()}")
    return {"path": path.relative_to(root).as_posix(), "sha256": digest, "bytes": actual_size}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dataset(root: Path, subset: Path, protocol: dict) -> tuple[list, dict]:
    rows, seen = [], set()
    with subset.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            subject, age = row["subject_id"], int(row["age"])
            path = _path(root, row["image"], subset.parent)
            match = re.fullmatch(r"(\d{3})A(\d{2})[A-Za-z]?\.JPG", path.name, re.I)
            if (
                not match
                or subject != match[1]
                or age != int(match[2])
                or not 20 <= age <= 70
                or path in seen
            ):
                raise ValueError("Adult CSV identity, age or unique image metadata is invalid.")
            seen.add(path)
            rows.append(
                dict(
                    subject_id=subject,
                    source_age=age,
                    **_pin(root, path, row["sha256"], int(row["size_bytes"])),
                )
            )
    identities = sorted({row["subject_id"] for row in rows})
    if (len(rows), len(identities)) != (
        protocol["expected_adult_images"],
        protocol["expected_adult_identities"],
    ):
        raise ValueError("Adult image/identity counts differ from the frozen protocol.")
    grouping = protocol["grouping"]
    development = set(grouping["development_subject_ids"])
    if len(development) != len(grouping["development_subject_ids"]) or not development <= set(
        identities
    ):
        raise ValueError("Development identities must be unique and present in the adult CSV.")
    remaining = sorted(
        set(identities) - development,
        key=lambda subject: hashlib.sha256(f"{grouping['seed']}:{subject}".encode()).hexdigest(),
    )
    count = grouping["calibration_identity_count"]
    if type(count) is not int or not 0 <= count <= len(remaining):
        raise ValueError("Invalid calibration identity count.")
    calibration = set(remaining[:count])
    groups = {
        subject: (
            "development"
            if subject in development
            else "calibration_research"
            if subject in calibration
            else "evaluation_research_holdout"
        )
        for subject in identities
    }
    digest_groups = {}
    for row in rows:
        row["group"] = group = groups[row["subject_id"]]
        if digest_groups.setdefault(row["sha256"], group) != group:
            raise ValueError("Identical image bytes occur across identity-use groups.")
    return sorted(rows, key=lambda row: row["path"]), groups


def _sam(root: Path, path: Path, input_hash: str, checkpoint: str) -> tuple[dict, list]:
    report = _load(path)
    if (
        report["input"]["sha256"] != input_hash
        or report["checkpoint"]["sha256"] != checkpoint
        or report.get("outputs_written") is not True
    ):
        raise ValueError("SAM input/checkpoint/output state does not match frozen evidence.")
    runs, ages = [], set()
    for run in report["runs"]:
        age = run["target_age"]
        if type(age) is not int or age in ages:
            raise ValueError("SAM targets must be unique integer conditions.")
        ages.add(age)
        output = _path(root, run["output"], path.parent)
        if output.parent != path.parent:
            raise ValueError("SAM output must be local to its report directory.")
        runs.append(dict(target_age=age, **_pin(root, output, run["output_sha256"])))
    return _pin(root, path), runs


def _coverage(rows: list, groups: dict) -> dict:
    strata, eligible = {}, {}
    for group in ["all", *sorted(set(groups.values()))]:
        selected = rows if group == "all" else [row for row in rows if row["group"] == group]
        strata[group] = {}
        for low, high in ((20, 29), (30, 39), (40, 49), (50, 59), (60, 69), (70, 70)):
            ages = [row for row in selected if low <= row["source_age"] <= high]
            strata[group][str(low) if low == high else f"{low}-{high}"] = {
                "images": len(ages),
                "identities": len({row["subject_id"] for row in ages}),
            }
        by_subject = {}
        for row in selected:
            by_subject.setdefault(row["subject_id"], set()).add(row["source_age"])
        eligible[group] = sum(len(ages) >= 2 for ages in by_subject.values())
    return {"age_strata": strata, "distinct_age_pair_eligible_identities": eligible}


def build_manifest(
    root: Path,
    protocol_path: Path,
    subset: Path,
    bridge_path: Path,
    controls_dir: Path,
    frozen_path: Path | None = None,
) -> dict:
    """Verify evidence and construct a deterministic snapshot without writing."""
    root = root.resolve()
    frozen = None
    if frozen_path is not None:
        frozen = _load(frozen_path)
        pinned = {_path(root, path): pin for path, pin in frozen["inputs"].items()}
        if not {protocol_path, subset, bridge_path} <= pinned.keys():
            raise ValueError("Frozen evidence must bind protocol, adult CSV and bridge report.")
        for path, pin in pinned.items():
            _pin(root, path, pin)
    protocol = _load(protocol_path)
    if (
        protocol["schema_version"] != 1
        or protocol["same_age_policy"] != "exact_integer_label_only"
        or protocol["source_age_policy"] != "unknown_stays_null"
    ):
        raise ValueError("Unsupported frozen protocol policies.")
    rows, groups = _dataset(root, subset, protocol)
    if frozen is not None and (
        frozen["protocol_id"] != protocol["protocol_id"] or frozen["identity_groups"] != groups
    ):
        raise ValueError("Identity assignments differ from the pre-inference frozen evidence.")
    by_path = {row["path"]: row for row in rows}
    bridge = _load(bridge_path)
    if len(bridge["samples"]) != protocol.get("expected_bridge_samples", 12):
        raise ValueError("Bridge sample count differs from the frozen protocol.")
    cases, seen = [], set()
    for sample in bridge["samples"]:
        sample_id = sample["id"]
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}", sample_id) or sample_id in seen:
            raise ValueError("Bridge sample identifiers must be safe and unique.")
        seen.add(sample_id)
        original = _pin(root, _path(root, sample["path"]), sample["input_sha256"])
        age = sample["age"]
        record = by_path.get(original["path"])
        if record is not None:
            subject = record["subject_id"]
            if (
                sample.get("subject_id") != subject
                or age != record["source_age"]
                or original["sha256"] != record["sha256"]
                or groups[subject] != "development"
            ):
                raise ValueError("Viewed bridge identity/age must match development CSV evidence.")
        else:
            subject = f"external:{sample_id}"
            if age is not None or sample.get("subject_id") is not None:
                raise ValueError("External demonstration source ages must remain unknown/null.")
            for row in rows:
                if row["sha256"] == original["sha256"] and row["group"] != "development":
                    raise ValueError("Viewed external sample duplicates a non-development image.")
        case_path = _path(root, sample["bridge_report"])
        report = _load(case_path)
        if report["input"]["sha256"] != original["sha256"] or (
            report["technical_execution"] != sample["technical_execution"]
            or report.get("error_code") != sample.get("error_code")
        ):
            raise ValueError("Per-case bridge status/input differs from aggregate evidence.")
        artifacts = {
            name: _pin(root, _path(root, name, case_path.parent), pin["sha256"], pin["bytes"])
            for name, pin in report.get("artifacts", {}).items()
        }
        case = dict(
            sample_id=sample_id,
            subject_id=subject,
            group="development",
            source=original,
            source_age={
                "value": age,
                "method": "dataset_filename" if age is not None else "unknown",
                "independently_verified": False,
            },
            bridge_report=_pin(root, case_path),
            artifacts=artifacts,
            source_status=report["technical_execution"],
            error_code=report.get("error_code"),
        )
        control = {"status": "blocked_source_failure", "target_age": None}
        if report["technical_execution"] == "passed":
            aligned_hash = artifacts["aligned.png"]["sha256"]
            sam_path = _path(root, sample["sam_report"])
            sam_pin, runs = _sam(root, sam_path, aligned_hash, bridge["sam_checkpoint_sha256"])
            if (
                sorted(run["target_age"] for run in runs) != sorted(protocol["target_ages"])
                or sample["sam_input_sha256"] != aligned_hash
                or [(run["target_age"], run["sha256"]) for run in runs]
                != [(run["target_age"], run["output_sha256"]) for run in sample["sam_runs"]]
            ):
                raise ValueError("Existing SAM runs differ from frozen bridge conditions/pins.")
            case.update(sam_report=sam_pin, target_runs=runs)
            if age is None:
                control = {"status": "not_applicable_unknown_source_age", "target_age": None}
            elif (
                isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age)
            ):
                raise ValueError("Known source age must be finite numeric metadata.")
            elif int(age) != age:
                control = {"status": "unsupported_fractional_source_age", "target_age": None}
            else:
                control = {"status": "pending", "target_age": int(age)}
                match = next((run for run in runs if run["target_age"] == age), None)
                if match:
                    control.update(status="reused_existing", report=sam_pin, output=match)
                else:
                    same_path = _path(root, controls_dir / sample_id / "report.json")
                    if same_path.exists():
                        pin, generated = _sam(
                            root, same_path, aligned_hash, bridge["sam_checkpoint_sha256"]
                        )
                        if len(generated) != 1 or generated[0]["target_age"] != age:
                            raise ValueError(
                                "Same-age control must request the exact source label."
                            )
                        control.update(status="generated", report=pin, output=generated[0])
        case["same_age_control"] = control
        cases.append(case)
    statuses = Counter(case["same_age_control"]["status"] for case in cases)
    known = sum(
        case["source_age"]["value"] is not None and case["source_status"] == "passed"
        for case in cases
    )
    if known != protocol.get("expected_known_controls", 8):
        raise ValueError("Known successful source count differs from the frozen protocol.")
    for field, actual in (
        ("inputs", len(cases)),
        ("alignment_successes", sum(case["source_status"] == "passed" for case in cases)),
        ("sam_images", sum(len(case.get("target_runs", [])) for case in cases)),
    ):
        if field in bridge and bridge[field] != actual:
            raise ValueError("Aggregate bridge counts do not match retained case evidence.")
    complete = known == statuses["generated"] + statuses["reused_existing"]
    inputs = {
        "protocol": _pin(root, protocol_path),
        "adult_subset": _pin(root, subset),
        "bridge_report": _pin(root, bridge_path),
    }
    if frozen_path is not None:
        inputs["pre_inference_freeze"] = _pin(root, frozen_path)
    for name, path in (
        ("dataset_manifest", subset.parent / "manifest.json"),
        (
            "historical_pipeline_report",
            root / "output/research/fgnet-pipeline-20261020/report.json",
        ),
    ):
        if path.exists():
            inputs[name] = _pin(root, _path(root, path))
    return dict(
        schema_version=1,
        protocol_id=protocol["protocol_id"],
        frozen_on=protocol["frozen_on"],
        research_only=True,
        training_use=False,
        service_ready=False,
        g3_complete=False,
        independent_external_evaluation=False,
        independent_landmark_nme_evaluation=False,
        historical_preprocessing_exposed=True,
        inputs=inputs,
        identities=[
            dict(
                subject_id=subject,
                group=group,
                historical_preprocessing_exposed=True,
                previously_viewed=group == "development",
            )
            for subject, group in sorted(groups.items())
        ],
        adult_images=rows,
        bridge_cases=cases,
        summary={
            "adult_images": len(rows),
            "adult_identities": len(groups),
            "identity_groups": dict(Counter(groups.values())),
            "image_groups": dict(Counter(row["group"] for row in rows)),
            "control_statuses": dict(sorted(statuses.items())),
            "same_age_controls_complete": complete,
            **_coverage(rows, groups),
        },
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--protocol", default="docs/age-evaluation-v1.json")
    parser.add_argument("--subset", default="data/datasets/fgnet/adult-20-70.csv")
    parser.add_argument(
        "--bridge-report", default="output/research/ffhq-bridge-20261020/report.json"
    )
    parser.add_argument("--controls-dir", default="output/research/age-protocol-20261020/same-age")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--require-controls", action="store_true")
    parser.add_argument(
        "--frozen-inputs", help="Verify a pre-inference freeze.json before publishing."
    )
    args = parser.parse_args(argv)
    root, created = args.root.resolve(), []
    try:
        output = _path(root, args.output_dir)
        if output.exists():
            raise FileExistsError("Output directory already exists; prior evidence is preserved.")
        manifest = build_manifest(
            root,
            _path(root, args.protocol),
            _path(root, args.subset),
            _path(root, args.bridge_report),
            _path(root, args.controls_dir),
            _path(root, args.frozen_inputs) if args.frozen_inputs else None,
        )
        if args.require_controls and not manifest["summary"]["same_age_controls_complete"]:
            raise ValueError("Exact same-age controls are incomplete; no snapshot was published.")
        output.mkdir(parents=True, exist_ok=False)
        for name, value in (("manifest.json", manifest), ("summary.json", manifest["summary"])):
            with (output / name).open("x", encoding="utf-8", newline="\n") as stream:
                created.append(output / name)
                stream.write(
                    json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
                )
        print(json.dumps(manifest["summary"], ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        for path in created:
            path.unlink(missing_ok=True)
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
