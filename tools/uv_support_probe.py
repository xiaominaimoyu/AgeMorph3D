"""Audit twelve existing target-owned UV correspondences without inference or edits.

Only immutable, hash-verified byte snapshots are decoded. The saved original
float32 UV is promoted before its v flip, matching the producer's arithmetic.
No photo, texture, GLB or mask is written. Model weights and GLBs are not read.
"""

# Standalone research entrypoint using only these existing numerical helpers.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import platform
import re
import struct
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))

import numpy as np
from agemorph3d import uv_texture as uv_helpers
from agemorph3d.tddfa import TddfaResult, project_vertices
from PIL import Image

PROTOCOL_ID = "agemorph3d-uv-support-v1"
SOURCES = (
    "tools/uv_support_probe.py",
    "backend/src/agemorph3d/__init__.py",
    "backend/src/agemorph3d/tddfa.py",
    "backend/src/agemorph3d/uv_texture.py",
    "backend/tests/test_uv_support_probe.py",
)
ROLES = (
    "protocol",
    "n0_manifest",
    "registration_report",
    "generated_report",
    "source_reset_report",
    "triage",
    "topology",
    "uv",
)
COHORT = {
    "fgnet-004a63": [20, 45, 63, 70],
    "fgnet-082a27": [20, 27, 45, 70],
    "fgnet-006a55": [20, 45, 55, 70],
}
REGIONS = {
    "eye_36_41": list(range(36, 42)),
    "eye_42_47": list(range(42, 48)),
    "nose_27_35": list(range(27, 36)),
    "mouth_48_67": list(range(48, 68)),
}
REJECTION_CODES = {
    "none": 0,
    "reviewed_occluder_only": 1,
    "other_ineligible_only": 2,
    "mixed_contributors": 3,
}
REASONS = uv_helpers.UV_REASON_CODES
UNKNOWN_AGE = {"value": None, "method": "unknown", "calibration_id": None}
FALSE_FLAGS = (
    "age_quality_accepted",
    "identity_quality_accepted",
    "visual_seam_quality_accepted",
    "independent_evaluation",
    "causal_cause_accepted",
    "masks_modified",
    "unknown_regions_filled",
    "real_model_inference",
    "service_ready",
    "production_enabled",
    "g3_complete",
)
META_LIMIT = 2 * 1024**2
BINARY_LIMIT = 8 * 1024**2
UNPACKED_LIMIT = 32 * 1024**2
PIXEL_LIMIT = 16_000_000
FIT_NAMES = ("vertices", "neutral_vertices", "shape", "expr", "projection", "roi")
SAMPLE_NAMES = ("rgba", "classification", "coverage", "gltf_uv")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _relative(root, name):
    if not isinstance(name, str) or "\\" in name:
        raise ValueError("Input paths must be normalized workspace-relative paths.")
    path = (root / name).resolve()
    if (
        Path(name).is_absolute()
        or root not in path.parents
        or path.relative_to(root).as_posix() != name
    ):
        raise ValueError("Input path escapes the workspace or is not canonical: " + name)
    return path


def _pin(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "bytes", "sha256"}
        or not isinstance(value["path"], str)
        or type(value["bytes"]) is not int
        or value["bytes"] < 1
        or not isinstance(value["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise ValueError("Every input needs an exact path, positive byte count and SHA-256.")
    return dict(value)


def _json(data):
    def pairs(items):
        answer = {}
        for key, value in items:
            if key in answer:
                raise ValueError("Duplicate JSON key: " + key)
            answer[key] = value
        return answer

    def constant(value):
        raise ValueError("Non-finite JSON constant: " + value)

    result = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(result, dict):
        raise ValueError("Metadata must be a JSON object.")
    return result


class Inputs:
    """Read bounded verified bytes once; retain pins for a final fresh disk audit."""

    def __init__(self, root, plan_inputs):
        self.root, self.pins, self.snapshots = Path(root).resolve(), {}, {}
        if not isinstance(plan_inputs, list) or len(plan_inputs) > 256:
            raise ValueError("Frozen inputs must be a bounded list of pins.")
        for value in plan_inputs:
            pin = _pin(value)
            _relative(self.root, pin["path"])
            if pin["path"] in self.pins:
                raise ValueError("Frozen inputs contain a duplicate path.")
            self.pins[pin["path"]] = pin

    def read(self, value, max_bytes=BINARY_LIMIT):
        pin = _pin(value)
        if self.pins.get(pin["path"]) != pin or pin["bytes"] > max_bytes:
            raise ValueError("Input is absent from the freeze or exceeds its byte bound.")
        if pin["path"] not in self.snapshots:
            path = _relative(self.root, pin["path"])
            with path.open("rb") as stream:
                data = stream.read(max_bytes + 1)
            if len(data) != pin["bytes"] or _digest(data) != pin["sha256"]:
                raise ValueError("Input pin mismatch: " + pin["path"])
            self.snapshots[pin["path"]] = data
        return self.snapshots[pin["path"]]

    def recheck(self):
        for pin in self.pins.values():
            path = _relative(self.root, pin["path"])
            digest, size = hashlib.sha256(), 0
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024**2), b""):
                    size += len(block)
                    digest.update(block)
            if size != pin["bytes"] or digest.hexdigest() != pin["sha256"]:
                raise ValueError("Input drift after calculation: " + pin["path"])


