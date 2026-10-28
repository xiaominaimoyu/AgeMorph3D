"""Nested identity validation of a source-anchored research shape direction.

The 41-dimensional Gram metric represents shape40 plus a full BFM direction.
This module neither loads models nor enables production capabilities.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np

ROUTES = ("no_change", "bfm_direction_refit", "identity_centered_ridge")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _array(value, shape):
    original = np.asarray(value)
    if original.dtype.kind not in "iuf" or original.shape != shape:
        raise ValueError("Invalid finite real coefficient array.")
    result = np.array(original, dtype=np.float64, copy=True)
    if not np.isfinite(result).all():
        raise ValueError("Invalid finite real coefficient array.")
    return result


def _age(value):
    if not _finite(value) or not 20 <= value <= 70:
        raise ValueError("Known finite source/target age within 20-70 required.")
    return value


def validate_samples(samples):
    if not isinstance(samples, list) or not 1 <= len(samples) <= 5000:
        raise ValueError("A bounded complete research sample list is required.")
    seen = set()
    for row in samples:
        name, subject = row["sample_id"], row["subject_id"]
        if (
            not isinstance(name, str)
            or not name
            or name in seen
            or not isinstance(subject, str)
            or not subject
        ):
            raise ValueError("Sample IDs must be unique and subject IDs nonempty.")
        seen.add(name)
        if row.get("group") != "calibration_research":
            raise ValueError("Only the frozen calibration research group is supported.")
        _age(row["age"])
        if row["status"] == "ok":
            _array(row["shape"], (40,))
            if not _finite(row["scale"]) or row["scale"] <= 0:
                raise ValueError("Original source canonical scale must be positive.")
        elif row["status"] != "failed" or not row.get("error_code") or row.get("shape") is not None:
            raise ValueError("Failures must be retained without imputed coefficients.")


def validate_metric(gram):
    g = _array(gram, (41, 41))
    if not np.allclose(g, g.T, rtol=1e-12, atol=1e-15):
        raise ValueError("Geometry metric must be symmetric.")
    magnitude = max(float(np.max(np.abs(g))), 1e-30)
    if float(np.linalg.eigvalsh(g)[0]) < -1e-10 * magnitude or g[-1, -1] <= 0:
        raise ValueError(
            "Geometry metric must be positive semidefinite with a nonzero BFM direction."
        )
    return g


def metric_rms(vector, gram, scale=1.0):
    v = _array(vector, (41,))
    squared = float(v @ gram @ v)
    bound = float(np.linalg.norm(v) ** 2 * np.max(np.abs(gram)))
    if not math.isfinite(squared) or squared < -1e-10 * max(bound, 1e-30):
        raise ValueError("Geometry residual is not finite nonnegative.")
    return math.sqrt(max(0.0, squared)) * scale


def _groups(samples, successful_only=False):
    grouped = defaultdict(list)
    for row in samples:
        if not successful_only or row["status"] == "ok":
            grouped[row["subject_id"]].append(row)
    return dict(sorted(grouped.items()))


def _pairs(rows):
    return [(s, t) for s in rows for t in rows if s["age"] != t["age"]]


def fit_direction(samples, alpha):
    """Identity-centered relative Ridge: d=Cov(a,c)/((1+alpha)*Var(a))."""
    validate_samples(samples)
    if not _finite(alpha) or alpha < 0:
        raise ValueError("Relative Ridge alpha must be finite and nonnegative.")
    covariance = np.zeros(40)
    variance = 0.0
    eligible, excluded, ages = [], [], []
    for subject, rows in _groups(samples, True).items():
        a = np.array([r["age"] for r in rows], dtype=np.float64)
        if len(set(a)) < 2:
            excluded.append(subject)
            continue
        c = np.array([r["shape"] for r in rows], dtype=np.float64)
        x, y = a - a.mean(), c - c.mean(axis=0)
        covariance += np.mean(x[:, None] * y, axis=0)
        variance += float(np.mean(x * x))
        eligible.append(subject)
        ages.extend(a.tolist())
    if len(eligible) < 2 or not math.isfinite(variance) or variance <= 0:
        raise ValueError("At least two informative training identities are required.")
    direction = covariance / variance / (1 + alpha)
    if not np.isfinite(direction).all():
        raise ValueError("Direction overflow.")
    return {
        "direction": direction.tolist(),
        "alpha": alpha,
        "age_min": min(ages),
        "age_max": max(ages),
        "training_identity_ids": sorted(_groups(samples)),
        "informative_identity_ids": eligible,
        "single_age_identity_ids": excluded,
        "within_age_variance_sum": variance,
        "within_age_shape_covariance_sum": covariance.tolist(),
    }


def _model(samples, alpha, gram):
    model = fit_direction(samples, alpha)
    unregularized = (
        np.array(model["within_age_shape_covariance_sum"]) / model["within_age_variance_sum"]
    )
    # Full mapped BFM direction, refitted on exactly this training fold.
    model["bfm_strength_per_year"] = float(gram[-1, :40] @ unregularized / gram[-1, -1])
    cap = 0.0
    for rows in _groups(samples, True).values():
        for s, t in _pairs(rows):
            delta = np.r_[np.subtract(t["shape"], s["shape"]), 0.0]
            cap = max(cap, metric_rms(delta, gram, s["scale"]))
    model["training_displacement_rms_bound"] = cap
    return model


def anchored_coefficients(
    source, source_age, target_age, model, gram, *, scale=1.0, route="identity_centered_ridge"
):
    """Calculate from the immutable source, with exact known-age reset and no clipping."""
    _age(source_age)
    _age(target_age)
    _array(source, (41,))
    if route not in ROUTES or not _finite(scale) or scale <= 0:
        raise ValueError("Invalid route or source frame scale.")
    if target_age == source_age or route == "no_change":
        return source
    if (
        not model["age_min"] <= source_age <= model["age_max"]
        or not model["age_min"] <= target_age <= model["age_max"]
    ):
        raise ValueError("OUTSIDE_FOLD_COVERAGE")
    delta = target_age - source_age
    displacement = np.zeros(41)
    if route == "bfm_direction_refit":
        strength = model["bfm_strength_per_year"] * delta
        if not math.isfinite(strength) or abs(strength) > 50:
            raise ValueError("BFM_STRENGTH_BOUND")
        displacement[-1] = strength
    else:
        displacement[:40] = np.array(model["direction"]) * delta
        if metric_rms(displacement, gram, scale) > model["training_displacement_rms_bound"] * (
            1 + 1e-12
        ):
            raise ValueError("TRAINING_DISPLACEMENT_BOUND")
    result = np.array(source, dtype=np.float64, copy=True) + displacement
    if not np.isfinite(result).all():
        raise ValueError("NONFINITE_PREDICTION")
    result.setflags(write=False)
    return result


def _evaluate(rows, model, gram, route, gallery=()):
    results = []
    for s, t in _pairs(rows):
        result = {
            "source_id": s["sample_id"],
            "target_id": t["sample_id"],
            "subject_id": s["subject_id"],
            "source_age": s["age"],
            "target_age": t["age"],
            "route": route,
            "status": "failed",
            "error_code": None,
        }
        if s["status"] != "ok" or t["status"] != "ok":
            result["error_code"] = "FIT_FAILED"
        elif model is None and route != "no_change":
            result["error_code"] = "INSUFFICIENT_TRAINING_IDENTITIES"
        else:
            original = np.r_[s["shape"], 0.0]
            target = np.r_[t["shape"], 0.0]
            try:
                candidate = anchored_coefficients(
                    original, s["age"], t["age"], model, gram, route=route, scale=s["scale"]
                )
                residual = metric_rms(candidate - target, gram, s["scale"])
                result.update(
                    status="ok",
                    endpoint_neutral_rms=residual,
                    displacement_rms=metric_rms(candidate - original, gram, s["scale"]),
                )
                refs = [
                    r
                    for r in gallery
                    if r["status"] == "ok"
                    and r["subject_id"] != s["subject_id"]
                    and r["age"] == t["age"]
                ]
                distances = [
                    (
                        metric_rms(candidate - np.r_[r["shape"], 0.0], gram, s["scale"]),
                        r["sample_id"],
                    )
                    for r in refs
                ]
                nearest = min(distances) if distances else None
                result.update(
                    identity_reference_count=len(refs),
                    nearest_impostor_id=nearest[1] if nearest else None,
                    identity_margin=nearest[0] - residual if nearest else None,
                )
            except ValueError as error:
                result["error_code"] = str(error)
        results.append(result)
    return results


def _macro(rows, allowed=None):
    grouped = defaultdict(list)
    for row in rows:
        key = (row["source_id"], row["target_id"])
        if row["status"] == "ok" and (allowed is None or key in allowed):
            grouped[row["subject_id"]].append(row["endpoint_neutral_rms"])
    means = {s: math.fsum(v) / len(v) for s, v in sorted(grouped.items())}
    return {
        "valid_pairs": sum(map(len, grouped.values())),
        "identities": len(means),
        "per_identity": means,
        "identity_macro_rms": math.fsum(means.values()) / len(means) if means else None,
    }


def choose_alpha(samples, gram, grid):
    """Inner identity validation; caller must supply only the outer-training rows."""
    folds = []
    for subject, validation in _groups(samples).items():
        if not _pairs(validation):
            continue
        train = [r for r in samples if r["subject_id"] != subject]
        models = {}
        try:
            models = {a: _model(train, a, gram) for a in grid}
        except ValueError:
            pass
        outcomes = {str(a): _evaluate(validation, models.get(a), gram, ROUTES[-1]) for a in grid}
        folds.append(
            {
                "validation_identity": subject,
                "training_identity_ids": sorted(_groups(train)),
                "outcomes": outcomes,
            }
        )
    all_rows = {str(a): [r for fold in folds for r in fold["outcomes"][str(a)]] for a in grid}
    common = set.intersection(
        *[
            {(r["source_id"], r["target_id"]) for r in rows if r["status"] == "ok"}
            for rows in all_rows.values()
        ]
    )
    scores = {str(a): _macro(all_rows[str(a)], common) for a in grid}
    selected, best = None, None
    for a in sorted(grid, reverse=True):
        value = scores[str(a)]["identity_macro_rms"]
        if value is not None and (
            best is None
            or (value < best and not math.isclose(value, best, rel_tol=1e-12, abs_tol=1e-15))
        ):
            selected, best = a, value
    return {"selected_alpha": selected, "scores": scores, "folds": folds}


def run_baseline(samples, gram, grid=(0.0, 0.1, 1.0, 10.0)):
    """Run nested identity folds, retaining every request and all candidate failures."""
    validate_samples(samples)
    gram = validate_metric(gram)
    if (
        not grid
        or len(grid) > 16
        or len(set(grid)) != len(grid)
        or any(not _finite(a) or a < 0 for a in grid)
    ):
        raise ValueError("Invalid relative Ridge grid.")
    grouped = _groups(samples)
    eligible = [s for s, rows in grouped.items() if _pairs(rows)]
    if len(eligible) < 4:
        raise ValueError("Nested validation needs at least four pair-eligible identities.")
    outcomes, folds = [], []
    for subject in eligible:
        train = [r for r in samples if r["subject_id"] != subject]
        tuning = choose_alpha(train, gram, grid)
        model = (
            _model(train, tuning["selected_alpha"], gram)
            if tuning["selected_alpha"] is not None
            else None
        )
        folds.append({"held_out_identity": subject, "tuning": tuning, "model": model})
        for route in ROUTES:
            outcomes.extend(_evaluate(grouped[subject], model, gram, route, train))
    full_tuning = choose_alpha(samples, gram, grid)
    full = (
        _model(samples, full_tuning["selected_alpha"], gram)
        if full_tuning["selected_alpha"] is not None
        else None
    )
    common = set.intersection(
        *[
            {
                (r["source_id"], r["target_id"])
                for r in outcomes
                if r["route"] == route and r["status"] == "ok"
            }
            for route in ROUTES
        ]
    )
    summaries = {}
    for route in ROUTES:
        rows = [r for r in outcomes if r["route"] == route]
        summaries[route] = {
            "requested": len(rows),
            "failures": dict(Counter(r["error_code"] for r in rows if r["status"] != "ok")),
            "all_valid": _macro(rows),
            "common_valid": _macro(rows, common),
        }
    stability = []
    full_vector = np.r_[full["direction"], 0.0] if full else np.zeros(41)
    full_norm = metric_rms(full_vector, gram)
    for fold in folds:
        model = fold["model"]
        v = np.r_[model["direction"], 0.0] if model else np.zeros(41)
        norm = metric_rms(v, gram)
        stability.append(
            {
                "held_out_identity": fold["held_out_identity"],
                "geometry_cosine_to_full": float(v @ gram @ full_vector / (norm * full_norm))
                if norm * full_norm > 0
                else None,
                "geometry_norm_ratio_to_full": norm / full_norm if full_norm > 0 else None,
            }
        )
    agreement = all(
        r["geometry_cosine_to_full"] is not None and r["geometry_cosine_to_full"] > 0
        for r in stability
    )
    base = summaries[ROUTES[0]]["common_valid"]["identity_macro_rms"]
    bfm_agreement = (
        full is not None
        and full["bfm_strength_per_year"] > 0
        and all(f["model"] is not None and f["model"]["bfm_strength_per_year"] > 0 for f in folds)
    )
    preferred, best = "static_fallback", base
    for route, allowed in ((ROUTES[1], bfm_agreement), (ROUTES[-1], agreement)):
        value = summaries[route]["common_valid"]["identity_macro_rms"]
        if (
            allowed
            and value is not None
            and best is not None
            and value < best
            and not math.isclose(value, best, rel_tol=1e-12, abs_tol=1e-15)
        ):
            preferred, best = route, value
    return {
        "schema_version": 1,
        "research_only": True,
        "training_use": False,
        "service_ready": False,
        "years_calibrated": False,
        "identity_accepted": False,
        "g3_complete": False,
        "production_route_selected": None,
        "independent_evaluation": False,
        "samples_requested": len(samples),
        "fit_statuses": dict(Counter(r["status"] for r in samples)),
        "pair_eligible_identity_ids": eligible,
        "outer_folds": folds,
        "outer_pair_outcomes": outcomes,
        "full_tuning": full_tuning,
        "full_model": full,
        "summaries": summaries,
        "stability": stability,
        "direction_agreement_diagnostic": agreement,
        "bfm_positive_scale_diagnostic": bfm_agreement,
        "exploratory_preference": preferred,
        "quality_accepted": False,
    }
