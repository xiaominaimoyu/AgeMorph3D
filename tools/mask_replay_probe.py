"""Reproduce a frozen mask candidate and explain existing UV rejection pixels.

The twelve-mask equality gate precedes every UV decomposition. This offline
tool writes JSON only; it neither infers models nor writes masks or textures.
Finite-cohort equivalence does not establish historical process identity.
"""

# Offline entrypoint sharing the already frozen byte and UV validation helpers.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import io
import math
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

import cv2
import numpy as np
import uv_support_probe as uv

PROTOCOL_ID = "agemorph3d-mask-replay-v1"
ROLES = (
    "protocol",
    "uv_report",
    "registration_report",
    "generated_report",
    "n0_manifest",
    "registration_protocol",
    "mask_review",
)
SOURCES = (*uv.SOURCES, "tools/mask_replay_probe.py", "backend/tests/test_mask_replay_probe.py")
FALSE_FLAGS = (*uv.FALSE_FLAGS, "historical_process_identity_proven")
PIXEL_REASONS = {
    "allowed": 0,
    "outside_landmark_hull": 1,
    "erosion_ring": 2,
    "mouth_exclusion": 3,
    "reviewed_candidate_band": 4,
}
REASON_BITS = {
    "outside_landmark_hull": 1,
    "erosion_ring": 2,
    "mouth_exclusion": 4,
    "reviewed_candidate_band": 8,
}
VECTOR_NAMES = (
    "texel_rows_columns",
    "face_owner",
    "barycentric",
    "target_xyz",
    "source_canonical_xyz",
    "region_bits",
    "rejection_partition",
)
VECTOR_DTYPES = {
    "texel_rows_columns": np.dtype("<i4"),
    "face_owner": np.dtype("<i4"),
    "barycentric": np.dtype("<f8"),
    "target_xyz": np.dtype("<f8"),
    "source_canonical_xyz": np.dtype("<f8"),
    "region_bits": np.dtype("u1"),
    "rejection_partition": np.dtype("u1"),
}


def _landmarks(value):
    array = np.asarray(value)
    if array.shape != (68, 2) or array.dtype.kind not in "iuf" or not np.isfinite(array).all():
        raise ValueError("Mask construction requires 68 finite continuous XY landmarks.")
    result = np.asarray(array, dtype=np.float64)
    rounded = np.rint(result)
    limits = np.iinfo(np.int32)
    if np.any(rounded < limits.min) or np.any(rounded > limits.max):
        raise ValueError("Rounded polygon coordinates exceed int32.")
    return result, np.ascontiguousarray(rounded, dtype=np.int32)


def _dimensions(width, height):
    if (
        type(width) is not int
        or type(height) is not int
        or width < 1
        or height < 1
        or width * height > uv.PIXEL_LIMIT
    ):
        raise ValueError("Mask dimensions must be positive integers within the pixel budget.")


def _rectangles(exclusions, width, height):
    if not isinstance(exclusions, list) or len(exclusions) > 16:
        raise ValueError("Reviewed exclusions must be a bounded rectangle list.")
    result = []
    keys = {"kind", "x0", "x1_exclusive", "y0", "y1_exclusive"}
    for rectangle in exclusions:
        if (
            not isinstance(rectangle, dict)
            or set(rectangle) != keys
            or rectangle["kind"] != "glasses_candidate_band"
            or any(type(rectangle[key]) is not int for key in keys - {"kind"})
        ):
            raise ValueError("Only exact integer reviewed glasses rectangles are supported.")
        x0, x1 = rectangle["x0"], rectangle["x1_exclusive"]
        y0, y1 = rectangle["y0"], rectangle["y1_exclusive"]
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError("Reviewed rectangles must have positive in-image half-open extent.")
        result.append((x0, y0, x1, y1))
    return result


