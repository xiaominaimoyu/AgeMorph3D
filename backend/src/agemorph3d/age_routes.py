"""Bounded offline age-route and within-person projection calibration research.

The scale fitted here describes filename-age changes in 3DDFA neutral geometry.
It is not independent age calibration, 3-D truth, or an identity recognizer.
Callers own image/condition association, model pins and the immutable source fit.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace
from numbers import Real
from typing import TYPE_CHECKING

import numpy as np

from .age_geometry import _raw, neutral_vertices
from .age_shape import apply_age_strength
from .static_mesh import projection_rotation

if TYPE_CHECKING:
    from .age_shape import AgeDirection
    from .tddfa import TddfaResult


def _number(value: object, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    return value


def _age(value: object, label: str) -> float:
    value = _number(value, label)
    if not 20 <= value <= 70:
        raise ValueError(f"{label} must be within the frozen 20--70 age range.")
    return value


def _vertices(value: object, label: str) -> np.ndarray:
    array = np.asarray(value)
    if (
        array.dtype.kind not in "iuf"
        or array.ndim != 2
        or array.shape[1] != 3
        or len(array) < 3
        or not np.isfinite(array).all()
    ):
        raise ValueError(f"{label} must be finite (N,3) real coordinates, N >= 3.")
    result = np.array(array, dtype=np.float64, copy=True)
    if not np.isfinite(result).all():
        raise ValueError(f"{label} must fit finite float64 coordinates.")
    return result


def _direction(value: object) -> tuple[np.ndarray, float]:
    direction = _vertices(value, "Direction")
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        squared_norm = float(np.sum(direction * direction))
    if not math.isfinite(squared_norm) or squared_norm <= 0:
        raise ValueError("Direction must have finite positive squared norm.")
    return direction, squared_norm


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string.")
    return value


def _slope(statistics: list[dict]) -> float:
    denominator = math.fsum(row["age_variance"] for row in statistics)
    numerator = math.fsum(row["age_projection_covariance"] for row in statistics)
    if not math.isfinite(denominator) or denominator <= 0 or not math.isfinite(numerator):
        raise ValueError("Calibration requires a finite positive within-identity age variance.")
    slope = numerator / denominator
    if not math.isfinite(slope):
        raise ValueError("Calibration strength per year must remain finite.")
    return slope


def fit_bfm_scale(
    samples: list[dict], neutral_vertices_by_id: dict[str, np.ndarray], direction: np.ndarray
) -> dict:
    """Fit a signed native-strength scale using identity-centered neutral fits.

    Each identity contributes its mean covariance and mean age variance, giving
    each identity equal total photograph weight. Wider age spans retain greater
    leverage. Failed fits must be retained and disclosed separately by the caller.
    """
    direction, squared_norm = _direction(direction)
    grouped = defaultdict(list)
    seen = set()
    for sample in samples:
        if sample.get("group") != "calibration_research":
            raise ValueError("Only frozen calibration_research identities may fit the scale.")
        sample_id = _identifier(sample.get("sample_id"), "Sample ID")
        subject = _identifier(sample.get("subject_id"), "Subject ID")
        age = _age(sample.get("source_age"), "Source age")
        if sample_id in seen:
            raise ValueError("Calibration sample identifiers must be unique.")
        seen.add(sample_id)
        if sample_id not in neutral_vertices_by_id:
            raise ValueError("Every calibration sample requires a successful neutral fit.")
        vertices = _vertices(neutral_vertices_by_id[sample_id], "Neutral fit")
        if vertices.shape != direction.shape:
            raise ValueError("Neutral fits and direction must share the ordered vertex count.")
        with np.errstate(over="ignore", invalid="ignore"):
            projection = float(np.sum(vertices * direction) / squared_norm)
        if not math.isfinite(projection):
            raise ValueError("Native direction projection must remain finite.")
        grouped[subject].append({"sample_id": sample_id, "age": age, "projection": projection})
    if not grouped:
        raise ValueError("Calibration requires samples.")

    statistics = []
    eligible, excluded = [], []
    for subject, rows in sorted(grouped.items()):
        ages = np.asarray([row["age"] for row in rows])
        projections = np.asarray([row["projection"] for row in rows])
        centered_ages, centered_values = ages - ages.mean(), projections - projections.mean()
        with np.errstate(over="ignore", invalid="ignore"):
            variance = float(np.mean(centered_ages * centered_ages))
            covariance = float(np.mean(centered_ages * centered_values))
        if not math.isfinite(variance) or not math.isfinite(covariance):
            raise ValueError("Within-identity sufficient statistics must remain finite.")
        informative = len(set(ages.tolist())) >= 2
        (eligible if informative else excluded).append(subject)
        statistics.append(
            {
                "subject_id": subject,
                "samples": len(rows),
                "distinct_ages": len(set(ages.tolist())),
                "age_min": float(ages.min()),
                "age_max": float(ages.max()),
                "age_mean": float(ages.mean()),
                "projection_mean": float(projections.mean()),
                "age_variance": variance,
                "age_projection_covariance": covariance,
                "eligible": informative,
            }
        )
    informative_statistics = [row for row in statistics if row["eligible"]]
    beta = _slope(informative_statistics)

    folds = []
    for held_out in eligible:
        train = [row for row in informative_statistics if row["subject_id"] != held_out]
        fold = {
            "held_out_identity": held_out,
            "training_identity_ids": [r["subject_id"] for r in train],
        }
        if not train:
            fold.update(status="unavailable", error_code="INSUFFICIENT_TRAINING_IDENTITIES")
            folds.append(fold)
            continue
        train_beta = _slope(train)
        low, high = min(row["age_min"] for row in train), max(row["age_max"] for row in train)
        held = grouped[held_out]
        residuals, unchanged, outside = [], [], 0
        for source in held:
            for target in held:
                if source["age"] == target["age"]:
                    continue
                actual = target["projection"] - source["projection"]
                predicted = train_beta * (target["age"] - source["age"])
                residuals.append(predicted - actual)
                unchanged.append(actual)
                outside += not (low <= source["age"] <= high and low <= target["age"] <= high)
        residuals, unchanged = np.asarray(residuals), np.asarray(unchanged)
        with np.errstate(over="ignore", invalid="ignore"):
            error = float(np.sqrt(np.mean(residuals * residuals)))
            baseline = float(np.sqrt(np.mean(unchanged * unchanged)))
        if not math.isfinite(error) or not math.isfinite(baseline):
            raise ValueError("LOIO projection residuals must remain finite.")
        fold.update(
            status="ok",
            strength_per_year=train_beta,
            train_age_min=low,
            train_age_max=high,
            heldout_age_min=min(row["age"] for row in held),
            heldout_age_max=max(row["age"] for row in held),
            pairs=len(residuals),
            projection_residual_rms=error,
            zero_change_projection_rms=baseline,
            extrapolation_pairs=outside,
            extrapolation_flag=bool(outside),
        )
        folds.append(fold)
    all_ages = [row["age"] for rows in grouped.values() for row in rows]
    return {
        "calibration_kind": "within_identity_neutral_direction_projection",
        "strength_per_year": beta,
        "beta_sign": "positive" if beta > 0 else "negative" if beta < 0 else "zero",
        "age_min": min(all_ages),
        "age_max": max(all_ages),
        "samples": len(samples),
        "identities": len(grouped),
        "eligible_identity_ids": eligible,
        "excluded_identity_ids": excluded,
        "sufficient_statistics": statistics,
        "loio": folds,
        "unit": "bfm_attribute_strength_per_filename_label_year",
        "weighting": "equal total photograph weight per identity; age-span leverage retained",
        "years_calibrated": False,
        "independent_evaluation": False,
    }


def _source(raw: TddfaResult) -> tuple[np.ndarray, np.ndarray]:
    vertices, faces, _, _ = _raw(raw)
    if not isinstance(raw.vertices, np.ndarray) or raw.vertices.dtype != np.float32:
        raise ValueError("Anchored routes require the original float32 raw source vertices.")
    projection_rotation(raw.projection)
    return vertices, faces


def anchored_bfm(
    source: TddfaResult,
    direction: AgeDirection,
    calibration: dict,
    source_age: float | None,
    target_age: float,
) -> TddfaResult:
    """Compute from immutable source; exact source-age reset returns that object.

    Never pass a previously aged result as the source. Keeping source shape/expr
    metadata unchanged is not evidence that human identity has been preserved.
    """
    start, target = _age(source_age, "Source age"), _age(target_age, "Target age")
    _source(source)
    # Existing loader/application enforce native unit, topology, dimensions and pins.
    apply_age_strength(source, direction, 0)
    if target == start:
        return source
    beta = _number(calibration.get("strength_per_year"), "Calibration strength per year")
    low, high = (
        _age(calibration.get("age_min"), "Calibration minimum"),
        _age(calibration.get("age_max"), "Calibration maximum"),
    )
    if low > high or not (low <= start <= high and low <= target <= high):
        raise ValueError("Nonzero BFM age changes cannot extrapolate beyond calibration coverage.")
    return apply_age_strength(source, direction, beta * (target - start))


def anchored_sam(
    source: TddfaResult,
    same_age_fit: TddfaResult | None,
    target_fit: TddfaResult | None,
    expression_basis: np.ndarray,
    source_age: float | None,
    target_age: float,
) -> TddfaResult:
    """Add neutral target-minus-same-age displacement to the original full source.

    The caller must pin that the two fits come from this source's SAM images with
    exactly these integer conditions; geometry alone cannot verify image ages.
    """
    start, target = _age(source_age, "Source age"), _age(target_age, "Target age")
    source_vertices, source_faces = _source(source)
    if target == start:
        return source
    if int(start) != start or int(target) != target:
        raise ValueError("Nonzero SAM age changes require exact integer age conditions.")
    if same_age_fit is None or target_fit is None:
        raise ValueError("Nonzero SAM age changes require both exact-condition fitted images.")
    for raw in (same_age_fit, target_fit):
        vertices, faces = _source(raw)
        if (
            raw.topology_sha256 != source.topology_sha256
            or vertices.shape != source_vertices.shape
            or not np.array_equal(faces, source_faces)
        ):
            raise ValueError("SAM fits must share the original source's exact ordered topology.")
    delta = neutral_vertices(target_fit, expression_basis) - neutral_vertices(
        same_age_fit, expression_basis
    )
    with np.errstate(over="ignore", invalid="ignore"):
        vertices = np.asarray(source_vertices + delta, dtype=np.float32)
    if not np.isfinite(vertices).all():
        raise ValueError("SAM difference geometry must fit finite float32 coordinates.")
    vertices.setflags(write=False)
    return replace(source, vertices=vertices)


def direction_observability(direction: np.ndarray, shape_basis40: np.ndarray) -> dict:
    """Describe full-direction observability without replacing the actual asset."""
    direction, squared_norm = _direction(direction)
    basis = np.asarray(shape_basis40)
    if (
        basis.dtype.kind not in "iuf"
        or basis.shape != (direction.size, 40)
        or not np.isfinite(basis).all()
    ):
        raise ValueError("Shape basis must be finite real (3N,40) coordinates.")
    basis = np.asarray(basis, dtype=np.float64)
    flat = direction.reshape(-1)
    coefficients, _, rank, _ = np.linalg.lstsq(basis, flat, rcond=None)
    projected = basis @ coefficients
    residual = flat - projected
    energy = float(np.dot(projected, projected) / squared_norm)
    remaining = float(np.dot(residual, residual) / squared_norm)
    rms = float(np.sqrt(np.mean(np.sum(residual.reshape(-1, 3) ** 2, axis=1))))
    if not all(math.isfinite(value) for value in (energy, remaining, rms)):
        raise ValueError("Direction observability must remain finite.")
    return {
        "basis_rank": int(rank),
        "direction_norm": math.sqrt(squared_norm),
        "observable_norm_fraction": math.sqrt(max(0, energy)),
        "unobservable_norm_fraction": math.sqrt(max(0, remaining)),
        "observable_energy_fraction": energy,
        "orthogonal_residual_rms": rms,
        "direction_replaced_by_projection": False,
    }
