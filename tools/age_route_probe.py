"""Compare source-anchored age-shape candidates using frozen local research fits.

This tool loads only verified numeric assets. It performs no model inference,
downloads, training, holdout evaluation, or production capability changes.
"""

# Standalone offline entrypoint with the existing backend/tool imports.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "tools"))

import numpy as np
from age_protocol import _load, _path, _pin
from age_refit_probe import _jobs, _write_csv, _write_json
from agemorph3d.age_geometry import neutral_vertices, source_frame, vector_difference_metrics
from agemorph3d.age_routes import (
    anchored_bfm,
    anchored_sam,
    direction_observability,
    fit_bfm_scale,
)
from agemorph3d.age_shape import load_age_direction
from agemorph3d.age_statistics import aggregate_identity_metrics, longitudinal_pairs
from agemorph3d.tddfa import TddfaResult, _npz_arrays

_ROUTES = ("no_change", "bfm_calibrated", "sam_difference")
_METRICS = ["endpoint_neutral_rms", "displacement_rms", "identity_margin"]


def _verify_descendants(root: Path, value: object) -> None:
    if isinstance(value, dict):
        if {"path", "sha256", "bytes"} <= value.keys():
            _pin(root, _path(root, value["path"]), value["sha256"], value["bytes"])
        for item in value.values():
            _verify_descendants(root, item)
    elif isinstance(value, list):
        for item in value:
            _verify_descendants(root, item)


def _load_study(root: Path, report: dict, manifest: dict, study: str, basis: dict) -> tuple:
    """Bind every requested row to its frozen identity, image and ordered topology."""
    if report["study"] != study:
        raise ValueError("Study role does not match the requested comparison input.")
    jobs = {job["sample_id"]: job for job in _jobs(manifest, study)}
    records = {row["sample_id"]: row for row in report["fit_records"]}
    if len(records) != len(report["fit_records"]) or set(records) != set(jobs):
        raise ValueError("Study requests differ from the frozen identity-use manifest.")
    topology = _npz_arrays(
        _path(root, report["topology_artifact"]["path"]),
        ("triangles", "keypoint_coordinates"),
    )
    triangles = topology["triangles"]
    if not np.array_equal(triangles, basis["tri"]) or not np.array_equal(
        topology["keypoint_coordinates"].reshape(-1), basis["keypoints"].reshape(-1)
    ):
        raise ValueError("Study ordered topology differs from the verified BFM asset.")
    count = len(basis["w_exp"]) // 3
    digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for array in (
        np.array([count, len(triangles)], dtype="<i8"),
        triangles.astype("<i8"),
        topology["keypoint_coordinates"].astype("<i8"),
    ):
        digest.update(array.tobytes(order="C"))
    topology_hash = digest.hexdigest()
    fits, neutrals = {}, {}
    for sample_id, row in records.items():
        job = jobs[sample_id]
        for key in ("subject_id", "source_age", "role", "target_age", "reference_source_id"):
            if row.get(key) != job.get(key):
                raise ValueError("Fit identity, age or role differs from the frozen request.")
        if row.get("data_group", job["data_group"]) != job["data_group"]:
            raise ValueError("Fit data group differs from the frozen identity purpose.")
        if row["input"] != job["input"] or row["status"] not in {"ok", "failed"}:
            raise ValueError("Fit image or status differs from the frozen request.")
        if row["status"] == "failed":
            continue
        arrays = _npz_arrays(
            _path(root, row["fit_artifact"]["path"]),
            ("vertices", "neutral_vertices", "shape", "expr", "projection", "roi"),
        )
        if row["topology_sha256"] != topology_hash:
            raise ValueError("Fit topology fingerprint differs from its ordered arrays.")
        raw = TddfaResult(
            arrays["shape"],
            arrays["expr"],
            arrays["vertices"],
            triangles,
            arrays["projection"],
            tuple(arrays["roi"].tolist()),
            topology_hash,
        )
        neutral = neutral_vertices(raw, basis["w_exp"])
        if not np.array_equal(neutral, arrays["neutral_vertices"]):
            raise ValueError("Saved neutral vertices do not match the verified expression basis.")
        if row["role"] == "original" and row["canonical_frame"] != source_frame(raw.vertices):
            raise ValueError("Source canonical frame differs from the unchanged original.")
        fits[sample_id], neutrals[sample_id] = raw, neutral
    return jobs, records, fits, neutrals