def audit_exclusions(sample_id, landmarks, exclusions, width, height):
    _dimensions(width, height)
    continuous, _ = _landmarks(landmarks)
    _rectangles(exclusions, width, height)
    expected = {f"{source}--sam-{age:03d}" for source, ages in uv.COHORT.items() for age in ages}
    if sample_id not in expected:
        raise ValueError("Mask replay is restricted to the twelve predeclared target conditions.")
    if sample_id.startswith("fgnet-004a63--"):
        threshold = math.floor(float(continuous[17:27, 1].min())) - 18
        wanted = [
            {
                "kind": "glasses_candidate_band",
                "x0": 0,
                "x1_exclusive": width,
                "y0": threshold,
                "y1_exclusive": 650,
            }
        ]
        if exclusions != wanted:
            raise ValueError(
                "Focus band must use continuous eyebrow floor and the saved row650 end."
            )
    elif exclusions:
        raise ValueError("The eight comparator targets require no reviewed exclusion bands.")


def _polygon(points, width, height):
    hull = cv2.convexHull(points)
    if len(hull) < 3 or cv2.contourArea(hull) <= 0:
        raise ValueError("Rounded landmark polygon has a degenerate integer convex hull.")
    raster = np.zeros((height, width), np.uint8)
    cv2.fillConvexPoly(raster, hull, 255, lineType=cv2.LINE_8, shift=0)
    return raster