def runtime_fingerprint():
    packages = {}
    for name in ("numpy", "Pillow", "opencv-python", "opencv-python-headless", "onnxruntime"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    executable = Path(sys.executable).resolve()
    with executable.open("rb") as stream:
        executable_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "executable": str(executable),
        "executable_sha256": executable_hash,
        "packages": packages,
    }


def _header_valid(name, shape, dtype):
    if dtype.hasobject or dtype.kind not in "biufU" or len(shape) > 3:
        return False
    if any(type(x) is not int or x < 0 or x > 1_200_000 for x in shape):
        return False
    if name in {"vertices", "neutral_vertices"}:
        return dtype.kind == "f" and len(shape) == 2 and 3 <= shape[0] <= 200_000 and shape[1] == 3
    if name == "triangles":
        return dtype.kind in "iu" and len(shape) == 2 and 1 <= shape[0] <= 300_000 and shape[1] == 3
    if name == "keypoint_coordinates":
        return dtype.kind in "iu" and shape == (68, 3)
    exact = {"shape": (40,), "expr": (10,), "projection": (3, 4), "roi": (4,)}
    if name in exact:
        return dtype.kind == "f" and shape == exact[name]
    if name in {"uv", "gltf_uv"}:
        return (
            dtype == np.float32 and len(shape) == 2 and 3 <= shape[0] <= 200_000 and shape[1] == 2
        )
    if name == "topology_sha256":
        return dtype.kind == "U" and dtype.itemsize == 256 and shape == ()
    if name == "rgba":
        return dtype == np.uint8 and shape == (256, 256, 4)
    if name == "classification":
        return dtype == np.uint8 and shape == (256, 256)
    if name == "coverage":
        return dtype == np.bool_ and shape == (256, 256)
    return False


def safe_npz(data, names):
    """Validate ZIP and small NPY headers before allowing NumPy to allocate arrays."""
    if not isinstance(data, bytes) or len(data) > BINARY_LIMIT:
        raise ValueError("NPZ exceeds its compressed byte budget.")
    expected = {name + ".npy" for name in names}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if (
                len(entries) != len(expected)
                or {e.filename for e in entries} != expected
                or any(e.flag_bits & 1 or e.file_size > UNPACKED_LIMIT for e in entries)
                or sum(e.file_size for e in entries) > UNPACKED_LIMIT
            ):
                raise ValueError("NPZ names, duplication or expanded resource budget is invalid.")
            for entry in entries:
                with archive.open(entry) as stream:
                    version = np.lib.format.read_magic(stream)
                    if version == (1, 0):
                        shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
                    elif version == (2, 0):
                        shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
                    else:
                        raise ValueError("Unsupported NPY header version.")
                    if (
                        not _header_valid(entry.filename[:-4], shape, dtype)
                        or math.prod(shape) * dtype.itemsize + stream.tell() != entry.file_size
                    ):
                        raise ValueError("NPY shape, dtype or declared byte length is invalid.")
        with np.load(io.BytesIO(data), allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in names}
        if any(a.dtype.kind in "f" and not np.isfinite(a).all() for a in arrays.values()):
            raise ValueError("NPZ numeric arrays must be finite.")
        return arrays
    except (zipfile.BadZipFile, EOFError, OverflowError) as error:
        raise ValueError("Malformed bounded NPZ archive.") from error


def _png_size(data):
    if (
        len(data) < 33
        or data[:8] != b"\x89PNG\r\n\x1a\n"
        or data[8:12] != b"\x00\x00\x00\x0d"
        or data[12:16] != b"IHDR"
    ):
        raise ValueError("Expected a PNG with a bounded IHDR.")
    width, height = struct.unpack_from(">II", data, 16)
    if width < 1 or height < 1 or width * height > PIXEL_LIMIT:
        raise ValueError("PNG pixel dimensions exceed the bound.")
    return width, height


def _png(data, mode, size):
    if _png_size(data) != tuple(size):
        raise ValueError("PNG dimensions differ from its frozen pixel frame.")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.mode != mode or image.size != tuple(size):
            raise ValueError("PNG mode or dimensions differ from the expected arrays.")
        pixels = np.asarray(image).copy()
    return pixels


def prepare_uv(uv, faces, size=256):
    uv, faces = np.asarray(uv), np.asarray(faces)
    if (
        uv.dtype != np.float32
        or uv.ndim != 2
        or uv.shape[1] != 2
        or not 3 <= len(uv) <= 200_000
        or not np.isfinite(uv).all()
        or np.any(uv < 0)
        or np.any(uv > 1)
        or faces.dtype.kind not in "iu"
        or faces.ndim != 2
        or faces.shape[1] != 3
        or not 1 <= len(faces) <= 300_000
        or np.any(faces < 0)
        or np.any(faces >= len(uv))
        or np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0)
        or type(size) is not int
        or not 4 <= size <= 1024
    ):
        raise ValueError("UV, native faces or raster size violates the bounded shared binding.")
    gltf_uv = uv.astype(np.float64)
    gltf_uv[:, 1] = 1 - gltf_uv[:, 1]
    return (gltf_uv, *uv_helpers._uv_samples(gltf_uv, faces, size))