def _expected_matches(manifest: dict) -> set:
    expected = set()
    for case in manifest["bridge_cases"]:
        source_age = case["source_age"]["value"]
        if source_age is None or case["source_status"] != "passed":
            continue
        if case["group"] != "development":
            raise ValueError("Viewed bridge identities must remain development-only.")
        for run in case["target_runs"]:
            age = run["target_age"]
            if age == source_age:
                continue
            for photo in manifest["adult_images"]:
                if (
                    photo["group"] == "development"
                    and photo["subject_id"] == case["subject_id"]
                    and photo["source_age"] == age
                ):
                    expected.add(
                        (
                            case["subject_id"],
                            case["sample_id"],
                            "fgnet-" + Path(photo["path"]).stem.lower(),
                            f"{case['sample_id']}--sam-{age:03d}",
                            f"{case['sample_id']}--sam-{int(source_age):03d}",
                            source_age,
                            age,
                        )
                    )
    return expected


def _match_signature(row: dict) -> tuple:
    return tuple(
        row[key]
        for key in (
            "subject_id",
            "source_id",
            "real_target_id",
            "generated_target_id",
            "same_age_id",
            "source_age",
            "target_age",
        )
    )


def _candidate(route, source, same, target, direction, calibration, basis, source_age, age):
    if route == "no_change":
        return source
    if route == "bfm_calibrated":
        return anchored_bfm(source, direction, calibration, source_age, age)
    return anchored_sam(source, same, target, basis, source_age, age)


def identity_geometry_proxy(candidate_neutral, genuine_neutral, impostors, frame) -> dict:
    """Actual endpoint distances; coefficient preservation cannot prove identity."""
    scale = frame["source_to_canonical_uniform_scale"]
    genuine = vector_difference_metrics((candidate_neutral - genuine_neutral) * scale)["rms"]
    distances = [
        (vector_difference_metrics((candidate_neutral - neutral) * scale)["rms"], sample_id)
        for sample_id, neutral in impostors.items()
    ]
    if not distances:
        return {"genuine_rms": genuine, "impostor_count": 0, "identity_margin": None}
    distance, sample_id = min(distances)
    return {
        "genuine_rms": genuine,
        "impostor_count": len(distances),
        "nearest_impostor_rms": distance,
        "nearest_impostor_id": sample_id,
        "identity_margin": distance - genuine,
    }


def _preserved(candidate: TddfaResult, source: TddfaResult) -> bool:
    return (
        candidate.topology_sha256 == source.topology_sha256
        and candidate.roi == source.roi
        and all(
            np.array_equal(getattr(candidate, key), getattr(source, key))
            for key in ("shape", "expr", "projection", "triangles")
        )
    )


def _grid(manifest, generated, direction, calibration, basis) -> tuple:
    rows, resets = [], []
    for case in manifest["bridge_cases"]:
        if case["source_status"] != "passed":
            continue
        sample_id, source_age = case["sample_id"], case["source_age"]["value"]
        source = generated.get(sample_id)
        for route in _ROUTES[1:]:
            if source_age is None:
                rows.append(
                    {
                        "sample_id": sample_id,
                        "subject_id": case["subject_id"],
                        "route": route,
                        "source_age": None,
                        "target_age": None,
                        "status": "failed",
                        "error_code": "SOURCE_AGE_UNKNOWN",
                    }
                )
                continue
            for age in sorted({20, 45, 70, source_age}):
                row = dict(
                    sample_id=sample_id,
                    subject_id=case["subject_id"],
                    route=route,
                    source_age=source_age,
                    target_age=age,
                    status="failed",
                )
                try:
                    if source is None:
                        raise ValueError("Original source fit is unavailable.")
                    result = _candidate(
                        route,
                        source,
                        generated.get(f"{sample_id}--sam-{int(source_age):03d}"),
                        generated.get(f"{sample_id}--sam-{int(age):03d}"),
                        direction,
                        calibration,
                        basis,
                        source_age,
                        age,
                    )
                    if not _preserved(result, source) or not np.isfinite(result.vertices).all():
                        raise ValueError("Candidate metadata or finite-geometry invariant failed.")
                    row.update(
                        status="ok",
                        displacement_rms=vector_difference_metrics(
                            (result.vertices.astype(np.float64) - source.vertices)
                            * source_frame(source.vertices)["source_to_canonical_uniform_scale"]
                        )["rms"],
                    )
                    if age == source_age:
                        exact = result is source and np.array_equal(
                            result.vertices, source.vertices
                        )
                        resets.append(
                            dict(
                                sample_id=sample_id,
                                route=route,
                                status="ok" if exact else "failed",
                                exact_reset=exact,
                            )
                        )
                        if not exact:
                            row.update(status="failed", error_code="SOURCE_RESET_FAILED")
                except ValueError as error:
                    outside = (
                        route == "bfm_calibrated"
                        and age != source_age
                        and not (
                            calibration["age_min"] <= source_age <= calibration["age_max"]
                            and calibration["age_min"] <= age <= calibration["age_max"]
                        )
                    )
                    row.update(
                        error_code="OUTSIDE_CALIBRATION_COVERAGE"
                        if outside
                        else "REQUEST_UNAVAILABLE",
                        reason=str(error),
                    )
                    if age == source_age:
                        resets.append(
                            dict(
                                sample_id=sample_id, route=route, status="failed", exact_reset=False
                            )
                        )
                rows.append(row)
    return rows, resets


