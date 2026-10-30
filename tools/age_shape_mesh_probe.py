"""Replay frozen K2 folds as actual neutral static meshes, without refitting."""

# Explicit standalone research entry, using the existing optional backend environment.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import stat
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend/src"))

import numpy as np
from agemorph3d.age_geometry import in_source_frame
from agemorph3d.age_shape import load_age_direction
from agemorph3d.static_mesh import _encode_glb
from agemorph3d.tddfa import _indices, _npz_arrays

from preprocessing.age_features import _JsonInputs, _pin, _require, _workspace_path
from preprocessing.age_shape_baseline import ROUTES, anchored_coefficients, validate_samples
from tools.age_shape_baseline import (
    geometry_metric,
    load_packet,
    samples_from_packet,
    verify_binary,
)

PROTOCOL = "agemorph3d-age-shape-mesh-v1"
UNKNOWN = {"value": None, "method": "unknown", "calibration_id": None}
SELECTION = (
    "minimum_and_maximum_recorded_label_per_identity_both_directions_"
    "lexicographic_first_sample_on_ties_include_failed_extremes"
)
FLAGS = dict.fromkeys(
    (
        "refit_performed",
        "model_inference_run",
        "holdout_opened",
        "training_use",
        "years_calibrated",
        "identity_accepted",
        "quality_accepted",
        "service_ready",
        "production_enabled",
        "g3_complete",
    ),
    False,
)
SOURCES = (
    "tools/age_shape_mesh_probe.py",
    "tools/age_shape_baseline.py",
    "preprocessing/age_features.py",
    "preprocessing/age_shape_baseline.py",
    "backend/src/agemorph3d/age_geometry.py",
    "backend/src/agemorph3d/age_shape.py",
    "backend/src/agemorph3d/static_mesh.py",
    "backend/src/agemorph3d/tddfa.py",
)


def pin_file(root, path):
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def saved_report(root, pin):
    pin = _pin(pin)
    path = _workspace_path(root, pin["path"])
    _require(path.suffix == ".json" and pin["bytes"] <= 24 * 1024**2, "Bounded K2 JSON required.")
    with path.open("rb") as stream:
        raw = stream.read(24 * 1024**2 + 1)
    _require(
        len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
        "Saved K2 report fingerprint mismatch.",
    )

    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "Duplicate report field.")
            result[key] = value
        return result

    def number(value):
        result = float(value)
        _require(math.isfinite(result), "Nonfinite report value.")
        return result

    result = json.loads(raw, object_pairs_hook=unique, parse_float=number, parse_constant=number)
    _require(isinstance(result, dict), "K2 report must be an object.")
    return result


def extreme_pairs(samples):
    """Select from all recorded labels; failures never silently select another endpoint."""
    validate_samples(samples)
    groups = defaultdict(list)
    for row in samples:
        groups[row["subject_id"]].append(row)
    selected, skipped = [], []
    for subject, rows in sorted(groups.items()):
        ordered = sorted(rows, key=lambda r: (r["age"], r["sample_id"]))
        low = ordered[0]
        highest = max(r["age"] for r in rows)
        high = min((r for r in rows if r["age"] == highest), key=lambda r: r["sample_id"])
        if low["age"] == high["age"]:
            skipped.append(
                {
                    "subject_id": subject,
                    "reason": "SINGLE_RECORDED_AGE",
                    "sample_ids": sorted(r["sample_id"] for r in rows),
                }
            )
        else:
            selected.extend(
                [(low["sample_id"], high["sample_id"]), (high["sample_id"], low["sample_id"])]
            )
    return selected, skipped