def _masks(allowed, occluded):
    if (
        not isinstance(allowed, np.ndarray)
        or not isinstance(occluded, np.ndarray)
        or allowed.dtype != np.bool_
        or occluded.dtype != np.bool_
        or allowed.ndim != 2
        or allowed.shape != occluded.shape
        or not all(allowed.shape)
        or allowed.size > PIXEL_LIMIT
        or np.any(allowed & occluded)
    ):
        raise ValueError("Allowed and reviewed occluder masks must be bounded disjoint booleans.")


def mask_rejection_partition(allowed, occluded, xy):
    _masks(allowed, occluded)
    xy = np.asarray(xy, dtype=np.float64)
    if (
        xy.ndim != 2
        or xy.shape[1] != 2
        or not np.isfinite(xy).all()
        or np.any(xy < 0)
        or np.any(xy[:, 0] > allowed.shape[1] - 1)
        or np.any(xy[:, 1] > allowed.shape[0] - 1)
    ):
        raise ValueError("Bilinear contributor queries must be finite in-image XY.")
    x0, y0 = np.floor(xy).astype(np.int64).T
    x1, y1 = np.minimum(x0 + 1, allowed.shape[1] - 1), np.minimum(y0 + 1, allowed.shape[0] - 1)
    dx, dy = xy[:, 0] - x0, xy[:, 1] - y0
    reviewed, other = np.zeros(len(xy), bool), np.zeros(len(xy), bool)
    for x, y, weight in (
        (x0, y0, (1 - dx) * (1 - dy)),
        (x1, y0, dx * (1 - dy)),
        (x0, y1, (1 - dx) * dy),
        (x1, y1, dx * dy),
    ):
        positive = weight > 0
        reviewed |= positive & occluded[y, x]
        other |= positive & ~allowed[y, x] & ~occluded[y, x]
    return (reviewed.astype(np.uint8) + 2 * other.astype(np.uint8)).astype(np.uint8)


def region_membership(xy, landmarks, regions=None, padding=0.25):
    regions = REGIONS if regions is None else regions
    xy, landmarks = np.asarray(xy, dtype=np.float64), np.asarray(landmarks, dtype=np.float64)
    if (
        xy.ndim != 2
        or xy.shape[1] != 2
        or landmarks.shape != (68, 2)
        or not np.isfinite(xy).all()
        or not np.isfinite(landmarks).all()
        or padding != 0.25
        or not 1 <= len(regions) <= 8
    ):
        raise ValueError("Region points, 68 XY landmarks or predeclared padding is invalid.")
    bits, boxes = np.zeros(len(xy), dtype=np.uint8), {}
    for index, (name, selected) in enumerate(regions.items()):
        indices = np.asarray(selected)
        if (
            indices.dtype.kind not in "iu"
            or not len(indices)
            or np.any(indices < 0)
            or np.any(indices >= 68)
        ):
            raise ValueError("Region landmark indices are invalid.")
        lower, upper = landmarks[indices].min(axis=0), landmarks[indices].max(axis=0)
        extent = upper - lower
        if np.any(extent <= 0) or not np.isfinite(extent).all():
            raise ValueError("A fitted regional box has zero or nonfinite extent.")
        lower, upper = lower - padding * extent, upper + padding * extent
        inside = np.all((xy >= lower) & (xy < upper), axis=1)
        bits[inside] |= np.uint8(1 << index)
        boxes[name] = [*lower.tolist(), *upper.tolist()]
    return bits, boxes


def region_counts(
    classification,
    texel_rows_columns,
    region_bits,
    rejection_partition,
    region_names=tuple(REGIONS),
):
    rc = np.asarray(texel_rows_columns)
    classes = classification[rc[:, 0], rc[:, 1]]
    result = {}
    for index, name in enumerate(("all_unique_correspondence", *region_names)):
        selected = np.ones(len(rc), bool) if index == 0 else region_bits & (1 << (index - 1)) != 0
        counts = {
            name: int(np.count_nonzero(classes[selected] == code)) for name, code in REASONS.items()
        }
        rejected = {
            key: int(np.count_nonzero(rejection_partition[selected] == code))
            for key, code in REJECTION_CODES.items()
            if code
        }
        requested = int(selected.sum())
        if sum(counts.values()) != requested or sum(rejected.values()) != counts["mask_rejected"]:
            raise ValueError("Regional classifications or mask reasons do not partition requests.")
        result[name] = {
            "requested": requested,
            "classification_counts": counts,
            "support": counts["sampled"] / requested if requested else None,
            "rejection_counts": rejected,
        }
    return result


