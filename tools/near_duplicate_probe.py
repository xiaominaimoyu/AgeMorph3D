"""Retrieve possible duplicate originals; similarity is not identity or leakage acceptance."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import struct
import sys
from itertools import combinations, product
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError, features
from PIL import __version__ as pillow_version

_HELPER_PATH = Path(__file__).with_name("evaluation_readiness_probe.py")
_SPEC = importlib.util.spec_from_file_location("_near_duplicate_metadata", _HELPER_PATH)
metadata = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(metadata)

PROTOCOL = "agemorph3d-near-duplicate-v1"
SOURCES = (
    "tools/evaluation_readiness_probe.py",
    "backend/tests/test_evaluation_readiness_probe.py",
    "tools/near_duplicate_probe.py",
    "backend/tests/test_near_duplicate_probe.py",
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 16000000
ENVIRONMENT = {"python_version": "3.11.16", "pillow_version": "13.0.0"}
FALSE_FLAGS = (
    "images_or_thumbnails_written",
    "candidate_review_complete",
    "no_leakage_accepted",
    "independent_evaluation",
    "legal_permission_established",
    "service_ready",
    "production_enabled",
    "g3_complete",
)
ALGORITHM = {
    "orientation": "Pillow ImageOps.exif_transpose before all features",
    "color": "Convert to RGB; no ICC color management transform",
    "views": ["original", "mirror"],
    "mirror": "Horizontal mirror of EXIF-corrected RGB",
    "pixel_sha256": (
        "SHA256(b'agemorph3d-rgb-v1\\0' + struct.pack('>II', width, height) "
        "+ b'RGB\\0' + RGB bytes); \\0 denotes one NUL byte"
    ),
    "grayscale": "Pillow convert('L')",
    "resample": "LANCZOS",
    "horizontal_size": [9, 8],
    "vertical_size": [8, 9],
    "comparison": "Right > left for horizontal; below > above for vertical",
    "bit_order": "Row-major, first comparison is the most significant of 64 bits",
    "diagnostic_size": [32, 32],
    "diagnostic": (
        "Per matched view-pair mean absolute grayscale byte difference divided by 255; "
        "no per-image normalization and no candidate filtering"
    ),
    "max_horizontal_hamming": 8,
    "max_vertical_hamming": 8,
    "candidate": (
        "At least one of all four view-pairs jointly satisfies both Hamming cutoffs; "
        "retain every matched view-pair and deduplicate only the unordered image pair"
    ),
    "exact_duplicates": (
        "Record same file SHA-256 and every equal dimension-bound pixel SHA-256 "
        "view-pair separately from perceptual candidate labels"
    ),
}
LIMITS = {
    "metadata_max_bytes": 2097152,
    "image_max_bytes": MAX_IMAGE_BYTES,
    "image_max_pixels": MAX_PIXELS,
    "max_images": 500,
    "image_formats": ["JPEG", "PNG", "WEBP"],
    "frames": 1,
}


def _protocol(value):
    metadata._keys(
        value,
        {
            "schema_version",
            "protocol_id",
            "frozen_on",
            "scope",
            "observations",
            "algorithm",
            "limits",
            "accounting",
            "output_policy",
            "known_limits",
        },
        "Near-duplicate protocol",
    )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["protocol_id"] != PROTOCOL
    ):
        raise ValueError("Unsupported near-duplicate protocol.")
    # JSON serialization distinguishes false from 0 and integer sizes from floats.
    if json.dumps(value["algorithm"], sort_keys=True) != json.dumps(
        ALGORITHM, sort_keys=True
    ) or json.dumps(value["limits"], sort_keys=True) != json.dumps(LIMITS, sort_keys=True):
        raise ValueError(
            "Near-duplicate algorithm or limits differ from the frozen implementation."
        )
    policy = value["output_policy"]
    metadata._keys(
        policy,
        {
            *FALSE_FLAGS,
            "automatic_original_image_feature_reading_disclosed",
            "human_candidate_review",
        },
        "Output policy",
    )
    metadata._false_flags(policy, FALSE_FLAGS, "Near-duplicate output policy")
    if policy["automatic_original_image_feature_reading_disclosed"] is not True:
        raise ValueError("Automatic original feature access must be disclosed.")
    metadata._text(policy["human_candidate_review"], "Human-review policy")
    observations = value["observations"]
    metadata._keys(
        observations,
        {
            "historical_n0_preprocessing_exposed",
            "new_near_duplicate_results_seen",
            "threshold_basis",
        },
        "Observations",
    )
    if (
        observations["historical_n0_preprocessing_exposed"] is not True
        or observations["new_near_duplicate_results_seen"] is not False
    ):
        raise ValueError(
            "Protocol must disclose historical preprocessing and prospective thresholds."
        )
    metadata._text(observations["threshold_basis"], "Threshold basis")
    metadata._keys(
        value["accounting"],
        {
            "requested_pairs",
            "comparable_pairs",
            "uncomparable_pairs",
            "source_integrity",
            "grouping",
            "components",
        },
        "Accounting",
    )
    for text in [
        value["scope"],
        value["frozen_on"],
        *value["accounting"].values(),
        *metadata._list(value["known_limits"], "Known limits"),
    ]:
        metadata._text(text, "Protocol explanation")


def _pixel_hash(image):
    return hashlib.sha256(
        b"agemorph3d-rgb-v1\0" + struct.pack(">II", *image.size) + b"RGB\0" + image.tobytes()
    ).hexdigest()


def _dhash(gray, horizontal):
    width, height = (9, 8) if horizontal else (8, 9)
    pixels = gray.resize((width, height), Image.Resampling.LANCZOS).tobytes()
    result = 0
    for y in range(8):
        for x in range(8):
            first = y * width + x
            second = first + (1 if horizontal else width)
            result = (result << 1) | (pixels[second] > pixels[first])
    return result


def _view(image):
    gray = image.convert("L")
    try:
        return {
            "horizontal": _dhash(gray, True),
            "vertical": _dhash(gray, False),
            "pixel_sha256": _pixel_hash(image),
            "gray32": gray.resize((32, 32), Image.Resampling.LANCZOS).tobytes(),
        }
    finally:
        gray.close()


def _decode(raw):
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in LIMITS["image_formats"]:
            raise ValueError("unsupported_format")
        if getattr(source, "n_frames", 1) != 1:
            raise ValueError("multiple_frames")
        if source.width * source.height > MAX_PIXELS:
            raise ValueError("pixel_limit")
        source.verify()
    with Image.open(io.BytesIO(raw)) as source:
        source.load()
        corrected = ImageOps.exif_transpose(source)
        rgb = corrected.convert("RGB")
        try:
            mirror = ImageOps.mirror(rgb)
            try:
                return {
                    "width": rgb.width,
                    "height": rgb.height,
                    "views": {"original": _view(rgb), "mirror": _view(mirror)},
                }
            finally:
                mirror.close()
        finally:
            rgb.close()
            corrected.close()


def _snapshot(root, row):
    path = metadata._relative(root, row["path"])
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("Original image metadata must reference JPEG/PNG/WebP paths.")
    state = {
        "path": row["path"],
        "bytes": None,
        "sha256": None,
        "verification": "read_failed",
        "matches_declared": False,
    }
    try:
        state["bytes"] = path.stat().st_size
        if row["bytes"] > MAX_IMAGE_BYTES or state["bytes"] > MAX_IMAGE_BYTES:
            state["verification"] = "not_verified_size_limit"
            return state, None
        with path.open("rb") as stream:
            raw = stream.read(MAX_IMAGE_BYTES + 1)
        state["bytes"] = len(raw)
        if len(raw) > MAX_IMAGE_BYTES:
            state["verification"] = "not_verified_size_limit"
            return state, None
        state["sha256"] = hashlib.sha256(raw).hexdigest()
        state["matches_declared"] = len(raw) == row["bytes"] and state["sha256"] == row["sha256"]
        state["verification"] = "verified" if state["matches_declared"] else "hash_or_size_mismatch"
        return state, raw if state["matches_declared"] else None
    except OSError:
        return state, None


def _matches(left, right):
    hits, exact_pixels = [], []
    for (left_name, left_view), (right_name, right_view) in product(
        left["views"].items(), right["views"].items()
    ):
        names = {"left_view": left_name, "right_view": right_name}
        if left_view["pixel_sha256"] == right_view["pixel_sha256"]:
            exact_pixels.append(names)
        horizontal = (left_view["horizontal"] ^ right_view["horizontal"]).bit_count()
        vertical = (left_view["vertical"] ^ right_view["vertical"]).bit_count()
        if horizontal <= 8 and vertical <= 8:
            mae = sum(
                abs(a - b) for a, b in zip(left_view["gray32"], right_view["gray32"], strict=True)
            ) / (1024 * 255)
            hits.append(
                {
                    **names,
                    "horizontal_hamming": horizontal,
                    "vertical_hamming": vertical,
                    "gray32_mae": mae,
                }
            )
    return hits, exact_pixels


def _candidates(rows, feature_rows):
    candidates = []
    for left, right in combinations(sorted(feature_rows), 2):
        hits, exact_pixels = _matches(feature_rows[left], feature_rows[right])
        if hits:
            candidates.append(
                {
                    "candidate_id": len(candidates),
                    "left_index": left,
                    "right_index": right,
                    "left_path": rows[left]["path"],
                    "right_path": rows[right]["path"],
                    "cross_group": rows[left]["group"] != rows[right]["group"],
                    "cross_identity": rows[left]["subject_id"] != rows[right]["subject_id"],
                    "label_age_difference": abs(
                        rows[left]["source_age"] - rows[right]["source_age"]
                    ),
                    "same_file_sha256": rows[left]["sha256"] == rows[right]["sha256"],
                    "equal_pixel_view_pairs": exact_pixels,
                    "matched_view_pairs": hits,
                }
            )
    return candidates


def _components(candidates):
    adjacency = {}
    for edge in candidates:
        left, right = edge["left_index"], edge["right_index"]
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    seen, components = set(), []
    for start in sorted(adjacency):
        if start in seen:
            continue
        pending, nodes = [start], set()
        while pending:
            node = pending.pop()
            if node in nodes:
                continue
            nodes.add(node)
            pending.extend(adjacency[node] - nodes)
        seen.update(nodes)
        edges = [
            {
                "candidate_id": edge["candidate_id"],
                "left_index": edge["left_index"],
                "right_index": edge["right_index"],
            }
            for edge in candidates
            if edge["left_index"] in nodes
        ]
        components.append(
            {
                "component_id": len(components),
                "image_indices": sorted(nodes),
                "edges": edges,
                "meaning": (
                    "Similarity review queue; no all-pairs duplicate or shared-identity inference."
                ),
            }
        )
    return components


def build_report(root: Path, plan_path: Path):
    root = Path(root).resolve(strict=True)
    plan_path = Path(plan_path).resolve(strict=True)
    if not plan_path.is_relative_to(root) or plan_path.suffix != ".json":
        raise ValueError("Study plan must be workspace JSON metadata.")
    raw = metadata._read(plan_path)
    plan = metadata._json(raw)
    metadata._keys(
        plan,
        {"protocol_id", "protocol", "n0_manifest", "age_protocol", "source_files", "environment"},
        "Study plan",
    )
    if (
        plan["protocol_id"] != PROTOCOL
        or plan["environment"] != ENVIRONMENT
        or any(type(value) is not str for value in plan["environment"].values())
    ):
        raise ValueError("Study plan protocol or frozen environment differs.")
    if {"python_version": sys.version.split()[0], "pillow_version": pillow_version} != ENVIRONMENT:
        raise ValueError("Running Python/Pillow environment differs from the frozen environment.")
    inputs = metadata._Inputs(root)
    inputs.read(
        {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    roles = ("protocol", "n0_manifest", "age_protocol")
    primary = [plan[role]["path"] for role in roles]
    if len(set(primary)) != len(primary):
        raise ValueError("Input roles must have distinct metadata paths.")
    values = {role: metadata._json(inputs.read(plan[role])) for role in roles}
    inputs.many(plan["source_files"], "Source files")
    source_pins = {pin["path"]: pin for pin in plan["source_files"]}
    if set(source_pins) != set(SOURCES) or set(primary) & set(source_pins):
        raise ValueError("Source pins must bind exactly the two CLIs and their tests.")
    for name, running in ((SOURCES[0], _HELPER_PATH), (SOURCES[2], Path(__file__))):
        if source_pins[name]["sha256"] != hashlib.sha256(metadata._read(running)).hexdigest():
            raise ValueError("Source pins differ from the running implementation.")
    _protocol(values["protocol"])
    manifest = values["n0_manifest"]
    summary = metadata._n0(
        values["age_protocol"], manifest, manifest.get("summary"), plan["age_protocol"]
    )
    rows = manifest["adult_images"]
    if len(rows) > LIMITS["max_images"]:
        raise ValueError("Cohort exceeds the frozen image-count bound.")
    # Resolve all original paths before opening any photograph.
    for row in rows:
        path = metadata._relative(root, row["path"])
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ValueError("Original path must have a supported image extension.")
    records, feature_rows = [], {}
    for index, row in enumerate(rows):
        initial, snapshot = _snapshot(root, row)
        record = {
            "index": index,
            "source": {
                key: row[key]
                for key in ("path", "sha256", "bytes", "subject_id", "group", "source_age")
            },
            "initial_source_check": initial,
            "status": initial["verification"],
        }
        if snapshot is not None:
            try:
                feature = _decode(snapshot)
                feature_rows[index] = feature
                record.update(
                    status="ok",
                    width=feature["width"],
                    height=feature["height"],
                    views={
                        name: {
                            "horizontal_dhash": f"{view['horizontal']:016x}",
                            "vertical_dhash": f"{view['vertical']:016x}",
                            "pixel_sha256": view["pixel_sha256"],
                        }
                        for name, view in feature["views"].items()
                    },
                )
            except Image.DecompressionBombError:
                record["status"] = "pixel_limit"
            except UnidentifiedImageError:
                record["status"] = "bad_image"
            except ValueError as error:
                record["status"] = (
                    str(error)
                    if str(error) in {"unsupported_format", "multiple_frames", "pixel_limit"}
                    else "bad_image"
                )
            except (OSError, SyntaxError) as error:
                record["status"] = (
                    "truncated_image"
                    if any(
                        word in str(error).lower()
                        for word in ("truncated", "broken data stream", "not enough image")
                    )
                    else "bad_image"
                )
        records.append(record)
    candidates = _candidates(rows, feature_rows)
    components = _components(candidates)
    analysis_image_count = len(feature_rows)
    integrity = True
    for index, (row, record) in enumerate(zip(rows, records, strict=True)):
        final, _ = _snapshot(root, row)
        record["final_source_check"] = final
        changed = final != record["initial_source_check"]
        record["source_changed"] = changed
        if changed:
            record["status_before_source_change"] = record["status"]
            record["status"] = "source_changed"
            feature_rows.pop(index, None)
        integrity &= (
            final["matches_declared"]
            and record["initial_source_check"]["matches_declared"]
            and not changed
        )
    if len(feature_rows) != analysis_image_count:
        # Every retained edge was already computed; discard all edges incident
        # to a changed source without rerunning image comparisons after the check.
        candidates = [
            edge
            for edge in candidates
            if edge["left_index"] in feature_rows and edge["right_index"] in feature_rows
        ]
        components = _components(candidates)
    inputs.verify()
    n, s = len(rows), len(feature_rows)
    requested, comparable = n * (n - 1) // 2, s * (s - 1) // 2
    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL,
        "integrity_status": "passed" if integrity else "failed",
        "screening_status": "complete" if s == n and integrity else "incomplete",
        "research_only": True,
        **dict.fromkeys(FALSE_FLAGS, False),
        "automatic_original_image_feature_reading_disclosed": True,
        "source_age_semantics": (
            "Unverified research filename labels only; no API SourceAge is created."
        ),
        "holdout_model_results_read": False,
        "models_loaded": False,
        "environment": {
            **ENVIRONMENT,
            "codecs": {name: features.version(name) for name in ("jpg", "zlib", "webp")},
        },
        "inputs": [inputs.pins[path] for path in sorted(inputs.pins)],
        "n0_cohort_summary": summary,
        "summary_verification": (
            "Recomputed from pinned manifest metadata; no independently pinned summary report."
        ),
        "source_image_pins": [
            {key: row[key] for key in ("path", "sha256", "bytes")} for row in rows
        ],
        "records": records,
        "pair_counts": {
            "requested": requested,
            "comparable": comparable,
            "uncomparable": requested - comparable,
        },
        "image_counts": {"requested": n, "successful": s, "failed": n - s},
        "analysis_image_count_before_final_source_check": analysis_image_count,
        "final_source_check_phase": "after_candidate_and_component_analysis",
        "candidates": candidates,
        "components": components,
        "candidate_counts": {
            "all": len(candidates),
            "cross_group": sum(edge["cross_group"] for edge in candidates),
            "cross_identity": sum(edge["cross_identity"] for edge in candidates),
            "same_file_sha256": sum(edge["same_file_sha256"] for edge in candidates),
            "equal_pixel_pairs": sum(bool(edge["equal_pixel_view_pairs"]) for edge in candidates),
        },
        "known_limits": values["protocol"]["known_limits"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        output = metadata._relative(root, args.output_dir)
        allowed = (root / "output/research").resolve()
        if (
            not output.is_relative_to(allowed)
            or output == allowed
            or not allowed.is_relative_to(root)
        ):
            raise ValueError("Output must be a new descendant of workspace output/research.")
        if output.exists():
            raise FileExistsError("Output already exists; prior evidence is preserved.")
        plan_path = (
            args.study_plan
            if args.study_plan.is_absolute()
            else metadata._relative(root, args.study_plan.as_posix())
        )
        report = build_report(root, plan_path)
        output.mkdir(parents=True, exist_ok=False)
        with (output / "report.json").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "integrity_status",
                        "screening_status",
                        "image_counts",
                        "pair_counts",
                        "candidate_counts",
                    )
                }
            )
        )
        return 0 if report["screening_status"] == "complete" else 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