def choose_route(
    records: list[dict],
    calibration: dict,
    resets: list[dict],
    expected: int,
    expected_reset_count: int = 8,
) -> dict:
    summaries = {
        route: aggregate_identity_metrics([r for r in records if r["route"] == route], _METRICS)
        for route in _ROUTES
    }
    baseline = summaries["no_change"]["macro"]["endpoint_neutral_rms"]["mean"]
    baseline_rows = [row for row in records if row["route"] == "no_change"]

    def pair_key(row):
        return (row["subject_id"], row["source_id"], row["real_target_id"])

    baseline_keys = {pair_key(row) for row in baseline_rows}
    baseline_complete = len(baseline_rows) == len(baseline_keys) == expected and all(
        row["status"] == "ok" and row.get("endpoint_neutral_rms") is not None
        for row in baseline_rows
    )
    folds = calibration["loio"]
    slopes = [float(fold["strength_per_year"]) for fold in folds if fold["status"] == "ok"]
    gates, eligible = {}, []
    for route in _ROUTES[1:]:
        own_resets = [row for row in resets if row["route"] == route]
        own = [row for row in records if row["route"] == route]
        sign = route != "bfm_calibrated" or (
            calibration["strength_per_year"] > 0
            and bool(slopes)
            and len(slopes) == len(folds)
            and all(beta > 0 for beta in slopes)
        )
        gate = (
            len(own) == expected
            and all(
                row["status"] == "ok" and row.get("endpoint_neutral_rms") is not None for row in own
            )
            and {pair_key(row) for row in own} == baseline_keys
            and baseline_complete
            and len(own_resets)
            == len({row["sample_id"] for row in own_resets})
            == expected_reset_count
            and all(row["exact_reset"] and row.get("status", "ok") == "ok" for row in own_resets)
            and sign
        )
        gates[route] = {
            "eligible": gate,
            "sign_gate": sign,
            "successful_matches": sum(row["status"] == "ok" for row in own),
            "exact_resets": sum(row["exact_reset"] for row in own_resets),
        }
        value = summaries[route]["macro"]["endpoint_neutral_rms"]["mean"]
        if (
            gate
            and baseline is not None
            and value is not None
            and value < baseline
            and not np.isclose(value, baseline, rtol=1e-12, atol=1e-15)
        ):
            eligible.append((value, route))
    eligible.sort()
    tied = len(eligible) >= 2 and np.isclose(eligible[0][0], eligible[1][0], rtol=1e-12, atol=1e-15)
    return {
        "research_route_choice": eligible[0][1] if eligible and not tied else "static_fallback",
        "reason": "Numerical tie between eligible candidates; prefer static fallback."
        if tied
        else "lowest eligible residual improves no-change"
        if eligible
        else "No eligible candidate improves the complete no-change baseline.",
        "gates": gates,
        "candidate_summaries": summaries,
        "production_route_selected": None,
        "identity_quality_accepted": False,
        "years_calibrated": False,
        "full_20_70_range_accepted": False,
    }