def trace_support(
    raw,
    uv,
    allowed,
    occluded,
    landmarks,
    source_vertices,
    frame,
    saved_arrays=None,
    *,
    raster=None,
    regions=None,
    padding=0.25,
):
    """Trace every uniquely owned texel, retaining all rejected classes and unknowns."""
    _masks(allowed, occluded)
    if raw.coordinate_system != "bfm_model_raw":
        raise ValueError("Target projection requires its own raw BFM fit.")
    faces, vertices = np.asarray(raw.triangles), np.asarray(raw.vertices)
    source_vertices = np.asarray(source_vertices, dtype=np.float64)
    if (
        vertices.shape != (len(uv), 3)
        or source_vertices.shape != vertices.shape
        or not np.isfinite(vertices).all()
        or not np.isfinite(source_vertices).all()
        or np.shape(raw.projection) != (3, 4)
        or not np.isfinite(raw.projection).all()
        or np.shape(raw.roi) != (4,)
        or not np.isfinite(raw.roi).all()
        or raw.roi[2] <= raw.roi[0]
        or raw.roi[3] <= raw.roi[1]
    ):
        raise ValueError("Fit arrays and source correspondence violate their shared shape.")
    block = np.asarray(raw.projection, dtype=np.float64)[:, :3]
    magnitude = np.max(np.abs(block))
    if magnitude == 0 or np.linalg.det(block / magnitude) <= 0:
        raise ValueError("Target affine projection must be proper and nonsingular.")
    singular = np.linalg.svd(block / magnitude, compute_uv=False)
    if singular[-1] <= singular[0] * 1e-6:
        raise ValueError("Target affine projection is singular.")
    gltf_uv, owner, bary, ambiguous = prepare_uv(uv, faces) if raster is None else raster
    size = owner.shape[0]
    unique = (owner >= 0) & ~ambiguous
    yy, xx = np.where(unique)
    face_owner = owner[yy, xx]
    weights = bary[yy, xx]
    projected = project_vertices(raw).astype(np.float64)
    triangles = projected[faces]
    samples = np.sum(weights[:, :, None] * triangles[face_owner], axis=1)
    front = uv_helpers._area(triangles)[face_owner] > 1e-10
    height, width = allowed.shape
    in_image = (
        (samples[:, 0] >= 0)
        & (samples[:, 0] <= width - 1)
        & (samples[:, 1] >= 0)
        & (samples[:, 1] <= height - 1)
    )
    candidates = front & in_image
    visible = np.zeros(len(samples), dtype=bool)
    visible[candidates], depth_pairs = uv_helpers._visible(
        projected,
        faces,
        samples[candidates],
        width,
        height,
    )
    sampled = visible.copy()
    sampled[visible] &= uv_helpers._allowed_bilinear(allowed, samples[visible, :2])
    classification = np.full((size, size), REASONS["outside_uv"], np.uint8)
    classification[(owner >= 0) & ambiguous] = REASONS["ambiguous_uv_overlap"]
    classification[yy, xx] = REASONS["back_facing"]
    for mask, reason in (
        (front, "outside_image"),
        (candidates, "self_occluded"),
        (visible, "mask_rejected"),
        (sampled, "sampled"),
    ):
        classification[yy[mask], xx[mask]] = REASONS[reason]
    coverage = classification == REASONS["sampled"]
    rejection = np.zeros(len(samples), np.uint8)
    rejection[visible] = mask_rejection_partition(allowed, occluded, samples[visible, :2])
    if not np.array_equal(rejection > 0, visible & ~sampled):
        raise ValueError("Contributor partitions disagree with the producer's allowed test.")
    center = np.asarray(frame["source_center"], dtype=np.float64)
    scale = frame["source_to_canonical_uniform_scale"]
    if (
        center.shape != (3,)
        or not np.isfinite(center).all()
        or not np.isfinite(scale)
        or scale <= 0
    ):
        raise ValueError("Original source canonical frame is invalid.")
    source_xyz = np.sum(weights[:, :, None] * source_vertices[faces[face_owner]], axis=1)
    canonical = (source_xyz - center) * scale
    if not np.isfinite(canonical).all():
        raise ValueError("Source canonical correspondence must remain finite.")
    bits, boxes = region_membership(samples[:, :2], landmarks, regions, padding)
    if saved_arrays is not None:
        if set(saved_arrays) != set(SAMPLE_NAMES):
            raise ValueError("Saved sample schema must contain exactly four arrays.")
        rgba = saved_arrays["rgba"]
        if (
            rgba.dtype != np.uint8
            or rgba.shape != (size, size, 4)
            or saved_arrays["classification"].dtype != np.uint8
            or saved_arrays["coverage"].dtype != np.bool_
            or saved_arrays["gltf_uv"].dtype != np.float32
            or not np.array_equal(saved_arrays["classification"], classification)
            or not np.array_equal(saved_arrays["coverage"], coverage)
            or not np.array_equal(saved_arrays["gltf_uv"], gltf_uv.astype(np.float32))
            or not np.array_equal(rgba[:, :, 3], coverage.astype(np.uint8) * 255)
            or np.any(rgba[~coverage] != 0)
        ):
            raise ValueError("Saved samples disagree with exact target-owned reconstruction.")
    rc = np.column_stack((yy, xx)).astype(np.int32)
    return {
        "classification": classification,
        "coverage": coverage,
        "texel_rows_columns": rc,
        "face_owner": face_owner,
        "barycentric": weights,
        "target_xyz": samples,
        "source_canonical_xyz": canonical,
        "region_bits": bits,
        "rejection_partition": rejection,
        "counts": region_counts(classification, rc, bits, rejection, tuple(regions or REGIONS)),
        "boxes": boxes,
        "depth_test_pairs": depth_pairs,
        "global_classification_counts": {
            key: int(np.count_nonzero(classification == code)) for key, code in REASONS.items()
        },
    }


def _indexed(rows, key="sample_id"):
    answer = {row[key]: row for row in rows}
    if len(answer) != len(rows):
        raise ValueError("Duplicate metadata record identifiers.")
    return answer


