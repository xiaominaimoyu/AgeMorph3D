"""Frozen saved-array support counts; never fill a target or run a model."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import math
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "_joint_uv_helpers", Path(__file__).with_name("uv_support_probe.py")
)
uv = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(uv)

PROTOCOL_ID = "agemorph3d-joint-uv-support-v1"
SOURCES = tuple(
    dict.fromkeys(
        (
            "tools/joint_uv_support_probe.py",
            "backend/tests/test_joint_uv_support_probe.py",
            *uv.SOURCES,
        )
    )
)
LOADED_CODE_SHA256 = {
    name: uv._digest((_ROOT / name).read_bytes()) for name in SOURCES if "/tests/" not in name
}
ROLES = (
    "protocol",
    "source_reset_report",
    "uv_report",
    "old_registration_report",
    "conservative_registration_report",
)
COHORT = uv.COHORT
REGIONS = tuple(uv.REGIONS)
STATES = ("both_known", "source_only", "target_only", "both_unknown")
REASONS = uv.REASONS
UNKNOWN_AGE = uv.UNKNOWN_AGE
FLAGS = {
    "research_only": True,
    **dict.fromkeys(
        (
            "real_model_inference",
            "masks_modified",
            "unknown_regions_filled",
            "source_fallback_enabled",
            "causal_cause_accepted",
            "independent_evaluation",
            "identity_quality_accepted",
            "age_quality_accepted",
            "visual_seam_quality_accepted",
            "legal_permission_established",
            "service_ready",
            "production_enabled",
            "g3_complete",
        ),
        False,
    ),
}
TRACE_NAMES = (
    "texel_rows_columns",
    "face_owner",
    "barycentric",
    "target_xyz",
    "source_canonical_xyz",
    "region_bits",
    "rejection_partition",
)


def _rgba(array):
    if (
        not isinstance(array, np.ndarray)
        or array.dtype != np.uint8
        or array.ndim != 3
        or array.shape[2] != 4
        or not 1 <= array.shape[0] <= 256
        or not 1 <= array.shape[1] <= 256
    ):
        raise ValueError("RGBA must be a bounded uint8 array.")
    alpha = array[:, :, 3]
    if not np.isin(alpha, (0, 255)).all() or np.any(array[alpha == 0] != 0):
        raise ValueError("Known alpha must be binary and unknown RGBA must be zero.")
    return alpha == 255


def joint_counts(source, target, classification, coverage, rc, region_bits):
    """Count four support states without altering or exporting any input pixels."""
    source_known, target_known = _rgba(source), _rgba(target)
    if (
        source.shape != target.shape
        or classification.dtype != np.uint8
        or classification.shape != source_known.shape
        or not np.isin(classification, tuple(REASONS.values())).all()
        or coverage.dtype != np.bool_
        or coverage.shape != source_known.shape
        or not np.array_equal(coverage, target_known)
        or not np.array_equal(coverage, classification == REASONS["sampled"])
    ):
        raise ValueError("Target classification, coverage and alpha disagree.")
    height, width = source_known.shape
    if (
        not isinstance(rc, np.ndarray)
        or rc.dtype != np.int32
        or rc.ndim != 2
        or rc.shape[1] != 2
        or len(rc) > height * width
        or np.any(rc < 0)
        or np.any(rc[:, 0] >= height)
        or np.any(rc[:, 1] >= width)
        or len(np.unique(rc[:, 0] * width + rc[:, 1])) != len(rc)
        or not isinstance(region_bits, np.ndarray)
        or region_bits.dtype != np.uint8
        or region_bits.shape != (len(rc),)
        or np.any(region_bits >= 1 << len(REGIONS))
    ):
        raise ValueError("Correspondence addresses or region bits are invalid.")
    domain = np.zeros((height, width), bool)
    domain[rc[:, 0], rc[:, 1]] = True
    if not np.array_equal(domain, classification >= REASONS["back_facing"]):
        raise ValueError("Correspondence does not cover exactly the unique-owned UV domain.")
    states = (
        source_known & target_known,
        source_known & ~target_known,
        ~source_known & target_known,
        ~source_known & ~target_known,
    )
    selections = {"all_atlas": np.ones_like(domain), "all_unique_correspondence": domain}
    for bit, name in enumerate(REGIONS):
        region = np.zeros_like(domain)
        region[rc[:, 0], rc[:, 1]] = region_bits & (1 << bit) != 0
        selections[name] = region
    answer = {}
    for name, selected in selections.items():
        count = int(selected.sum())
        values = {}
        for state, mask in zip(STATES, states, strict=True):
            chosen = selected & mask
            reasons = {
                key: int(np.count_nonzero(chosen & (classification == code)))
                for key, code in REASONS.items()
            }
            values[state] = {"count": int(chosen.sum()), "target_reasons": reasons}
            if sum(reasons.values()) != values[state]["count"]:
                raise ValueError("Target reasons do not partition the joint state.")
        if sum(item["count"] for item in values.values()) != count:
            raise ValueError("Joint states do not partition the region.")
        known = int(np.count_nonzero(selected & source_known))
        only = values["source_only"]["count"]
        answer[name] = {
            "requested": count,
            "source_known": known,
            "target_known": int(np.count_nonzero(selected & target_known)),
            "states": values,
            "source_only_fraction_of_source_known": only / known if known else None,
            "source_only_fraction_of_region": only / count if count else None,
        }
    return answer


def count_deltas(old, conservative):
    result = {}
    if old.keys() != conservative.keys():
        raise ValueError("Variant regions differ.")
    for name, before in old.items():
        after = conservative[name]
        if (
            before["requested"] != after["requested"]
            or before["source_known"] != after["source_known"]
        ):
            raise ValueError("Variants changed a denominator or original source support.")
        result[name] = {
            "requested": before["requested"],
            "states": {
                state: {
                    "count": after["states"][state]["count"] - before["states"][state]["count"],
                    "target_reasons": {
                        reason: after["states"][state]["target_reasons"][reason]
                        - before["states"][state]["target_reasons"][reason]
                        for reason in REASONS
                    },
                }
                for state in STATES
            },
        }
    return result


def _index(report, key):
    rows = report.get("records")
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("Report records must be a bounded list.")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or row[key] in result:
            raise ValueError("Report record identifiers are absent or duplicated.")
        result[row[key]] = row
    return result


def select_records(metadata, roles):
    """Bind saved arrays to prior reports without opening a raw image or model."""
    protocol = metadata["protocol"]
    if (
        protocol.get("protocol_id") != PROTOCOL_ID
        or protocol.get("schema_version") != 1
        or protocol.get("cohort") != COHORT
        or protocol.get("variants") != ["old", "conservative"]
        or protocol.get("expected_records") != 24
        or protocol.get("flags") != FLAGS
    ):
        raise ValueError("Unsupported joint-support protocol or capability flags.")
    original, traced, old, new = (metadata[key] for key in ROLES[1:])
    if (
        traced.get("protocol_id") != uv.PROTOCOL_ID
        or traced.get("classification_codes") != REASONS
        or traced.get("region_bit_order") != list(REGIONS)
        or traced.get("roles", {}).get("registration_report") != roles["old_registration_report"]
        or traced.get("roles", {}).get("source_reset_report") != roles["source_reset_report"]
    ):
        raise ValueError("Correspondence provenance differs from the selected historical reports.")
    for report in (original, traced, old, new):
        if (
            report.get("research_only") is not True
            or report.get("g3_complete") is not False
            or report.get("service_ready") is not False
        ):
            raise ValueError("Historical research boundaries are not closed.")
    for key in ("uv", "generated_report", "protocol_manifest"):
        if not old["inputs"][key] == new["inputs"][key] == original["inputs"][key]:
            raise ValueError("Historical reports disagree on source inputs or UV binding.")
    sources, traces, prior, revised = (
        _index(report, "sample_id") for report in (original, traced, old, new)
    )
    selected = []
    for source_id, conditions in COHORT.items():
        source = sources[source_id]
        if (
            source.get("status") != "ok"
            or source.get("group") != "development"
            or source.get("source_age") != UNKNOWN_AGE
        ):
            raise ValueError("Source is not an eligible development original with unknown API age.")
        for condition in conditions:
            sample = f"{source_id}--sam-{condition:03d}"
            trace, a, b = traces[sample], prior[sample], revised[sample]
            if (
                trace.get("source_id") != source_id
                or trace.get("target_age_condition") != condition
                or trace.get("status") != "ok"
                or trace.get("source_age") != UNKNOWN_AGE
                or trace.get("source_frame_verified") is not True
                or trace.get("classification_mismatches") != 0
                or trace.get("gltf_uv_mismatches") != 0
            ):
                raise ValueError("Correspondence selection or verified shared frame differs.")
            for row in (a, b):
                texture, source_texture = row["texture_metadata"], source["texture_metadata"]
                if (
                    row.get("source_id") != source_id
                    or row.get("target_age") != condition
                    or row.get("subject_id") != source.get("subject_id")
                    or row.get("status") != "ok"
                    or row.get("source_age") != UNKNOWN_AGE
                    or row.get("source_frame") != source["source_frame"]
                    or row.get("common_uv") != old["inputs"]["uv"]
                    or row.get("sampling_geometry") != "target_full_identity_expression_raw_fit"
                    or row.get("capabilities") != {"age_morph": False, "age_texture": False}
                    or texture.get("classification_codes") != REASONS
                    or any(
                        texture.get(key) != source_texture.get(key)
                        for key in (
                            "uv_array_sha256",
                            "atlas_size",
                            "input_uv_origin",
                            "gltf_uv_origin",
                            "uv_transform",
                            "atlas_texel_sample",
                        )
                    )
                    or texture.get("atlas_size") != 256
                    or not isinstance(source_texture.get("uv_array_sha256"), str)
                    or uv.re.fullmatch(r"[0-9a-f]{64}", source_texture["uv_array_sha256"]) is None
                    or any(
                        not isinstance(source_texture.get(key), str) or not source_texture[key]
                        for key in (
                            "input_uv_origin",
                            "gltf_uv_origin",
                            "uv_transform",
                            "atlas_texel_sample",
                        )
                    )
                ):
                    raise ValueError("Target/source mapping, original frame or common UV differs.")
            if any(
                a[key] != b[key]
                for key in (
                    "input",
                    "target_fit",
                    "projection",
                    "roi",
                    "gltf_uv_sha256",
                    "source_positions_sha256",
                    "source_normals_sha256",
                    "source_indices_sha256",
                )
            ):
                raise ValueError("Conservative variant changed its target-owned projection or UV.")
            if (
                trace["source_age_label"] != a["source_age_label"]
                or a["source_age_label"] != b["source_age_label"]
                or a["source_age_label"] != source["label_source_age"]
            ):
                raise ValueError("Research labels differ across saved records.")
            selected.append({"source": source, "trace": trace, "old": a, "conservative": b})
    return selected


def derive_binary_pins(selected):
    pins = {}
    for item in selected:
        values = (
            item["source"]["artifacts"]["atlas"],
            item["trace"]["correspondence"],
            *(item[name]["artifacts"]["samples"] for name in ("old", "conservative")),
        )
        for value in values:
            pin = uv._pin(value)
            if pin["path"] in pins and pins[pin["path"]] != pin:
                raise ValueError("Conflicting derived binary pins.")
            pins[pin["path"]] = pin
    return list(pins.values())


def trace_npz(data):
    """Reject oversized or unexpected NPY headers before NumPy allocation."""
    if not isinstance(data, bytes) or len(data) > uv.BINARY_LIMIT:
        raise ValueError("Correspondence compressed byte bound exceeded.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if (
                len(entries) != len(TRACE_NAMES)
                or {e.filename for e in entries} != {n + ".npy" for n in TRACE_NAMES}
                or any(e.flag_bits & 1 or e.file_size > uv.UNPACKED_LIMIT for e in entries)
                or sum(e.file_size for e in entries) > uv.UNPACKED_LIMIT
            ):
                raise ValueError("Correspondence archive names or expanded bounds differ.")
            count = None
            for entry in entries:
                name = entry.filename[:-4]
                with archive.open(entry) as stream:
                    version = np.lib.format.read_magic(stream)
                    reader = {
                        (1, 0): np.lib.format.read_array_header_1_0,
                        (2, 0): np.lib.format.read_array_header_2_0,
                    }.get(version)
                    if reader is None:
                        raise ValueError("Unsupported NPY header version.")
                    shape, _, dtype = reader(stream)
                    if not shape or not 0 <= shape[0] <= 65536:
                        raise ValueError("Correspondence row budget exceeded.")
                    count = shape[0] if count is None else count
                    expected_shape = (
                        (count, 2)
                        if name == "texel_rows_columns"
                        else (count, 3)
                        if name in {"barycentric", "target_xyz", "source_canonical_xyz"}
                        else (count,)
                    )
                    expected_dtype = (
                        np.dtype("int32")
                        if name in {"texel_rows_columns", "face_owner"}
                        else np.dtype("float64")
                        if len(expected_shape) == 2 and name != "texel_rows_columns"
                        else np.dtype("uint8")
                    )
                    if (
                        shape != expected_shape
                        or dtype != expected_dtype
                        or math.prod(shape) * dtype.itemsize + stream.tell() != entry.file_size
                    ):
                        raise ValueError("Correspondence shape, dtype or byte length differs.")
        with np.load(io.BytesIO(data), allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in TRACE_NAMES}
        if (
            any(not np.isfinite(a).all() for a in arrays.values())
            or np.any(arrays["face_owner"] < 0)
            or np.any(arrays["face_owner"] >= 300000)
            or np.any(arrays["rejection_partition"] > 3)
            or np.any(arrays["barycentric"] < -1e-10)
            or np.any(arrays["barycentric"] > 1 + 2e-10)
            or np.any(np.abs(arrays["barycentric"].sum(axis=1) - 1) > 1e-10)
        ):
            raise ValueError("Correspondence numeric values are invalid.")
        return arrays
    except (zipfile.BadZipFile, EOFError, OverflowError) as error:
        raise ValueError("Malformed correspondence archive.") from error


def _variant_check(before, after, source_id):
    if not np.array_equal(before["gltf_uv"], after["gltf_uv"]):
        raise ValueError("Variant UV arrays differ.")
    changed = before["classification"] != after["classification"]
    if (
        np.any(changed)
        and source_id != "fgnet-004a63"
        or np.any(before["classification"][changed] != REASONS["mask_rejected"])
        or np.any(after["classification"][changed] != REASONS["sampled"])
        or not np.array_equal(before["rgba"][~changed], after["rgba"][~changed])
    ):
        raise ValueError("Conservative variant changed more than its class5-to-class6 candidates.")
    return int(changed.sum())


def _old_counts_check(counts, trace):
    if set(trace["counts"]) != {"all_unique_correspondence", *REGIONS}:
        raise ValueError("Prior UV diagnostic omits a required regional denominator.")
    for name, recorded in trace["counts"].items():
        actual = counts[name]
        classification = {
            reason: sum(state["target_reasons"][reason] for state in actual["states"].values())
            for reason in REASONS
        }
        if (
            actual["requested"] != recorded["requested"]
            or classification != recorded["classification_counts"]
        ):
            raise ValueError("Saved old regional counts differ from the prior UV diagnostic.")
    actual = counts["all_atlas"]
    if {
        reason: sum(state["target_reasons"][reason] for state in actual["states"].values())
        for reason in REASONS
    } != trace["global_classification_counts"]:
        raise ValueError("Saved old global counts differ from the prior UV diagnostic.")


def recheck_inputs(inputs):
    """A changed file cannot turn the final hash pass into an unbounded scan."""
    for pin in inputs.pins.values():
        path = uv._relative(inputs.root, pin["path"])
        size, digest = 0, uv.hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                block = stream.read(min(1024**2, pin["bytes"] + 1 - size))
                if not block:
                    break
                size += len(block)
                if size > pin["bytes"]:
                    raise ValueError("Input drift after calculation: " + pin["path"])
                digest.update(block)
        if size != pin["bytes"] or digest.hexdigest() != pin["sha256"]:
            raise ValueError("Input drift after calculation: " + pin["path"])


def run(args):
    root = Path(args.root).resolve()
    output = uv._output_path(root, args.output_dir)
    plan_path = Path(args.study_plan)
    plan_path = (plan_path if plan_path.is_absolute() else root / plan_path).resolve()
    if root not in plan_path.parents:
        raise ValueError("Study plan must stay in the workspace.")
    with plan_path.open("rb") as stream:
        plan_bytes = stream.read(uv.META_LIMIT + 1)
    if len(plan_bytes) > uv.META_LIMIT:
        raise ValueError("Study plan exceeds its metadata bound.")
    plan, runtime = uv._json(plan_bytes), uv.runtime_fingerprint()
    if (
        plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("schema_version") != 1
        or plan.get("runtime") != runtime
    ):
        raise ValueError("Plan protocol or frozen runtime differs.")
    inputs, roles = uv.Inputs(root, plan["inputs"]), plan["roles"]
    if set(roles) != set(ROLES):
        raise ValueError("Plan must contain exactly five metadata roles.")
    metadata = {name: uv._json(inputs.read(roles[name], uv.META_LIMIT)) for name in ROLES}
    selected = select_records(metadata, roles)
    binaries = {pin["path"] for pin in derive_binary_pins(selected)}
    required = binaries | {pin["path"] for pin in roles.values()} | set(SOURCES) | {".gitignore"}
    if set(inputs.pins) != required:
        raise ValueError("Freeze omits required evidence/code or adds unrelated binary inputs.")
    if any(inputs.pins[name]["sha256"] != digest for name, digest in LOADED_CODE_SHA256.items()):
        raise ValueError("Frozen implementation differs from the code loaded in this process.")
    for name in inputs.pins.keys() - binaries:
        inputs.read(inputs.pins[name], uv.META_LIMIT)
    records, deltas = [], []
    for item in selected:
        source_id = item["old"]["source_id"]
        source = uv._png(inputs.read(item["source"]["artifacts"]["atlas"]), "RGBA", (256, 256))
        if (
            int(_rgba(source).sum()) != item["source"]["texture_metadata"]["observed_texels"]
            or uv._digest(source.tobytes()) != item["source"]["rgba_sha256"]
        ):
            raise ValueError("Original source alpha differs from its observed support metadata.")
        trace = trace_npz(inputs.read(item["trace"]["correspondence"]))
        variants = {
            name: uv.safe_npz(inputs.read(item[name]["artifacts"]["samples"]), uv.SAMPLE_NAMES)
            for name in ("old", "conservative")
        }
        changed = _variant_check(variants["old"], variants["conservative"], source_id)
        rc = trace["texel_rows_columns"]
        # Validate addresses before indexing the old classification below.
        original_counts = joint_counts(
            source,
            variants["old"]["rgba"],
            variants["old"]["classification"],
            variants["old"]["coverage"],
            rc,
            trace["region_bits"],
        )
        if not np.array_equal(
            trace["rejection_partition"] > 0,
            variants["old"]["classification"][rc[:, 0], rc[:, 1]] == REASONS["mask_rejected"],
        ):
            raise ValueError("Saved rejection partition differs from old mask-rejected texels.")
        counted = {}
        for name, arrays in variants.items():
            if (
                np.any(arrays["gltf_uv"] < 0)
                or np.any(arrays["gltf_uv"] > 1)
                or uv._digest(arrays["gltf_uv"].astype("<f4").tobytes())
                != item[name]["gltf_uv_sha256"]
            ):
                raise ValueError("Saved glTF UV differs from its registration hash or bounds.")
            counted[name] = (
                original_counts
                if name == "old"
                else joint_counts(
                    source,
                    arrays["rgba"],
                    arrays["classification"],
                    arrays["coverage"],
                    trace["texel_rows_columns"],
                    trace["region_bits"],
                )
            )
            if {
                reason: int(np.count_nonzero(arrays["classification"] == code))
                for reason, code in REASONS.items()
            } != item[name]["texture_metadata"]["classification_counts"]:
                raise ValueError("Target saved classes differ from registration metadata.")
            records.append(
                {
                    "sample_id": item[name]["sample_id"],
                    "source_id": source_id,
                    "target_age_condition": item[name]["target_age"],
                    "source_age": dict(UNKNOWN_AGE),
                    "variant": name,
                    "status": "ok",
                    "counts": counted[name],
                }
            )
        _old_counts_check(counted["old"], item["trace"])
        deltas.append(
            {
                "sample_id": item["old"]["sample_id"],
                "source_id": source_id,
                "new_sampled_texels": changed,
                "counts": count_deltas(counted["old"], counted["conservative"]),
            }
        )

    def audit():
        recheck_inputs(inputs)
        with plan_path.open("rb") as stream:
            current = stream.read(uv.META_LIMIT + 1)
        if current != plan_bytes or uv.runtime_fingerprint() != runtime:
            raise ValueError("Plan or runtime drift after calculation.")

    audit()
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **FLAGS,
        "study_plan": {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(plan_bytes),
            "sha256": uv._digest(plan_bytes),
        },
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "classification_codes": REASONS,
        "region_bit_order": list(REGIONS),
        "records": records,
        "deltas": deltas,
        "summary": {
            "requested_targets": 12,
            "requested_variants": 24,
            "records_verified": len(records),
            "all_requested_verified": len(records) == 24,
        },
        "integrity": {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
        },
    }
    output.mkdir(parents=True, exist_ok=False)
    pending = output / "pending-report.json"
    try:
        with pending.open("xb") as stream:
            stream.write(
                (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode(
                    "utf-8"
                )
            )
        audit()
        pending.rename(output / "report.json")
    except BaseException:
        pending.unlink(missing_ok=True)
        if not any(output.iterdir()):
            output.rmdir()
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    try:
        report = run(parser.parse_args(argv))
        print(json.dumps(report["summary"]))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
