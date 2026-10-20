"""Identity-level summaries for offline, development-only age research.

These are proxy measurements, not age accuracy or identity acceptance. Failed
requests stay in the denominator; each metric uses its own observed identities.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from numbers import Real
from statistics import median


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite numeric value, not a boolean.")
    return float(value)


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string.")
    return value


def _mean(values: list[float]) -> float:
    return math.fsum(value / len(values) for value in values)


def _percentile(ordered: list[float], quantile: float) -> float:
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def aggregate_identity_metrics(
    records: list[dict],
    metric_keys: list[str],
    bootstrap_seed: int = 20261020,
    bootstrap_samples: int = 2000,
) -> dict:
    """Summarize each identity first, then give all observed identities equal weight.

    Missing or null metrics are absent measurements, including on successful
    records. Provided metrics must be finite even on failed records. Bootstrap
    resamples whole identities with replacement and reports interpolated 2.5th
    and 97.5th percentiles; fewer than two eligible identities yields no interval.
    """
    if any(not isinstance(key, str) or not key for key in metric_keys) or len(
        set(metric_keys)
    ) != len(metric_keys):
        raise ValueError("Metric keys must be unique nonempty strings.")
    if type(bootstrap_seed) is not int:
        raise ValueError("Bootstrap seed must be an integer.")
    if type(bootstrap_samples) is not int or bootstrap_samples < 1:
        raise ValueError("Bootstrap sample count must be a positive integer.")

    grouped = defaultdict(list)
    for record in records:
        subject = _identifier(record.get("subject_id"), "Subject ID")
        if record.get("status") not in {"ok", "failed"}:
            raise ValueError("Research record status must be ok or failed.")
        for key in metric_keys:
            if record.get(key) is not None:
                _number(record[key], f"Metric {key}")
        grouped[subject].append(record)

    per_identity = {}
    for subject, rows in sorted(grouped.items()):
        successful = [row for row in rows if row["status"] == "ok"]
        metrics = {}
        for key in metric_keys:
            values = [float(row[key]) for row in successful if row.get(key) is not None]
            metrics[key] = {"count": len(values), "mean": _mean(values) if values else None}
        per_identity[subject] = {
            "requests": len(rows),
            "successes": len(successful),
            "failures": len(rows) - len(successful),
            "metrics": metrics,
        }

    macro = {}
    for key in metric_keys:
        eligible = [
            item["metrics"][key] for item in per_identity.values() if item["metrics"][key]["count"]
        ]
        values = [item["mean"] for item in eligible]
        interval = None
        if len(values) >= 2:
            rng = random.Random(bootstrap_seed)
            draws = sorted(
                _mean(rng.choices(values, k=len(values))) for _ in range(bootstrap_samples)
            )
            interval = [_percentile(draws, 0.025), _percentile(draws, 0.975)]
        macro[key] = {
            "identities": len(values),
            "observations": sum(item["count"] for item in eligible),
            "mean": _mean(values) if values else None,
            "median": float(median(values)) if values else None,
            "ci95": interval,
        }

    successes = sum(item["successes"] for item in per_identity.values())
    return {
        "requests": len(records),
        "successes": successes,
        "failures": len(records) - successes,
        "per_identity": per_identity,
        "macro": macro,
        "bootstrap": {"seed": bootstrap_seed, "samples": bootstrap_samples, "unit": "identity"},
    }


def longitudinal_pairs(samples: list[dict]) -> list[dict]:
    """Return all ordered within-person pairs with distinct 20--70 age labels.

    Same-age photos remain legitimate input samples but are not longitudinal
    pairs. This function never splits identities or decides fit success.
    """
    seen, grouped = set(), defaultdict(list)
    for sample in samples:
        sample_id = _identifier(sample.get("sample_id"), "Sample ID")
        subject = _identifier(sample.get("subject_id"), "Subject ID")
        if sample_id in seen:
            raise ValueError("Sample IDs must be unique across identities.")
        seen.add(sample_id)
        age = _number(sample.get("source_age"), "Source age")
        if not 20 <= age <= 70:
            raise ValueError("Research source age must be within the frozen 20--70 range.")
        grouped[subject].append({"sample_id": sample_id, "source_age": age})

    pairs = []
    for subject, photos in sorted(grouped.items()):
        photos = sorted(photos, key=lambda photo: photo["sample_id"])
        for source in photos:
            for target in photos:
                if source["source_age"] != target["source_age"]:
                    pairs.append(
                        {
                            "subject_id": subject,
                            "source_id": source["sample_id"],
                            "target_id": target["sample_id"],
                            "source_age": source["source_age"],
                            "target_age": target["source_age"],
                        }
                    )
    return pairs