def neutral_vertices(mean, basis, shape):
    mean, basis, shape = np.asarray(mean), np.asarray(basis), np.asarray(shape)
    _require(
        mean.dtype.kind in "fiu"
        and mean.ndim == 2
        and mean.shape[1] == 1
        and mean.size % 3 == 0
        and 3 <= mean.size // 3 <= 100_000,
        "Invalid bounded BFM mean.",
    )
    _require(
        basis.dtype.kind in "fiu"
        and basis.ndim == 2
        and basis.shape[0] == mean.size
        and basis.shape[1] >= 40
        and shape.dtype.kind in "fiu"
        and shape.shape == (40,),
        "Invalid BFM shape basis/coefficients.",
    )
    _require(all(np.isfinite(a).all() for a in (mean, basis, shape)), "Nonfinite neutral inputs.")
    raw = mean.astype(np.float64).reshape(-1) + basis[:, :40].astype(np.float64) @ shape.astype(
        np.float64
    )
    _require(np.isfinite(raw).all(), "Nonfinite neutral vertices.")
    return raw.reshape(-1, 3)


def encode_neutral(raw, raw_faces, frame, topology, source_id):
    _require(re.fullmatch(r"[0-9a-f]{64}", topology or "") is not None, "Invalid topology hash.")
    _require(re.fullmatch(r"[a-z0-9-]{1,100}", source_id or "") is not None, "Invalid source ID.")
    vertices = np.asarray(in_source_frame(raw, frame), dtype="<f4")
    _require(np.isfinite(vertices).all(), "Encoded positions overflow.")
    faces = np.asarray(raw_faces)
    _require(
        faces.dtype.kind in "iu"
        and faces.ndim == 2
        and faces.shape[1] == 3
        and 1 <= len(faces) <= 300_000
        and np.all(faces >= 0)
        and np.all(faces < len(vertices))
        and not np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0),
        "Invalid ordered triangles.",
    )
    triangles = np.array(faces[:, [0, 2, 1]], dtype="<u4")
    precise = vertices.astype(np.float64)
    face_normals = np.cross(
        precise[triangles[:, 1]] - precise[triangles[:, 0]],
        precise[triangles[:, 2]] - precise[triangles[:, 0]],
    )
    lengths = np.linalg.norm(face_normals, axis=1)
    _require(
        np.isfinite(lengths).all()
        and np.all(lengths > 1e-15)
        and float(face_normals[:, 2].sum()) > 0,
        "Degenerate or unsupported face winding.",
    )
    normals = np.zeros_like(precise)
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1)
    _require(
        np.isfinite(lengths).all() and np.all(lengths > 1e-15), "Unreferenced or degenerate vertex."
    )
    normals = np.asarray(normals / lengths[:, None], dtype="<f4")
    extras = {
        "asset_mode": "static",
        "source_age": UNKNOWN,
        "topology_id": "tddfa-bfm-canon-v1-" + topology,
        "coordinate_metadata": {
            **frame,
            "canonical_unit": "dimensionless",
            "metric_scale_verified": False,
            "expression": "neutral",
        },
        "research_age_shape": {
            "protocol_id": PROTOCOL,
            "source_id": source_id,
            "research_only": True,
            **FLAGS,
        },
    }
    return _encode_glb(vertices, normals, triangles, extras), vertices


def _output(root, relative):
    _require(
        isinstance(relative, str) and relative.startswith("output/research/"),
        "Use ignored research output.",
    )
    path = root
    for part in Path(relative).parts:
        _require(part not in {"", ".", ".."}, "Invalid output path.")
        path /= part
        if path.exists() or path.is_symlink():
            info = path.lstat()
            _require(
                not stat.S_ISLNK(info.st_mode)
                and not (
                    getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ),
                "Output links/reparse paths rejected.",
            )
    _require(not path.exists(), "Output must not exist.")
    return path


def publish(root, relative, files, recheck):
    output = _output(root, relative)
    _require(
        len(files) <= 130 and sum(map(len, files.values())) <= 256 * 1024**2,
        "Research output budget exceeded.",
    )
    _require(
        all(Path(n).name == n and n not in {"", ".", ".."} for n in files),
        "Flat filenames required.",
    )
    recheck()
    output.mkdir(parents=True, exist_ok=False)
    owned = []
    try:
        for name, raw in files.items():
            path = output / name
            with path.open("xb") as stream:
                owned.append(path)
                stream.write(raw)
        recheck()
    except BaseException:
        for path in reversed(owned):
            path.unlink()
        if not any(output.iterdir()):
            output.rmdir()
        raise