def select_targets(protocol, n0, registration, generated, reset):
    """Select only the protocol's twelve existing development conditions from N0."""
    if (
        protocol.get("protocol_id") != PROTOCOL_ID
        or protocol.get("schema_version") != 1
        or protocol["cohort"]["sources"] != COHORT
        or protocol["cohort"]["group"] != "development"
        or protocol["cohort"]["api_source_age"] != UNKNOWN_AGE
        or protocol["regions"] != REGIONS
        or protocol["regional_counting"]["padding_fraction"] != 0.25
        or protocol["observations"]["regional_support_results_seen_before_freeze"] is not False
        or protocol["quality_threshold"] is not None
        or protocol["flags"] != {"research_only": True, **dict.fromkeys(FALSE_FLAGS, False)}
    ):
        raise ValueError("Unsupported UV support protocol, cohort, semantics or flags.")
    cases, targets = _indexed(n0["bridge_cases"]), _indexed(registration["records"])
    fits, sources = _indexed(generated["fit_records"]), _indexed(reset["records"])
    held = [row for row in n0["adult_images"] if row["group"] != "development"]
    held_paths, held_hashes = {row["path"] for row in held}, {row["sha256"] for row in held}
    result = []
    for source_id, ages in COHORT.items():
        case, source, source_fit = cases[source_id], sources[source_id], fits[source_id]
        label = case["source_age"]["value"]
        if (
            case["group"] != "development"
            or case["source_status"] != "passed"
            or source["group"] != "development"
            or source["status"] != "ok"
            or source["source_age"] != UNKNOWN_AGE
            or source["input"] != case["source"]
            or source["subject_id"] != case["subject_id"]
            or source["label_source_age"] != label
            or source["research_source_age"] != case["source_age"]
            or source_fit["input"] != case["source"]
            or source_fit["role"] != "original"
            or source_fit["status"] != "ok"
            or source_fit["reference_source_id"] != source_id
            or source_fit["subject_id"] != case["subject_id"]
            or source_fit["source_age"] != label
            or source_fit["fit_artifact"] != source["fit_artifact"]
            or case["source"]["path"] in held_paths
            or case["source"]["sha256"] in held_hashes
        ):
            raise ValueError(
                "Original source identity, group, age or fit provenance differs from N0."
            )
        conditions = {}
        control = case["same_age_control"]
        if (
            control["status"] not in {"generated", "reused_existing"}
            or control["target_age"] != label
        ):
            raise ValueError("Every selected source needs its existing same-age control.")
        for run in [
            *case["target_runs"],
            {**control["output"], "target_age": control["target_age"]},
        ]:
            pin = {key: run[key] for key in ("path", "bytes", "sha256")}
            age = run["target_age"]
            if age in conditions and conditions[age] != pin:
                raise ValueError("Conflicting N0 target/control input pins.")
            conditions[age] = pin
        if set(conditions) != set(ages):
            raise ValueError("Selected source conditions differ from all four frozen N0 targets.")
        for age in ages:
            sample_id = f"{source_id}--sam-{age:03d}"
            row, fit = targets[sample_id], fits[sample_id]
            review = row["mask_review"]
            if (
                row["source_id"] != source_id
                or row["target_age"] != age
                or row["subject_id"] != case["subject_id"]
                or row["source_age_label"] != label
                or row["input"] != conditions[age]
                or row["status"] != "ok"
                or row["source_age"] != UNKNOWN_AGE
                or row["asset_mode"] != "static"
                or row["capabilities"] != {"age_morph": False, "age_texture": False}
                or row["source_frame"] != source["source_frame"]
                or fit["input"] != row["input"]
                or fit["fit_artifact"] != row["target_fit"]
                or fit["status"] != "ok"
                or fit["role"] != "sam_generated"
                or fit["subject_id"] != case["subject_id"]
                or fit["source_age"] != label
                or fit["reference_source_id"] != source_id
                or fit["target_age"] != age
                or fit.get("data_group", "development") != "development"
                or review["sample_id"] != sample_id
                or review["input"] != row["input"]
                or review["target_fit"] != row["target_fit"]
                or review["status"] != "reviewed_conservative_exclusion"
                or review["reviewer"] != "codex_visual_review"
                or review["automatic_external_occlusion_detection"] is not False
                or review["independent_mask_ground_truth"] is not False
                or row["sampling_geometry"] != "target_full_identity_expression_raw_fit"
                or row["input"]["path"] in held_paths
                or row["input"]["sha256"] in held_hashes
            ):
                raise ValueError(
                    "Target, own-fit, original frame or reviewed mask provenance differs."
                )
            result.append(
                {"registration": row, "fit": fit, "source": source, "source_fit": source_fit}
            )
    if len(result) != 12:
        raise ValueError("All twelve target requests must remain present.")
    return result


def derive_binary_pins(metadata):
    selected = select_targets(
        *(
            metadata[key]
            for key in (
                "protocol",
                "n0_manifest",
                "registration_report",
                "generated_report",
                "source_reset_report",
            )
        )
    )
    pins = {}
    for item in selected:
        row = item["registration"]
        values = [
            row["input"],
            row["target_fit"],
            item["source_fit"]["fit_artifact"],
            row["mask_review"]["allowed_mask"],
            row["mask_review"]["occluded_mask"],
        ]
        values.extend(
            row["artifacts"][name] for name in ("samples", "atlas", "classification", "coverage")
        )
        for value in values:
            pin = _pin(value)
            if pin["path"] in pins and pins[pin["path"]] != pin:
                raise ValueError("Conflicting derived binary pins.")
            pins[pin["path"]] = pin
    for pin in (
        metadata["generated_report"]["topology_artifact"],
        metadata["registration_report"]["inputs"]["uv"],
    ):
        pin = _pin(pin)
        pins[pin["path"]] = pin
    return list(pins.values())