def _comparison_rows(manifest, matches, real, generated, direction, calibration, basis) -> tuple:
    real_jobs, real_records, real_fits, real_neutral = real
    generated_fits = generated[2]
    rows, outputs = [], {}
    for match in matches:
        source_id, subject = match["source_id"], match["subject_id"]
        source, truth = real_fits.get(source_id), real_neutral.get(match["real_target_id"])
        same, target = (
            generated_fits.get(match[key]) for key in ("same_age_id", "generated_target_id")
        )
        if (
            source is not None
            and source_id in generated_fits
            and not np.array_equal(source.vertices, generated_fits[source_id].vertices)
        ):
            raise ValueError("Original source fit differs between the two prior studies.")
        impostors = {
            sample_id: real_neutral[sample_id]
            for sample_id, job in real_jobs.items()
            if job["subject_id"] != subject
            and job["source_age"] == match["target_age"]
            and sample_id in real_neutral
        }
        pair_rows = []
        for route in _ROUTES:
            row = {
                key: match[key]
                for key in ("subject_id", "source_id", "real_target_id", "source_age", "target_age")
            }
            row.update(route=route, status="failed")
            try:
                if source is None or truth is None:
                    raise ValueError("Original or real exact-target fit is unavailable.")
                frame = source_frame(source.vertices)
                candidate = _candidate(
                    route,
                    source,
                    same,
                    target,
                    direction,
                    calibration,
                    basis,
                    match["source_age"],
                    match["target_age"],
                )
                if not _preserved(candidate, source):
                    raise ValueError(
                        "Candidate must preserve source expression, camera and topology."
                    )
                neutral = neutral_vertices(candidate, basis)
                proxy = identity_geometry_proxy(neutral, truth, impostors, frame)
                row.update(
                    status="ok",
                    source_frame=frame,
                    endpoint_neutral_rms=proxy["genuine_rms"],
                    displacement_rms=vector_difference_metrics(
                        (neutral - real_neutral[source_id])
                        * frame["source_to_canonical_uniform_scale"]
                    )["rms"],
                    identity_proxy=proxy,
                    identity_margin=proxy["identity_margin"],
                    preserved_source_metadata=True,
                    provenance={
                        "source": real_records[source_id]["fit_artifact"],
                        "real_target": real_records[match["real_target_id"]],
                        "impostor_references": [
                            {
                                "sample_id": sample_id,
                                "fit_artifact": real_records[sample_id]["fit_artifact"],
                                "rotation": real_records[sample_id].get("rotation"),
                                "image_size": real_records[sample_id].get("image_size"),
                                "projection_diagnostics": real_records[sample_id].get(
                                    "projection_diagnostics"
                                ),
                            }
                            for sample_id in sorted(impostors)
                        ],
                    },
                )
                name = f"candidates/{source_id}-to-{match['target_age']:03d}-{route}.npz"
                buffer = io.BytesIO()
                np.savez_compressed(
                    buffer,
                    vertices=candidate.vertices,
                    neutral_vertices=neutral,
                    source_center=np.asarray(frame["source_center"]),
                    source_scale=np.asarray(frame["source_to_canonical_uniform_scale"]),
                )
                outputs[name] = buffer.getvalue()
                row["output_name"] = name
            except ValueError as error:
                row.update(error_code="CANDIDATE_UNAVAILABLE", reason=str(error))
            rows.append(row)
            pair_rows.append(row)
        baseline = next(
            (row.get("identity_margin") for row in pair_rows if row["route"] == "no_change"), None
        )
        for row in pair_rows:
            margin = row.get("identity_margin")
            if margin is not None and baseline is not None:
                row["identity_margin_delta_vs_no_change"] = margin - baseline
    return rows, outputs