def run(root, protocol_path, protocol_hash, output):
    root = Path(root).resolve()
    source_pins = [pin_file(root, root / name) for name in SOURCES]
    _output(root, output)
    reader = _JsonInputs(root)
    protocol_file = _workspace_path(root, protocol_path)
    policy = reader.read(
        {"path": protocol_path, "bytes": protocol_file.stat().st_size, "sha256": protocol_hash}
    )
    _require(
        policy["protocol_id"] == PROTOCOL
        and policy["schema_version"] == 1
        and policy["selection"] == SELECTION
        and tuple(policy["routes"]) == ROUTES
        and policy["research_only"] is True
        and all(policy[k] is False for k in FLAGS),
        "Unsupported mesh replay policy.",
    )
    geometry = policy["geometry"]
    _require(
        geometry["endpoint_rtol"] == 1e-9
        and geometry["endpoint_atol"] == 1e-12
        and geometry["float32_rms_atol"] == 2e-7
        and geometry["numeric_tolerances_are_quality_thresholds"] is False,
        "Unsupported numeric tolerances.",
    )
    original_policy = reader.read(policy["upstream_protocol"])
    report = saved_report(root, policy["saved_report"])
    _require(
        report["protocol_id"] == original_policy["protocol_id"]
        and report["research_only"] is True
        and report["production_route_selected"] is None
        and report["holdout_age_results_opened"] is False,
        "Invalid saved research report.",
    )
    for p in report["verified_json_inputs"]:
        reader.read(p)
    packet = load_packet(reader, original_policy["dataset"])
    samples = samples_from_packet(packet)
    by_id = {s["sample_id"]: s for s in samples}
    records = {s["sample_id"]: s for s in packet["records"]}
    selected, skipped = extreme_pairs(samples)
    cohort = policy["cohort"]
    _require(
        len(samples) == cohort["requests"]
        and len({s["subject_id"] for s in samples}) == cohort["identities"]
        and len(selected)
        == cohort["selected_directed_pairs"]
        == 2 * cohort["pair_eligible_identities"],
        "Cohort/selection mismatch.",
    )
    gram, binaries = geometry_metric(root, packet, original_policy["bfm_direction"])
    _require(binaries == report["verified_binary_inputs"], "Binary report binding mismatch.")
    bfm_path = verify_binary(root, binaries[0], 64 * 1024**2)
    arrays = _npz_arrays(bfm_path, ("u", "w_shp", "tri"))
    count = packet["binding"]["vertex_count"]
    faces = _indices(arrays["tri"], "tri", count)
    direction = load_age_direction(
        verify_binary(root, binaries[1], 8 * 1024**2),
        binaries[1]["sha256"],
        target_bfm_sha256=binaries[0]["sha256"],
    ).shape_direction.astype(np.float64)
    raw = {
        s["sample_id"]: neutral_vertices(arrays["u"], arrays["w_shp"], s["shape"])
        for s in samples
        if s["status"] == "ok"
    }
    _require(all(len(v) == count for v in raw.values()), "BFM vertex count mismatch.")
    folds = {f["held_out_identity"]: f["model"] for f in report["outer_folds"]}
    _require(len(folds) == cohort["pair_eligible_identities"], "Outer fold count mismatch.")
    units = {}
    for subject, model in folds.items():
        if model is None:
            continue
        _require(
            set(model["training_identity_ids"]) == {s["subject_id"] for s in samples} - {subject},
            "Held-out identity entered its model.",
        )
        units[subject] = (
            arrays["w_shp"][:, :40].astype(np.float64) @ np.array(model["direction"])
        ).reshape(-1, 3)
    outcomes = report["outer_pair_outcomes"]
    expected = {
        (s["sample_id"], t["sample_id"], route)
        for s in samples
        for t in samples
        if s["subject_id"] == t["subject_id"] and s["age"] != t["age"]
        for route in ROUTES
    }
    _require(
        len(outcomes) == len(expected) == 3 * cohort["directed_pairs"],
        "Full request denominator mismatch.",
    )
    _require(
        {(r["source_id"], r["target_id"], r["route"]) for r in outcomes} == expected,
        "Missing/duplicate requests.",
    )
    files, assets, replay, selected_rows = {}, [], [], []
    selected_set = set(selected)
    reset_count = 0

    def add_mesh(name, vertices, source, role, target_id):
        encoded, positions = encode_neutral(
            vertices,
            faces,
            records[source]["source_canonical_frame"],
            packet["binding"]["topology_sha256"],
            source,
        )
        _require(name not in files, "Duplicate mesh artifact name.")
        files[name] = encoded
        asset = {
            "asset_id": name[:-4],
            "role": role,
            "source_id": source,
            "target_id": target_id,
            "source_age_api": UNKNOWN,
            "source_frame": records[source]["source_canonical_frame"],
            "topology_id": "tddfa-bfm-canon-v1-" + packet["binding"]["topology_sha256"],
            "artifact": {
                "path": output + "/" + name,
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            },
        }
        assets.append(asset)
        return asset, positions

    controls = {}
    for source, target in selected:
        s, t = by_id[source], by_id[target]
        _require(re.fullmatch(r"[a-z0-9-]{1,100}", target) is not None, "Invalid target ID.")
        if s["status"] != "ok" or t["status"] != "ok":
            continue
        original, positions = add_mesh(
            f"{source}--{target}--source.glb", raw[source], source, "neutral_source", target
        )
        reference, _ = add_mesh(
            f"{source}--{target}--reference.glb",
            raw[target],
            source,
            "reconstructed_neutral_target_reference",
            target,
        )
        controls[source, target] = original, reference, positions
        vector = np.r_[s["shape"], 0.0]
        for route in ROUTES:
            restored = anchored_coefficients(
                vector,
                s["age"],
                s["age"],
                folds[s["subject_id"]],
                gram,
                route=route,
                scale=s["scale"],
            )
            _require(restored is vector, "Same-age reset changed coefficient identity.")
            reset_glb, _ = encode_neutral(
                raw[source],
                faces,
                records[source]["source_canonical_frame"],
                packet["binding"]["topology_sha256"],
                source,
            )
            _require(
                reset_glb == files[Path(original["artifact"]["path"]).name],
                "Same-age GLB reset changed bytes.",
            )
            reset_count += 1
    for old in outcomes:
        source, target, route = old["source_id"], old["target_id"], old["route"]
        s, t = by_id[source], by_id[target]
        model = folds[s["subject_id"]]
        row = {
            k: old[k]
            for k in ("source_id", "target_id", "subject_id", "source_age", "target_age", "route")
        }
        _require(
            row["subject_id"] == s["subject_id"]
            and row["source_age"] == s["age"]
            and row["target_age"] == t["age"],
            "Outcome age/identity binding changed.",
        )
        try:
            if s["status"] != "ok" or t["status"] != "ok":
                raise ValueError("FIT_FAILED")
            if model is None and route != "no_change":
                raise ValueError("INSUFFICIENT_TRAINING_IDENTITIES")
            vector = np.r_[s["shape"], 0.0]
            anchored_coefficients(
                vector, s["age"], t["age"], model, gram, route=route, scale=s["scale"]
            )
            delta = t["age"] - s["age"]
            predicted = (
                raw[source]
                if route == "no_change"
                else raw[source]
                + delta
                * (
                    units[s["subject_id"]]
                    if route == "identity_centered_ridge"
                    else direction * model["bfm_strength_per_year"]
                )
            )
            endpoint = float(
                np.sqrt(np.mean(np.sum(((predicted - raw[target]) * s["scale"]) ** 2, axis=1)))
            )
            displacement = float(
                np.sqrt(np.mean(np.sum(((predicted - raw[source]) * s["scale"]) ** 2, axis=1)))
            )
            _require(
                old["status"] == "ok"
                and math.isclose(endpoint, old["endpoint_neutral_rms"], rel_tol=1e-9, abs_tol=1e-12)
                and math.isclose(
                    displacement, old["displacement_rms"], rel_tol=1e-9, abs_tol=1e-12
                ),
                "Actual vertex replay differs from saved Gram result.",
            )
            row.update(
                status="ok",
                error_code=None,
                vertex_endpoint_rms=endpoint,
                vertex_displacement_rms=displacement,
                saved_gram_endpoint_rms=old["endpoint_neutral_rms"],
            )
            if (source, target) in selected_set:
                original, reference, source_positions = controls[source, target]
                if route == "no_change":
                    mesh, positions = original, source_positions
                else:
                    mesh, positions = add_mesh(
                        f"{source}--{target}--{route}.glb", predicted, source, route, target
                    )
                target_positions = np.asarray(
                    in_source_frame(raw[target], records[source]["source_canonical_frame"]),
                    dtype="<f4",
                )
                encoded_rms = float(
                    np.sqrt(
                        np.mean(
                            np.sum((positions.astype(np.float64) - target_positions) ** 2, axis=1)
                        )
                    )
                )
                _require(
                    abs(encoded_rms - endpoint) <= 2e-7,
                    "Float32 mesh RMS differs beyond numeric tolerance.",
                )
                row.update(
                    mesh=mesh["artifact"],
                    source=original["artifact"],
                    reference=reference["artifact"],
                    float32_endpoint_rms=encoded_rms,
                )
        except ValueError as error:
            _require(
                old["status"] == "failed" and old["error_code"] == str(error),
                "Replay failure differs from saved failure.",
            )
            row.update(status="failed", error_code=str(error))
        replay.append(row)
        if (source, target) in selected_set:
            selected_rows.append(row)

    def recheck():
        reader.recheck()
        saved_report(root, policy["saved_report"])
        for p in binaries:
            verify_binary(root, p, 64 * 1024**2)
        _require(
            source_pins == [pin_file(root, root / n) for n in SOURCES],
            "Source drift during mesh replay.",
        )

    result = {
        "protocol_id": PROTOCOL,
        "status": "completed_mesh_replay_not_quality_acceptance",
        "research_only": True,
        **FLAGS,
        "protocol": reader.pins[protocol_path],
        "saved_report": policy["saved_report"],
        "verified_json_inputs": list(reader.pins.values()),
        "verified_binary_inputs": binaries,
        "producer_inputs": source_pins,
        "cohort": cohort,
        "records": packet["records"],
        "full_outcomes": replay,
        "full_counts": dict(Counter(r["status"] for r in replay)),
        "selected_pairs": selected,
        "single_age_identities": skipped,
        "selected_outcomes": selected_rows,
        "selected_counts": dict(Counter(r["status"] for r in selected_rows)),
        "same_age_exact_glb_resets": reset_count,
        "assets": assets,
        "mesh_count": len(assets),
        "geometry": geometry,
        "source_age_api": UNKNOWN,
        "references_are_ground_truth": False,
        "full_replay_is_independent_evaluation": False,
    }
    files["report.json"] = (
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode()
    publish(root, output, files, recheck)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = run(ROOT, args.protocol, args.protocol_sha256, args.output_dir)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        OverflowError,
        RecursionError,
    ) as error:
        print(
            json.dumps({"status": "invalid_input", "error": str(error), **FLAGS}), file=sys.stderr
        )
        return 2
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "full_counts",
                    "selected_counts",
                    "mesh_count",
                    "same_age_exact_glb_resets",
                    "g3_complete",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