def _topology(arrays, vertex_count):
    faces, coordinates = arrays["triangles"], arrays["keypoint_coordinates"]
    if (
        np.any(faces < 0)
        or np.any(faces >= vertex_count)
        or np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0)
        or np.any(coordinates < 0)
        or np.any(coordinates >= 3 * vertex_count)
    ):
        raise ValueError("Native ordered faces or sparse coordinate addresses are invalid.")
    digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for array in (
        np.array([vertex_count, len(faces)], dtype="<i8"),
        faces.astype("<i8"),
        coordinates.astype("<i8"),
    ):
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _fit(inputs, row, faces, topology_hash, count):
    arrays = safe_npz(inputs.read(row["fit_artifact"]), FIT_NAMES)
    if arrays["vertices"].dtype != np.float32 or arrays["vertices"].shape != (count, 3):
        raise ValueError("Saved full target geometry must preserve original float32 vertex order.")
    if (
        arrays["neutral_vertices"].shape != (count, 3)
        or row["topology_sha256"] != topology_hash
        or row["vertex_count"] != count
        or not np.array_equal(arrays["projection"], np.asarray(row["projection"]))
        or not np.array_equal(arrays["roi"], np.asarray(row["roi"]))
    ):
        raise ValueError("Fit arrays disagree with their topology, own projection or ROI metadata.")
    return TddfaResult(
        arrays["shape"],
        arrays["expr"],
        arrays["vertices"],
        faces,
        arrays["projection"],
        tuple(arrays["roi"].tolist()),
        topology_hash,
    )


def _source_frame(raw, frame, row):
    vertices = raw.vertices.astype(np.float64)
    extent = vertices.max(axis=0) - vertices.min(axis=0)
    center = vertices.min(axis=0) + extent / 2
    scale = 1 / float(extent[1]) if extent[1] > 0 else 0
    minimal = {
        "source_center": center.tolist(),
        "source_to_canonical_uniform_scale": scale,
        "normalization_reference": "unchanged_source_mesh",
    }
    if (
        row["canonical_frame"] != minimal
        or frame["source_center"] != center.tolist()
        or frame["source_to_canonical_uniform_scale"] != scale
        or frame["source_bbox_height"] != extent[1]
        or frame["source_topology_sha256"] != raw.topology_sha256
        or frame["vertex_order_preserved"] is not True
        or frame["face_order_preserved"] is not True
        or frame["winding"] != "source_face_a_b_c_to_a_c_b"
        or frame["axis_rotation_row_major"] != np.eye(3).reshape(-1).tolist()
        or frame["source_projection_row_major"] != raw.projection.reshape(-1).tolist()
        or frame["source_roi"] != list(raw.roi)
    ):
        raise ValueError("The immutable original bbox/canonical frame or native winding differs.")


def _record(inputs, item, uv, faces, coordinates, topology_hash, raster):
    row, fitrow = item["registration"], item["fit"]
    raw = _fit(inputs, fitrow, faces, topology_hash, len(uv))
    original = _fit(inputs, item["source_fit"], faces, topology_hash, len(uv))
    _source_frame(original, row["source_frame"], item["source_fit"])
    frame = row["source_frame"]
    canonical = (original.vertices.astype(np.float64) - frame["source_center"]) * frame[
        "source_to_canonical_uniform_scale"
    ]
    if (
        _digest(canonical.astype("<f4").tobytes()) != row["source_positions_sha256"]
        or _digest(faces[:, [0, 2, 1]].astype("<u4").tobytes()) != row["source_indices_sha256"]
    ):
        raise ValueError("Original canonical positions or reversed GLB index hashes differ.")
    if row["projection"] != fitrow["projection"] or row["roi"] != fitrow["roi"]:
        raise ValueError("Registration did not retain this target's own projection and ROI.")
    size = fitrow["image_size"]
    if list(_png_size(inputs.read(row["input"]))) != size:
        raise ValueError("Target input IHDR differs from its fit image frame.")
    masks = []
    for name in ("allowed_mask", "occluded_mask"):
        pixels = _png(inputs.read(row["mask_review"][name]), "L", size)
        if not np.isin(pixels, (0, 255)).all():
            raise ValueError("Reviewed masks must contain only 0 and 255.")
        masks.append(pixels == 255)
    if (
        int(masks[0].sum()) != row["mask_review"]["allowed_pixels"]
        or int(masks[1].sum()) != row["mask_review"]["excluded_occluder_pixels"]
    ):
        raise ValueError("Reviewed mask byte arrays differ from their saved counts.")
    landmarks = project_vertices(raw, coordinates)[:, :2].astype(np.float64)
    saved_landmarks = np.asarray(fitrow["projected_landmarks"], dtype=np.float64)
    if saved_landmarks.shape not in {(68, 2), (68, 3)} or not np.isfinite(saved_landmarks).all():
        raise ValueError("Saved target-own landmarks must contain 68 finite XY points.")
    residual = float(np.max(np.abs(landmarks - saved_landmarks[:, :2])))
    if residual > 0.001:
        raise ValueError("Target-own 68-landmark XY residual exceeds 0.001 pixel.")
    saved = safe_npz(inputs.read(row["artifacts"]["samples"]), SAMPLE_NAMES)
    for name, mode, expected in (
        ("atlas", "RGBA", saved["rgba"]),
        ("classification", "L", saved["classification"]),
        ("coverage", "L", saved["coverage"].astype(np.uint8) * 255),
    ):
        if not np.array_equal(
            _png(inputs.read(row["artifacts"][name]), mode, (256, 256)), expected
        ):
            raise ValueError("Saved PNG differs from its pinned NPZ array: " + name)
    trace = trace_support(
        raw, uv, *masks, landmarks, original.vertices, row["source_frame"], saved, raster=raster
    )
    if trace["global_classification_counts"] != row["texture_metadata"]["classification_counts"]:
        raise ValueError("Recomputed class partition differs from saved registration counts.")
    return trace, residual