def _loio_geometry(jobs, fits, neutrals, direction, calibration, basis) -> list:
    folds = {fold["held_out_identity"]: fold for fold in calibration["loio"]}
    rows = []
    for pair in longitudinal_pairs(list(jobs.values())):
        row = dict(pair, status="failed")
        source, target = fits.get(pair["source_id"]), neutrals.get(pair["target_id"])
        fold = folds.get(pair["subject_id"])
        if source is None or target is None or fold is None or fold["status"] != "ok":
            row["error_code"] = "CALIBRATION_FIT_OR_FOLD_UNAVAILABLE"
            rows.append(row)
            continue
        frame = source_frame(source.vertices)
        scale = frame["source_to_canonical_uniform_scale"]
        outside = not (
            fold["train_age_min"] <= pair["source_age"] <= fold["train_age_max"]
            and fold["train_age_min"] <= pair["target_age"] <= fold["train_age_max"]
        )
        row.update(
            source_frame=frame,
            strength_per_year=fold["strength_per_year"],
            train_age_min=fold["train_age_min"],
            train_age_max=fold["train_age_max"],
            extrapolation_flag=outside,
            no_change_neutral_rms=vector_difference_metrics(
                (neutrals[pair["source_id"]] - target) * scale
            )["rms"],
        )
        try:
            result = anchored_bfm(
                source,
                direction,
                {
                    "strength_per_year": fold["strength_per_year"],
                    "age_min": fold["train_age_min"],
                    "age_max": fold["train_age_max"],
                },
                pair["source_age"],
                pair["target_age"],
            )
            row.update(
                status="ok",
                endpoint_neutral_rms=vector_difference_metrics(
                    (neutral_vertices(result, basis) - target) * scale
                )["rms"],
            )
        except ValueError as error:
            row.update(
                error_code="OUTSIDE_FOLD_COVERAGE" if outside else "LOIO_ROUTE_UNAVAILABLE",
                reason=str(error),
            )
        rows.append(row)
    return rows