def construct_masks(landmarks, width, height, exclusions):
    """Run the predeclared candidate, with explicit borders and recipe priority."""
    _dimensions(width, height)
    _, rounded = _landmarks(landmarks)
    rectangles = _rectangles(exclusions, width, height)
    hull = _polygon(rounded[:27], width, height)
    eroded = cv2.erode(
        hull,
        np.ones((9, 9), np.uint8),
        anchor=(-1, -1),
        iterations=1,
        borderType=cv2.BORDER_CONSTANT,
        borderValue=255,
    )
    mouth = _polygon(rounded[60:68], width, height)
    mouth = cv2.dilate(
        mouth,
        np.ones((7, 7), np.uint8),
        anchor=(-1, -1),
        iterations=1,
        borderType=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    h, e, m = hull != 0, eroded != 0, mouth != 0
    band = np.zeros((height, width), bool)
    for x0, y0, x1, y1 in rectangles:
        band[y0:y1, x0:x1] = True
    base = e & ~m
    allowed, occluded = base & ~band, base & band
    reason = np.zeros((height, width), np.uint8)
    reason[~h] = PIXEL_REASONS["outside_landmark_hull"]
    reason[h & ~e] = PIXEL_REASONS["erosion_ring"]
    reason[e & m] = PIXEL_REASONS["mouth_exclusion"]
    reason[occluded] = PIXEL_REASONS["reviewed_candidate_band"]
    if np.any(e & ~h) or not np.array_equal(reason == 0, allowed):
        raise ValueError("Candidate morphology failed the exclusive recipe-stage partition.")
    result = {
        "H": h,
        "E": e,
        "M": m,
        "B": band,
        "base": base,
        "allowed": allowed,
        "occluded": occluded,
        "reason": reason,
    }
    result["pixel_counts"] = {
        **{name: int(array.sum()) for name, array in result.items() if name != "reason"},
        "reasons": {
            name: int(np.count_nonzero(reason == code)) for name, code in PIXEL_REASONS.items()
        },
    }
    return result


def pixel_comparison(reconstructed, original_allowed, original_occluded):
    uv._masks(original_allowed, original_occluded)
    answer = {}
    for name, original in (("allowed", original_allowed), ("occluded", original_occluded)):
        candidate = reconstructed[name]
        if (
            not isinstance(candidate, np.ndarray)
            or candidate.dtype != np.bool_
            or candidate.shape != original.shape
        ):
            raise ValueError(
                "Candidate and original masks must share the exact boolean pixel frame."
            )
        answer[name] = {
            "xor_mismatch_pixels": int(np.count_nonzero(candidate ^ original)),
            "added_pixels": int(np.count_nonzero(candidate & ~original)),
            "removed_pixels": int(np.count_nonzero(original & ~candidate)),
            "reconstructed_pixels": int(candidate.sum()),
            "original_pixels": int(original.sum()),
        }
    answer["exact"] = all(
        answer[name]["xor_mismatch_pixels"] == 0 for name in ("allowed", "occluded")
    )
    return answer


def all_masks_match(comparisons, expected=12):
    return len(comparisons) == expected and all(
        isinstance(row, dict) and row.get("exact") is True for row in comparisons
    )


def contributor_bits(reason, xy):
    reason, xy = np.asarray(reason), np.asarray(xy, dtype=np.float64)
    if (
        reason.dtype != np.uint8
        or reason.ndim != 2
        or not all(reason.shape)
        or reason.size > uv.PIXEL_LIMIT
        or np.any(reason > 4)
        or xy.ndim != 2
        or xy.shape[1] != 2
        or not np.isfinite(xy).all()
        or np.any(xy < 0)
        or np.any(xy[:, 0] > reason.shape[1] - 1)
        or np.any(xy[:, 1] > reason.shape[0] - 1)
    ):
        raise ValueError("Contributor queries need bounded recipe reasons and finite in-image XY.")
    x0, y0 = np.floor(xy).astype(np.int64).T
    x1, y1 = np.minimum(x0 + 1, reason.shape[1] - 1), np.minimum(y0 + 1, reason.shape[0] - 1)
    dx, dy = xy[:, 0] - x0, xy[:, 1] - y0
    lookup = np.array([0, 1, 2, 4, 8], np.uint8)
    bits = np.zeros(len(xy), np.uint8)
    for x, y, weight in (
        (x0, y0, (1 - dx) * (1 - dy)),
        (x1, y0, dx * (1 - dy)),
        (x0, y1, (1 - dx) * dy),
        (x1, y1, dx * dy),
    ):
        bits |= np.where(weight > 0, lookup[reason[y, x]], 0).astype(np.uint8)
    return bits


def decompose_regions(
    bits, old_partition, region_bits, region_names=tuple(uv.REGIONS), *, expected_counts=None
):
    bits, old_partition, region_bits = map(np.asarray, (bits, old_partition, region_bits))
    if (
        bits.dtype != np.uint8
        or old_partition.dtype != np.uint8
        or region_bits.dtype != np.uint8
        or bits.ndim != 1
        or bits.shape != old_partition.shape
        or bits.shape != region_bits.shape
        or len(bits) > 65536
        or np.any(bits < 1)
        or np.any(bits > 15)
        or not 1 <= len(region_names) <= 4
        or np.any(region_bits >= 1 << len(region_names))
    ):
        raise ValueError(
            "Class5 vectors must have valid nonzero contributor bitsets and region bits."
        )
    partition = (bits & 8 != 0).astype(np.uint8) + 2 * (bits & 7 != 0).astype(np.uint8)
    if not np.array_equal(partition, old_partition):
        raise ValueError(
            "Recipe contributor bits disagree with the frozen three-way mask partition."
        )
    result = {}
    for index, name in enumerate(("all_unique_correspondence", *region_names)):
        selected = np.ones(len(bits), bool) if index == 0 else region_bits & (1 << (index - 1)) != 0
        count = int(selected.sum())
        combinations = {
            str(code): int(np.count_nonzero(bits[selected] == code)) for code in range(1, 16)
        }
        partitions = {
            label: int(np.count_nonzero(partition[selected] == code))
            for label, code in uv.REJECTION_CODES.items()
            if code
        }
        if sum(combinations.values()) != count or sum(partitions.values()) != count:
            raise ValueError("Contributor combinations must partition the rejected denominator.")
        requested = count
        if expected_counts is not None:
            old = expected_counts[name]
            requested = old["requested"]
            if (
                count != old["classification_counts"]["mask_rejected"]
                or partitions != old["rejection_counts"]
            ):
                raise ValueError(
                    "Decomposition does not retain the frozen regional rejection totals."
                )
        result[name] = {
            "requested": requested,
            "mask_rejected": count,
            "combination_counts": combinations,
            "partition_counts": partitions,
        }
    return result


def load_vectors(data, expected_count=None):
    """Check exact bounded ZIP/NPY schema before NumPy allocates any vector payload."""
    if not isinstance(data, bytes) or len(data) > uv.BINARY_LIMIT:
        raise ValueError("Correspondence archive exceeds its compressed byte budget.")
    expected = {name + ".npy" for name in VECTOR_NAMES}
    rows = None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if (
                len(entries) != 7
                or {entry.filename for entry in entries} != expected
                or any(
                    entry.flag_bits & 1 or entry.file_size > uv.UNPACKED_LIMIT for entry in entries
                )
                or sum(entry.file_size for entry in entries) > uv.UNPACKED_LIMIT
            ):
                raise ValueError("Correspondence archive names or expanded byte budget is invalid.")
            for entry in entries:
                with archive.open(entry) as stream:
                    version = np.lib.format.read_magic(stream)
                    if version == (1, 0):
                        shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
                    elif version == (2, 0):
                        shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
                    else:
                        raise ValueError("Unsupported correspondence NPY header version.")
                    name = entry.filename[:-4]
                    columns = (
                        2
                        if name == "texel_rows_columns"
                        else 3
                        if name
                        in {
                            "barycentric",
                            "target_xyz",
                            "source_canonical_xyz",
                        }
                        else None
                    )
                    wanted = (
                        (shape[0], columns)
                        if len(shape) and columns
                        else (shape[0],)
                        if len(shape)
                        else ()
                    )
                    if (
                        not shape
                        or type(shape[0]) is not int
                        or not 0 <= shape[0] <= 65536
                        or shape != wanted
                        or dtype != VECTOR_DTYPES[name]
                        or dtype.hasobject
                        or math.prod(shape) * dtype.itemsize + stream.tell() != entry.file_size
                        or rows is not None
                        and rows != shape[0]
                    ):
                        raise ValueError(
                            "Correspondence NPY shape, dtype or row binding is invalid."
                        )
                    rows = shape[0]
            if expected_count is not None and rows != expected_count:
                raise ValueError(
                    "Correspondence row count differs from the frozen unique UV domain."
                )
        with np.load(io.BytesIO(data), allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in VECTOR_NAMES}
    except (zipfile.BadZipFile, EOFError, OverflowError) as error:
        raise ValueError("Malformed bounded correspondence archive.") from error
    if any(array.dtype.kind == "f" and not np.isfinite(array).all() for array in arrays.values()):
        raise ValueError("Correspondence vectors must remain finite.")
    rc, owner, bary = arrays["texel_rows_columns"], arrays["face_owner"], arrays["barycentric"]
    linear = rc[:, 0].astype(np.int64) * 256 + rc[:, 1]
    if (
        np.any(rc < 0)
        or np.any(rc > 255)
        or np.any(np.diff(linear) <= 0)
        or np.any(owner < 0)
        or np.any(owner >= 300_000)
        or np.any(bary < -1e-8)
        or np.any(bary > 1 + 1e-8)
        or np.any(np.abs(bary.sum(axis=1) - 1) > 1e-8)
        or np.any(arrays["region_bits"] > 15)
        or np.any(arrays["rejection_partition"] > 3)
    ):
        raise ValueError("Correspondence indices, barycentrics or saved reason bits are invalid.")
    return arrays


def derive_input_pins(metadata):
    """Derive the entire old closure and all twelve vector pins from the report."""
    old = metadata["uv_report"]
    pins = {}
    for value in [
        *old["inputs"],
        *(row["correspondence"] for row in old["records"]),
        metadata["registration_report"]["inputs"]["protocol"],
        metadata["registration_report"]["inputs"]["mask_review"],
    ]:
        pin = uv._pin(value)
        if pin["path"] in pins and pins[pin["path"]] != pin:
            raise ValueError("Conflicting inherited UV or correspondence pins.")
        pins[pin["path"]] = pin
    return list(pins.values())


def _protocol(protocol):
    if (
        protocol.get("schema_version") != 1
        or protocol.get("protocol_id") != PROTOCOL_ID
        or protocol["cohort"]["sources"] != uv.COHORT
        or protocol["cohort"]["expected_targets"] != 12
        or protocol["cohort"]["group"] != "development"
        or protocol["cohort"]["api_source_age"] != uv.UNKNOWN_AGE
        or protocol["flags"] != {"research_only": True, **dict.fromkeys(FALSE_FLAGS, False)}
        or protocol["construction"]["pixel_reasons"] != PIXEL_REASONS
        or protocol["uv_contributors"]["reason_bits"] != REASON_BITS
        or protocol["equivalence_gate"]["all_cohort_required"] is not True
        or protocol["observations"]["candidate_pixel_equivalence_seen_before_freeze"] is not False
        or protocol["observations"]["detailed_other_rejection_results_seen_before_freeze"]
        is not False
        or protocol["quality_threshold"] is not None
    ):
        raise ValueError("Unsupported mask candidate protocol, cohort or closed research boundary.")


def _selected(inputs, roles, metadata):
    old = metadata["uv_report"]
    if (
        old.get("protocol_id") != uv.PROTOCOL_ID
        or len(old["inputs"]) != 112
        or old["summary"]["requested_targets"] != 12
        or old["summary"]["all_requested_verified"] is not True
        or old["integrity"]["all_inputs_unchanged"] is not True
        or old["integrity"]["runtime_unchanged"] is not True
        or old["region_bit_order"] != list(uv.REGIONS)
        or old["classification_codes"] != uv.REASONS
        or old["rejection_partition_codes"] != uv.REJECTION_CODES
        or any(old.get(key) is not False for key in uv.FALSE_FLAGS)
        or old.get("research_only") is not True
    ):
        raise ValueError("The exact prior twelve-target verified UV report is required.")
    for name in ("n0_manifest", "registration_report", "generated_report"):
        if roles[name] != old["roles"][name]:
            raise ValueError("Mask replay roles differ from the prior verified UV evidence.")
    registration = metadata["registration_report"]
    for name, old_name in (("registration_protocol", "protocol"), ("mask_review", "mask_review")):
        if roles[name] != registration["inputs"][old_name]:
            raise ValueError("Historical constructor documentation or review pin differs from N4.")
    old_protocol = uv._json(inputs.read(old["roles"]["protocol"], uv.META_LIMIT))
    reset = uv._json(inputs.read(old["roles"]["source_reset_report"], uv.META_LIMIT))
    selected = uv.select_targets(
        old_protocol, metadata["n0_manifest"], registration, metadata["generated_report"], reset
    )
    records = uv._indexed(old["records"])
    reviews = uv._indexed(metadata["mask_review"]["target_records"])
    if set(records) != {item["registration"]["sample_id"] for item in selected}:
        raise ValueError("Prior UV vectors must cover the same exact twelve target conditions.")
    for item in selected:
        row = item["registration"]
        saved = records[row["sample_id"]]
        if (
            saved["status"] != "ok"
            or saved["source_id"] != row["source_id"]
            or saved["target_age_condition"] != row["target_age"]
            or saved["source_age_label"] != row["source_age_label"]
            or saved["source_age"] != uv.UNKNOWN_AGE
            or reviews[row["sample_id"]] != row["mask_review"]
        ):
            raise ValueError(
                "UV correspondence, target review or source semantics were reassigned."
            )
    return selected, records


def _pixel_record(inputs, item):
    row, fit = item["registration"], item["fit"]
    size = fit["image_size"]
    if not isinstance(size, list) or len(size) != 2:
        raise ValueError("Saved target dimensions are unavailable.")
    width, height = size
    points = np.asarray(fit["projected_landmarks"], dtype=np.float64)
    if points.shape not in {(68, 2), (68, 3)} or not np.isfinite(points).all():
        raise ValueError("Target-own saved landmarks must provide 68 finite XY points.")
    points = points[:, :2]
    review = row["mask_review"]
    audit_exclusions(row["sample_id"], points, review["exclusions"], width, height)
    candidate = construct_masks(points, width, height, review["exclusions"])
    masks = []
    for name in ("allowed_mask", "occluded_mask"):
        pixels = uv._png(inputs.read(review[name]), "L", size)
        if not np.isin(pixels, (0, 255)).all():
            raise ValueError("Original reviewed masks must contain only PNG values0/255.")
        masks.append(pixels == 255)
    comparison = pixel_comparison(candidate, *masks)
    if (
        comparison["allowed"]["original_pixels"] != review["allowed_pixels"]
        or comparison["occluded"]["original_pixels"] != review["excluded_occluder_pixels"]
    ):
        raise ValueError("Original mask arrays differ from frozen review pixel totals.")
    return candidate, comparison


def _decompose(inputs, item, old, reason):
    row = item["registration"]
    vectors = load_vectors(
        inputs.read(old["correspondence"]), old["counts"]["all_unique_correspondence"]["requested"]
    )
    classification = uv._png(inputs.read(row["artifacts"]["classification"]), "L", (256, 256))
    if not np.isin(classification, tuple(uv.REASONS.values())).all():
        raise ValueError("Original atlas classification contains an unknown reason code.")
    rc = vectors["texel_rows_columns"]
    classes = classification[rc[:, 0], rc[:, 1]]
    rejected = classes == uv.REASONS["mask_rejected"]
    if (
        np.count_nonzero(classification >= uv.REASONS["back_facing"]) != len(rc)
        or np.any(classes < uv.REASONS["back_facing"])
        or not np.array_equal(vectors["rejection_partition"] > 0, rejected)
    ):
        raise ValueError(
            "Saved vector domain differs from the exact old unique/class5 classification."
        )
    counts = uv.region_counts(
        classification, rc, vectors["region_bits"], vectors["rejection_partition"]
    )
    if counts != old["counts"]:
        raise ValueError(
            "Saved vector regions or all-class denominators differ from the UV report."
        )
    global_counts = {
        name: int(np.count_nonzero(classification == code)) for name, code in uv.REASONS.items()
    }
    if global_counts != old["global_classification_counts"]:
        raise ValueError("Saved original classification totals differ from the prior UV report.")
    bits = contributor_bits(reason, vectors["target_xyz"][rejected, :2])
    return decompose_regions(
        bits,
        vectors["rejection_partition"][rejected],
        vectors["region_bits"][rejected],
        expected_counts=counts,
    )


def _encode(report):
    import json

    return (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode(
        "utf-8"
    )


def _invalidate(report, error):
    for row in report["records"]:
        row.pop("decomposition", None)
        row.update(status="invalidated_input_drift", error_code="INPUT_DRIFT", detail=str(error))
    report["summary"].update(
        statuses={"invalidated_input_drift": 12},
        all_masks_pixel_equal=False,
        all_requested_verified=False,
        decomposition_targets=0,
    )
    report["integrity"] = {"all_inputs_unchanged": False, "detail": str(error)}


def run(args):
    root = Path(args.root).resolve()
    output = uv._output_path(root, args.output_dir)
    plan_name = Path(args.study_plan)
    plan_path = (plan_name if plan_name.is_absolute() else root / plan_name).resolve()
    if root not in plan_path.parents:
        raise ValueError("Study plan must stay within the selected workspace.")
    with plan_path.open("rb") as stream:
        plan_bytes = stream.read(uv.META_LIMIT + 1)
    if len(plan_bytes) > uv.META_LIMIT:
        raise ValueError("Study plan exceeds the metadata byte budget.")
    plan, runtime = uv._json(plan_bytes), uv.runtime_fingerprint()
    if (
        plan.get("schema_version") != 1
        or plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("runtime") != runtime
        or set(plan["roles"]) != set(ROLES)
    ):
        raise ValueError("Plan protocol, required roles or runtime fingerprint is invalid.")
    inputs, roles = uv.Inputs(root, plan["inputs"]), plan["roles"]
    metadata = {name: uv._json(inputs.read(roles[name], uv.META_LIMIT)) for name in ROLES}
    _protocol(metadata["protocol"])
    inherited = derive_input_pins(metadata)
    for pin in inherited:
        if inputs.pins.get(pin["path"]) != pin:
            raise ValueError("Freeze omits or changes an inherited UV input/vector pin.")
    required = (
        {pin["path"] for pin in inherited} | {pin["path"] for pin in roles.values()} | set(SOURCES)
    )
    if not required <= inputs.pins.keys():
        raise ValueError("Freeze omits candidate implementation, tests or required metadata.")
    if any(
        Path(name).suffix.lower() not in {".py", ".json", ".md", ".toml", ".lock"}
        for name in inputs.pins.keys() - required
    ):
        raise ValueError("Arbitrary new binary inputs outside the inherited cohort are forbidden.")
    selected, old_records = _selected(inputs, roles, metadata)
    snapshot_error = None
    try:
        for pin in inputs.pins.values():
            limit = (
                uv.BINARY_LIMIT
                if Path(pin["path"]).suffix.lower() in {".png", ".npz"}
                else uv.META_LIMIT
            )
            inputs.read(pin, limit)
    except (OSError, ValueError, KeyError, TypeError) as error:
        snapshot_error = error
    records, reasons = [], {}
    for item in selected:
        row = item["registration"]
        record = {
            "sample_id": row["sample_id"],
            "source_id": row["source_id"],
            "target_age_condition": row["target_age"],
            "source_age_label": row["source_age_label"],
            "source_age": dict(uv.UNKNOWN_AGE),
            "status": "failed",
            "decomposition": None,
        }
        try:
            if snapshot_error is not None:
                raise ValueError("Verified input snapshot unavailable: " + str(snapshot_error))
            candidate, comparison = _pixel_record(inputs, item)
            record.update(
                status="pixel_match" if comparison["exact"] else "pixel_mismatch",
                pixel_comparison=comparison,
                layer_pixel_counts=candidate["pixel_counts"],
                reviewed_exclusions=row["mask_review"]["exclusions"],
            )
            if comparison["exact"]:
                reasons[row["sample_id"]] = candidate["reason"]
            else:
                record["error_code"] = "MASK_PIXEL_MISMATCH"
        except (OSError, ValueError, KeyError, TypeError, cv2.error) as error:
            record.update(
                error_code="MASK_REPLAY_FAILED", error_type=type(error).__name__, detail=str(error)
            )
        records.append(record)
        print(
            f"Mask candidate {len(records)}/12: {row['sample_id']} {record['status']}", flush=True
        )
    matched = all_masks_match([row.get("pixel_comparison") for row in records])
    if matched:
        for record, item in zip(records, selected, strict=True):
            try:
                record["decomposition"] = _decompose(
                    inputs, item, old_records[record["sample_id"]], reasons[record["sample_id"]]
                )
                record["status"] = "ok"
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                record.update(
                    status="decomposition_failed",
                    error_code="UV_DECOMPOSITION_FAILED",
                    error_type=type(error).__name__,
                    detail=str(error),
                    decomposition=None,
                )
    else:
        for record in records:
            if record["status"] == "pixel_match":
                record.update(
                    status="pixel_match_decomposition_blocked",
                    error_code="COHORT_PIXEL_GATE_FAILED",
                )
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **metadata["protocol"]["flags"],
        "study_plan": {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(plan_bytes),
            "sha256": uv._digest(plan_bytes),
        },
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "pixel_reason_codes": PIXEL_REASONS,
        "contributor_reason_bits": REASON_BITS,
        "contributor_combination_labels": {
            str(code): [name for name, bit in REASON_BITS.items() if code & bit]
            for code in range(1, 16)
        },
        "region_bit_order": list(uv.REGIONS),
        "records": records,
        "summary": {
            "requested_targets": 12,
            "requested_sources": 3,
            "statuses": dict(Counter(row["status"] for row in records)),
            "all_masks_pixel_equal": matched,
            "decomposition_targets": sum(row["status"] == "ok" for row in records),
            "all_requested_verified": all(row["status"] == "ok" for row in records),
        },
        "interpretation": "Finite-cohort pixel equivalence and recipe-stage labels only; "
        "no historical constructor identity, anatomical truth or NO_FACE cause is established.",
    }

    def audit():
        inputs.recheck()
        with plan_path.open("rb") as stream:
            current = stream.read(uv.META_LIMIT + 1)
        if current != plan_bytes or uv.runtime_fingerprint() != runtime:
            raise ValueError("Study plan, loaded sources or runtime drifted after calculation.")

    output.mkdir(parents=True, exist_ok=False)
    encoded = _encode(report)
    try:
        audit()
    except (OSError, ValueError) as error:
        _invalidate(report, error)
    else:
        report["integrity"] = {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
            "verified_input_count": len(inputs.pins),
        }
    encoded = _encode(report)
    destination = output / "report.json"
    with destination.open("xb") as stream:
        stream.write(encoded)
    try:
        audit()
    except (OSError, ValueError) as error:
        _invalidate(report, error)
        destination.unlink()
        with destination.open("xb") as stream:
            stream.write(_encode(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args)
        print(_encode(report["summary"]).decode("utf-8").strip())
        return 0 if report["summary"]["all_requested_verified"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
