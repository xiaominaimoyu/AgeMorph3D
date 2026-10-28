"""Run frozen K2 coefficient-derived neutral-geometry research, without inference."""

# Explicit standalone import paths for the existing local research environment.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend/src"))

import numpy as np
from agemorph3d.age_shape import load_age_direction
from agemorph3d.tddfa import _indices, _npz_arrays

from preprocessing.age_features import (
    _JsonInputs,
    _pin,
    _require,
    _workspace_path,
    build_feature_dataset,
)
from preprocessing.age_shape_baseline import run_baseline


def load_packet(reader, packet_pin):
    """Rebuild K1 from its seven bound JSON inputs; reject edits to the derived packet."""
    packet = reader.read(packet_pin)
    pins = packet["verified_json_inputs"]
    _require(len(pins) == 7, "K1 requires exactly seven verified JSON inputs.")
    docs = {p["path"]: reader.read(p) for p in pins}
    _require(len(docs) == 7, "Duplicate K1 input paths.")
    reports = [d for d in docs.values() if "fit_records" in d and d.get("study") == "calibration"]
    _require(len(reports) == 1, "Expected exactly one original calibration fit report.")
    report = reports[0]
    n0 = docs[report["inputs"]["protocol_manifest"]["path"]]
    freeze = docs[report["inputs"]["pre_inference_freeze"]["path"]]
    for role in ("protocol_manifest", "pre_inference_freeze"):
        declared = _pin(report["inputs"][role])
        _require(declared in pins, "K1 report input binding mismatch.")
    _require(
        _pin(n0["inputs"]["pre_inference_freeze"])
        == _pin(report["inputs"]["pre_inference_freeze"]),
        "K1 freeze binding mismatch.",
    )
    for name, p in n0["inputs"].items():
        if name != "pre_inference_freeze":
            _require(freeze["inputs"].get(p["path"]) == p["sha256"], "N0 freeze mismatch.")
    protocol_pin, dataset_pin = (n0["inputs"][k] for k in ("protocol", "dataset_manifest"))
    model_pins = {r: report["models"][r]["manifest"] for r in ("detector", "reconstructor")}
    for p in (protocol_pin, dataset_pin, *model_pins.values()):
        _require(_pin(p) in pins, "K1 metadata pin is not in its verified closure.")
    rebuilt = build_feature_dataset(
        report,
        n0,
        freeze,
        docs[protocol_pin["path"]],
        docs[dataset_pin["path"]],
        {r: docs[p["path"]] for r, p in model_pins.items()},
    )
    rebuilt["verified_json_inputs"] = sorted(pins, key=lambda p: p["path"])
    _require(rebuilt == packet, "K1 packet differs from its bound original requests/coefficients.")
    return packet


def samples_from_packet(packet):
    samples = []
    for i, row in enumerate(packet["records"]):
        j = row["feature_row_index"]
        label = row["research_age"]
        _require(
            label["kind"] == "exact", "Only exact research labels are supported by this experiment."
        )
        sample = {
            "sample_id": row["sample_id"],
            "subject_id": row["subject_id"],
            "group": row["group"],
            "age": label["value"],
            "status": row["fit_status"],
            "error_code": row["error_code"],
            "shape": None,
            "scale": None,
        }
        if row["fit_status"] == "ok":
            _require(packet["features"]["record_indices"][j] == i, "K1 feature index mismatch.")
            sample.update(
                shape=packet["features"]["shape"][j],
                scale=row["source_canonical_frame"]["source_to_canonical_uniform_scale"],
            )
        samples.append(sample)
    return samples


def verify_binary(root, pin, limit):
    p = _pin(pin)
    path = _workspace_path(root, p["path"])
    _require(path.suffix == ".npz" and p["bytes"] <= limit, "Expected bounded safe NPZ input.")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    _require(
        len(payload) == p["bytes"] and hashlib.sha256(payload).hexdigest() == p["sha256"],
        "Binary input fingerprint mismatch.",
    )
    return path