def build_report(args) -> tuple[dict, dict]:
    """Verify frozen evidence before computing any calibration or route outcomes."""
    root = args.root
    protocol, manifest = _load(args.protocol), _load(args.protocol_manifest)
    if protocol["parent_protocol_id"] != manifest["protocol_id"]:
        raise ValueError("Shape protocol must bind the frozen parent evaluation protocol.")
    plan = _load(args.study_plan)
    if plan["protocol_id"] != protocol["protocol_id"]:
        raise ValueError("Study plan differs from the predeclared shape-comparison protocol.")
    frozen_inputs = dict(plan["inputs"])
    run_freeze = getattr(args, "run_freeze", None)
    if run_freeze is not None:
        for name, pin in _load(run_freeze)["inputs"].items():
            if name in frozen_inputs and any(
                frozen_inputs[name][key] != pin[key] for key in ("sha256", "bytes")
            ):
                raise ValueError("Pre-inference and pre-analysis freezes disagree on an input.")
            frozen_inputs[name] = pin
    required_frozen_paths = {
        args.protocol,
        args.protocol_manifest,
        args.direction,
        args.bfm,
        args.longitudinal_report,
        args.generated_report,
        args.matched_report,
    }
    if run_freeze is not None:
        required_frozen_paths.add(args.calibration_report)
    if not required_frozen_paths <= {_path(root, name) for name in frozen_inputs}:
        raise ValueError("Study plan must bind every supplied protocol and pre-existing input.")
    for name, pin in frozen_inputs.items():
        _pin(root, _path(root, name), pin["sha256"], pin["bytes"])
    _verify_descendants(root, manifest)
    paths = {
        "calibration": args.calibration_report,
        "longitudinal": args.longitudinal_report,
        "generated": args.generated_report,
        "matched": args.matched_report,
    }
    reports = {name: _load(path) for name, path in paths.items()}
    manifest_pin = _pin(root, args.protocol_manifest)
    for name, report in reports.items():
        _verify_descendants(root, report)
        if report["inputs"]["protocol_manifest"] != manifest_pin:
            raise ValueError("All studies must bind the identical frozen N0 manifest.")
        if name != "matched":
            for role in ("detector", "reconstructor"):
                if (
                    report["models"][role]["manifest_sha256"]
                    != reports["longitudinal"]["models"][role]["manifest_sha256"]
                ):
                    raise ValueError("Study model versions differ.")
    for name in ("longitudinal", "generated"):
        if reports["matched"]["inputs"][name + "_report"] != _pin(root, paths[name]):
            raise ValueError("Matched report does not bind the supplied source studies.")
    bfm_pin = _pin(root, args.bfm)
    for name in ("calibration", "longitudinal", "generated"):
        if reports[name]["expression_basis"]["asset"] != bfm_pin:
            raise ValueError("Study expression basis differs from the pinned BFM asset.")
    arrays = _npz_arrays(args.bfm, ("w_shp", "w_exp", "tri", "keypoints"))
    arrays["w_exp"] = arrays["w_exp"][:, :10]
    direction = load_age_direction(
        args.direction, args.direction_sha256, target_bfm_sha256=bfm_pin["sha256"]
    )
    studies = {
        name: _load_study(root, reports[name], manifest, name, arrays)
        for name in ("calibration", "longitudinal", "generated")
    }
    cal_jobs, cal_records, _, cal_neutral = studies["calibration"]
    expected = protocol["calibration"]
    if (
        len(cal_jobs) != expected["expected_images"]
        or len({j["subject_id"] for j in cal_jobs.values()}) != expected["expected_identities"]
    ):
        raise ValueError("Calibration cohort differs from the predeclared image/identity counts.")
    pair_count = len(longitudinal_pairs(list(cal_jobs.values())))
    pair_identities = {row["subject_id"] for row in longitudinal_pairs(list(cal_jobs.values()))}
    if (
        pair_count != expected["expected_directed_distinct_age_pairs"]
        or len(pair_identities) != expected["expected_distinct_age_pair_identities"]
    ):
        raise ValueError("Calibration distinct-age pairing differs from the preregistration.")
    successful_samples = [
        dict(job, group="calibration_research")
        for sample_id, job in cal_jobs.items()
        if sample_id in cal_neutral
    ]
    calibration = fit_bfm_scale(successful_samples, cal_neutral, direction.shape_direction)
    loio = _loio_geometry(
        cal_jobs, studies["calibration"][2], cal_neutral, direction, calibration, arrays["w_exp"]
    )
    matches = reports["matched"]["records"]
    if len(matches) != protocol["comparison"]["expected_exact_age_matches"] or {
        _match_signature(row) for row in matches
    } != _expected_matches(manifest):
        raise ValueError("Matched cohort must contain exact labels, not nearest-age substitutes.")
    comparisons, outputs = _comparison_rows(
        manifest,
        matches,
        studies["longitudinal"],
        studies["generated"],
        direction,
        calibration,
        arrays["w_exp"],
    )
    grid, resets = _grid(manifest, studies["generated"][2], direction, calibration, arrays["w_exp"])
    reset_count = sum(
        case["source_status"] == "passed" and case["source_age"]["value"] is not None
        for case in manifest["bridge_cases"]
    )
    selection = choose_route(comparisons, calibration, resets, len(matches), reset_count)
    report = {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "protocol_id": protocol["protocol_id"],
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "identity_quality_accepted": False,
        "years_calibrated": False,
        "full_20_70_range_accepted": False,
        "production_route_selected": None,
        "holdout_age_results_opened": False,
        "quality_thresholds_established": False,
        "independent_evaluation": False,
        "training": False,
        "new_sam_inference": False,
        "inputs": {
            "protocol": _pin(root, args.protocol),
            "protocol_manifest": manifest_pin,
            "study_plan": _pin(root, args.study_plan),
            "bfm": bfm_pin,
            "direction": _pin(root, args.direction, args.direction_sha256),
            **{name + "_report": _pin(root, path) for name, path in paths.items()},
        },
        "calibration": calibration,
        "calibration_requested_images": len(cal_jobs),
        "calibration_successful_images": len(successful_samples),
        "calibration_requested_pairs": pair_count,
        "calibration_request_statuses": dict(Counter(r["status"] for r in cal_records.values())),
        "calibration_failed_requests": [r for r in cal_records.values() if r["status"] != "ok"],
        "loio_comparisons": loio,
        "loio_geometry_summary": aggregate_identity_metrics(
            loio, ["endpoint_neutral_rms", "no_change_neutral_rms"]
        ),
        "loio_all_request_baseline": aggregate_identity_metrics(
            [
                dict(row, status="ok" if "no_change_neutral_rms" in row else "failed")
                for row in loio
            ],
            ["no_change_neutral_rms"],
        ),
        "direction_observability": direction_observability(
            direction.shape_direction, arrays["w_shp"][:, :40]
        ),
        "comparison_records": comparisons,
        "grid_records": grid,
        "reset_checks": resets,
        "selection": selection,
        "identity_proxy_limits": (
            "Unvalidated fitted-geometry distances to exact-age same/different-person development "
            "photos, not independent identity accuracy. Preserved coefficients are not "
            "acceptance evidence."
        ),
    }
    if run_freeze is not None:
        report["inputs"]["pre_analysis_freeze"] = _pin(root, run_freeze)
    return report, outputs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--protocol", default="docs/age-shape-comparison-v1.json")
    parser.add_argument(
        "--protocol-manifest",
        default="output/research/age-protocol-20261020/verified/manifest.json",
    )
    parser.add_argument(
        "--study-plan", default="output/research/age-stage3-20261021/study-plan.json"
    )
    parser.add_argument(
        "--run-freeze", default="output/research/age-stage3-20261021/run-freeze.json"
    )
    parser.add_argument("--calibration-report", required=True)
    parser.add_argument(
        "--longitudinal-report",
        default="output/research/age-stage2-20261020/longitudinal/report.json",
    )
    parser.add_argument(
        "--generated-report", default="output/research/age-stage2-20261020/generated/report.json"
    )
    parser.add_argument(
        "--matched-report", default="output/research/age-stage2-20261020/matched/report.json"
    )
    parser.add_argument("--direction", default="output/backend/b45/prepared-age/age_direction.npz")
    parser.add_argument(
        "--direction-sha256",
        default="e94e8f294a2a36264a6751eaffdcd4854f7587800de1ccde31d4969424850b5b",
    )
    parser.add_argument("--bfm", default="data/models/3ddfa-v2/bfm.npz")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    created = []
    try:
        for name in (
            "protocol",
            "protocol_manifest",
            "study_plan",
            "run_freeze",
            "calibration_report",
            "longitudinal_report",
            "generated_report",
            "matched_report",
            "direction",
            "bfm",
            "output_dir",
        ):
            setattr(args, name, _path(args.root, getattr(args, name)))
        if args.output_dir.exists():
            raise FileExistsError(
                "Output directory already exists; existing evidence is preserved."
            )
        report, outputs = build_report(args)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "candidates").mkdir()
        for name, payload in outputs.items():
            path = args.output_dir / name
            with path.open("xb") as stream:
                created.append(path)
                stream.write(payload)
        for row in report["comparison_records"]:
            if "output_name" in row:
                row["candidate_artifact"] = _pin(
                    args.root, args.output_dir / row.pop("output_name")
                )
        for name, value in (
            ("calibration.json", report["calibration"]),
            ("selection.json", report["selection"]),
        ):
            path = args.output_dir / name
            _write_json(path, value)
            created.append(path)
        for name, rows, columns in (
            (
                "comparisons.csv",
                report["comparison_records"],
                [
                    "subject_id",
                    "source_id",
                    "real_target_id",
                    "source_age",
                    "target_age",
                    "route",
                    "status",
                    "error_code",
                    *_METRICS,
                    "identity_margin_delta_vs_no_change",
                ],
            ),
            (
                "grid.csv",
                report["grid_records"],
                [
                    "sample_id",
                    "subject_id",
                    "route",
                    "source_age",
                    "target_age",
                    "status",
                    "error_code",
                    "reason",
                    "displacement_rms",
                ],
            ),
            (
                "loio.csv",
                report["loio_comparisons"],
                [
                    "subject_id",
                    "source_id",
                    "target_id",
                    "source_age",
                    "target_age",
                    "status",
                    "error_code",
                    "strength_per_year",
                    "train_age_min",
                    "train_age_max",
                    "extrapolation_flag",
                    "endpoint_neutral_rms",
                    "no_change_neutral_rms",
                ],
            ),
        ):
            path = args.output_dir / name
            _write_csv(path, rows, columns)
            created.append(path)
        report["output_artifacts"] = {
            path.name: _pin(args.root, path) for path in created if path.suffix != ".npz"
        }
        _write_json(args.output_dir / "report.json", report)
        created.append(args.output_dir / "report.json")
        print(json.dumps(report["selection"], ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        for path in created:
            path.unlink(missing_ok=True)
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