def _output_path(root, value):
    path = Path(value)
    output = (path if path.is_absolute() else root / path).resolve()
    research = (root / "output" / "research").resolve()
    if root not in output.parents or research not in output.parents or output.exists():
        raise ValueError("Output must be a new directory strictly inside ignored output/research.")
    rules = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    if "output/" not in rules or any(line.startswith("!output") for line in rules):
        raise ValueError("The output ignore rule is absent or has unreviewed negation.")
    return output


def run(args):
    root = Path(args.root).resolve()
    output = _output_path(root, args.output_dir)
    plan_name = Path(args.study_plan)
    plan_path = (plan_name if plan_name.is_absolute() else root / plan_name).resolve()
    if root not in plan_path.parents:
        raise ValueError("Study plan must stay in this workspace.")
    with plan_path.open("rb") as stream:
        plan_bytes = stream.read(META_LIMIT + 1)
    if len(plan_bytes) > META_LIMIT:
        raise ValueError("Study plan exceeds the metadata bound.")
    plan, runtime = _json(plan_bytes), runtime_fingerprint()
    if (
        plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("schema_version") != 1
        or plan.get("runtime") != runtime
    ):
        raise ValueError("Plan protocol or pre-measurement runtime fingerprint differs.")
    inputs = Inputs(root, plan["inputs"])
    roles = plan["roles"]
    if set(roles) != set(ROLES):
        raise ValueError("Plan must declare exactly the eight required metadata/array roles.")
    metadata = {name: _json(inputs.read(roles[name], META_LIMIT)) for name in ROLES[:-2]}
    selected = select_targets(
        *(
            metadata[key]
            for key in (
                "protocol",
                "n0_manifest",
                "registration_report",
                "generated_report",
                "source_reset_report",
            )
        )
    )
    registration, generated, reset = (
        metadata[name]
        for name in (
            "registration_report",
            "generated_report",
            "source_reset_report",
        )
    )
    for report in (registration, generated, reset):
        if report["inputs"]["protocol_manifest"] != roles["n0_manifest"]:
            raise ValueError("Reports do not bind the exact selected N0 manifest.")
    if (
        registration["inputs"]["generated_report"] != roles["generated_report"]
        or reset["inputs"]["generated_report"] != roles["generated_report"]
        or generated["topology_artifact"] != roles["topology"]
        or registration["inputs"]["uv"] != roles["uv"]
        or reset["inputs"]["uv"] != roles["uv"]
    ):
        raise ValueError(
            "Report roles disagree about generated fits, native topology or common UV."
        )
    triage = metadata["triage"]
    if (
        triage.get("focus_source_id") != "fgnet-004a63"
        or roles["registration_report"] not in triage["inputs"]
        or roles["source_reset_report"] not in triage["inputs"]
        or any(
            triage.get(key) is not False
            for key in (
                "causal_cause_accepted",
                "new_inference",
                "service_ready",
                "production_enabled",
                "g3_complete",
            )
        )
    ):
        raise ValueError("Saved failure triage differs from selected reports or closed boundaries.")
    if any(item["registration"]["common_uv"] != roles["uv"] for item in selected):
        raise ValueError("Selected targets do not share the pinned original common UV binding.")
    required = (
        {pin["path"] for pin in derive_binary_pins(metadata)}
        | {roles[name]["path"] for name in ROLES}
        | set(SOURCES)
    )
    if not required <= inputs.pins.keys():
        raise ValueError(
            "Freeze omits selected binary evidence or loaded implementation/test sources."
        )
    if any(
        Path(name).suffix.lower() not in {".json", ".py", ".toml", ".lock", ".md"}
        for name in inputs.pins.keys() - required
    ):
        raise ValueError("The freeze includes arbitrary binary inputs outside the derived cohort.")
    for name in inputs.pins.keys() - {pin["path"] for pin in derive_binary_pins(metadata)}:
        inputs.read(inputs.pins[name], META_LIMIT)
    # Decode only after all metadata and source snapshots have been verified.
    shared_error = None
    try:
        topology = safe_npz(inputs.read(roles["topology"]), ("triangles", "keypoint_coordinates"))
        binding = safe_npz(inputs.read(roles["uv"]), ("uv", "topology_sha256"))
        uv, faces, coordinates = (
            binding["uv"],
            topology["triangles"],
            topology["keypoint_coordinates"],
        )
        topology_hash = _topology(topology, len(uv))
        if binding["topology_sha256"].item() != topology_hash:
            raise ValueError("Common UV differs from the ordered native topology fingerprint.")
        raster = prepare_uv(uv, faces)
    except (OSError, ValueError, KeyError, TypeError) as error:
        shared_error = error
    output.mkdir(parents=True, exist_ok=False)
    records, prepared = [], []
    for item in selected:
        row = item["registration"]
        record = {
            "sample_id": row["sample_id"],
            "source_id": row["source_id"],
            "target_age_condition": row["target_age"],
            "source_age_label": row["source_age_label"],
            "source_age": dict(UNKNOWN_AGE),
            "status": "failed",
        }
        try:
            if shared_error is not None:
                raise ValueError("Shared topology/UV unavailable: " + str(shared_error))
            trace, residual = _record(inputs, item, uv, faces, coordinates, topology_hash, raster)
            blob = io.BytesIO()
            np.savez_compressed(
                blob,
                **{
                    key: trace[key]
                    for key in (
                        "texel_rows_columns",
                        "face_owner",
                        "barycentric",
                        "target_xyz",
                        "source_canonical_xyz",
                        "region_bits",
                        "rejection_partition",
                    )
                },
            )
            relative = row["sample_id"] + "/correspondence.npz"
            prepared.append((relative, blob.getvalue()))
            record.update(
                status="ok",
                counts=trace["counts"],
                region_boxes_xyxy=trace["boxes"],
                global_classification_counts=trace["global_classification_counts"],
                landmark_xy_max_abs_residual_pixels=residual,
                classification_mismatches=0,
                gltf_uv_mismatches=0,
                source_frame_verified=True,
                depth_test_pairs=trace["depth_test_pairs"],
                correspondence={
                    "path": output.relative_to(root).as_posix() + "/" + relative,
                    "bytes": len(blob.getvalue()),
                    "sha256": _digest(blob.getvalue()),
                },
            )
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            record.update(
                error_code="UV_SUPPORT_FAILED", error_type=type(error).__name__, detail=str(error)
            )
        records.append(record)
        print(f"UV support {len(records)}/12: {row['sample_id']} {record['status']}", flush=True)
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **metadata["protocol"]["flags"],
        "study_plan": {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(plan_bytes),
            "sha256": _digest(plan_bytes),
        },
        "inputs": list(inputs.pins.values()),
        "roles": roles,
        "runtime": runtime,
        "classification_codes": REASONS,
        "region_bit_order": list(REGIONS),
        "rejection_partition_codes": REJECTION_CODES,
        "correspondence_semantics": {
            "texel_rows_columns": "zero-based UV raster row,column; center=(column+.5,row+.5)/256",
            "face_owner": "zero-based native ordered face index; no GLB winding reversal",
            "barycentric": "weights in native face vertex order a,b,c",
            "target_xyz": "target own projected continuous pixel XY and dense shifted relative Z",
            "source_canonical_xyz": "same owner/bary on original source and original bbox frame",
            "region_bits": "overlapping fitted XY boxes; regions are not a disjoint face partition",
            "rejection_partition": "0 outside visible mask rejection; positive contributors only",
        },
        "records": records,
        "summary": {
            "requested_targets": 12,
            "requested_sources": 3,
            "statuses": dict(Counter(row["status"] for row in records)),
            "all_requested_verified": all(row["status"] == "ok" for row in records),
        },
    }
    # Hold prepared vectors until a fresh audit, then audit again after writing.
    # Only paths created by this invocation can be removed upon invalidation.
    written = []

    def audit():
        inputs.recheck()
        with plan_path.open("rb") as stream:
            current_plan = stream.read(META_LIMIT + 1)
        if current_plan != plan_bytes or runtime_fingerprint() != runtime:
            raise ValueError("Study plan or runtime changed after calculation.")

    try:
        audit()
        for relative, data in prepared:
            path = output / relative
            path.parent.mkdir(exist_ok=False)
            with path.open("xb") as stream:
                stream.write(data)
            written.append(path)
        audit()
    except (OSError, ValueError) as error:
        for path in written:
            path.unlink()
            path.parent.rmdir()
        for row in records:
            for key in (
                "counts",
                "region_boxes_xyxy",
                "global_classification_counts",
                "landmark_xy_max_abs_residual_pixels",
                "classification_mismatches",
                "gltf_uv_mismatches",
                "source_frame_verified",
                "depth_test_pairs",
                "correspondence",
            ):
                row.pop(key, None)
            row.update(
                status="invalidated_input_drift", error_code="INPUT_DRIFT", detail=str(error)
            )
        report["summary"].update(
            statuses={"invalidated_input_drift": 12}, all_requested_verified=False
        )
        report["integrity"] = {"all_inputs_unchanged": False, "detail": str(error)}
    else:
        report["integrity"] = {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
            "verified_input_count": len(inputs.pins),
        }
    encoded = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode(
        "utf-8"
    )
    with (output / "report.json").open("xb") as stream:
        stream.write(encoded)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args)
        print(json.dumps(report["summary"], ensure_ascii=True))
        return 0 if report["summary"]["all_requested_verified"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