def geometry_metric(root, packet, direction_pin):
    binding = packet["binding"]
    bfm_pin = binding["models"]["reconstructor"]["artifacts"]["bfm"]
    path = verify_binary(root, bfm_pin, 64 * 1024 * 1024)
    arrays = _npz_arrays(path, ("w_shp", "tri", "keypoints"))
    count = binding["vertex_count"]
    basis = np.asarray(arrays["w_shp"])
    _require(
        basis.dtype.kind in "iuf"
        and basis.ndim == 2
        and basis.shape[0] == 3 * count
        and basis.shape[1] >= 40
        and np.isfinite(basis).all(),
        "Incompatible shape basis.",
    )
    triangles = _indices(arrays["tri"], "tri", count)
    coordinates = _indices(arrays["keypoints"], "keypoints", 3 * count)
    _require(
        triangles.ndim == 2 and triangles.shape[1] == 3 and coordinates.size == 204,
        "Invalid ordered topology.",
    )
    digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for a in (
        np.array([count, len(triangles)], dtype="<i8"),
        triangles.astype("<i8"),
        coordinates.reshape(68, 3).astype("<i8"),
    ):
        digest.update(a.tobytes(order="C"))
    _require(digest.hexdigest() == binding["topology_sha256"], "K1/BFM topology mismatch.")
    direction_path = verify_binary(root, direction_pin, 8 * 1024 * 1024)
    direction = load_age_direction(
        direction_path, direction_pin["sha256"], target_bfm_sha256=bfm_pin["sha256"]
    )
    _require(
        direction.topology_sha256 == binding["topology_sha256"]
        and direction.shape_direction.shape == (count, 3),
        "Mapped direction topology mismatch.",
    )
    combined = np.column_stack(
        (
            np.array(basis[:, :40], dtype=np.float64),
            direction.shape_direction.reshape(-1).astype(np.float64),
        )
    )
    gram = combined.T @ combined / count
    return gram, [bfm_pin, direction_pin]


def run(root, protocol_path, protocol_hash, output_dir):
    root = root.resolve()
    output = _workspace_path(root, output_dir)
    _require(
        root / "output" in output.parents and not output.exists(),
        "A fresh output/ directory is required.",
    )
    reader = _JsonInputs(root)
    path = _workspace_path(root, protocol_path)
    protocol = reader.read(
        {"path": protocol_path, "sha256": protocol_hash, "bytes": path.stat().st_size}
    )
    _require(
        protocol["protocol_id"] == "agemorph3d-age-shape-baseline-v1"
        and protocol["schema_version"] == 1,
        "Unsupported K2 protocol.",
    )
    packet = load_packet(reader, protocol["dataset"])
    samples = samples_from_packet(packet)
    cohort = protocol["cohort"]
    groups = {}
    for row in samples:
        groups.setdefault(row["subject_id"], []).append(row)
    pair_count = sum(
        sum(s["age"] != t["age"] for s in rows for t in rows) for rows in groups.values()
    )
    _require(
        len(samples) == cohort["requested"]
        and len(groups) == cohort["identities"]
        and sum(len({r["age"] for r in rows}) > 1 for rows in groups.values())
        == cohort["pair_eligible_identities"]
        and pair_count == cohort["directed_distinct_age_pairs"],
        "Frozen cohort count mismatch.",
    )
    gram, binary_pins = geometry_metric(root, packet, protocol["bfm_direction"])
    report = run_baseline(samples, gram, protocol["fit"]["relative_ridge_grid"])
    report.update(
        protocol_id=protocol["protocol_id"],
        geometry_definition=protocol["geometry"]["definition"],
        old_calibration_results_exposed=True,
        holdout_age_results_opened=False,
        verified_json_inputs=sorted(reader.pins.values(), key=lambda p: p["path"]),
        verified_binary_inputs=binary_pins,
        geometry_metric=gram.tolist(),
    )
    payload = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
    reader.recheck()
    for p in binary_pins:
        verify_binary(root, p, 64 * 1024 * 1024)
    output.mkdir(parents=True, exist_ok=False)
    destination = output / "report.json"
    try:
        destination.write_bytes(payload)
        reader.recheck()
        for p in binary_pins:
            verify_binary(root, p, 64 * 1024 * 1024)
    except BaseException:
        destination.unlink(missing_ok=True)
        output.rmdir()
        raise
    return {
        "path": destination.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "summaries": report["summaries"],
        "exploratory_preference": report["exploratory_preference"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.root, args.protocol, args.protocol_sha256, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError, IndexError, OverflowError) as error:
        print(f"K2 research refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
