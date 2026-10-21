"""Offline display interpolation diagnostics, separate from SAM age generation.

The selected geometry route remains static. Floating point premultiplied linear
RGBA describes a possible display blend; the current viewer does not implement
it. Quantized MASK visibility and age/identity quality are separate questions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import TypeVar

import numpy as np

_T = TypeVar("_T")


def validate_age(value: object, *, allow_unknown: bool = False) -> float | None:
    """Preserve a finite decimal age; unknown never acquires a default value."""
    if value is None and allow_unknown:
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError("A known finite source/target age within 20--70 is required.")
    age = float(value)
    if not math.isfinite(age) or not 20 <= age <= 70:
        raise ValueError("Age must be finite and within 20--70; no rounding or clamping.")
    return age


def sam_integer_condition(age: object) -> int:
    """Reject fractional SAM conditions instead of upstream's silent int cast."""
    value = validate_age(age)
    assert value is not None
    if not value.is_integer():
        raise ValueError("Direct SAM generation requires an exact integer age condition.")
    return int(value)


def age_anchors(ages: Sequence[float], source_age: float | None = None) -> tuple[float, ...]:
    """Sort and deduplicate anchors, optionally including the exact source age.

    Adding an age does not create a corresponding geometry or texture asset.
    The caller must supply the original asset for a source anchor, never a
    same-age generated image as a replacement for the original.
    """
    values = {validate_age(age) for age in ages}
    source = validate_age(source_age, allow_unknown=True)
    if source is not None:
        values.add(source)
    if not values:
        raise ValueError("At least one known age anchor is required.")
    return tuple(sorted(values))


def age_weights(target_age: float, anchors: Sequence[float]) -> np.ndarray:
    """Piecewise linear weights over actual ages, rejecting unsupported coverage."""
    target = validate_age(target_age)
    values = [validate_age(value) for value in anchors]
    if not values or any(b <= a for a, b in zip(values, values[1:], strict=False)):
        raise ValueError("Age anchors must be nonempty and strictly increasing.")
    assert target is not None
    if not values[0] <= target <= values[-1]:
        raise ValueError("Display interpolation cannot extrapolate beyond its age anchors.")
    result = np.zeros(len(values), dtype=np.float64)
    if target in values:
        result[values.index(target)] = 1
    else:
        right = next(index for index, value in enumerate(values) if value > target)
        weight = (target - values[right - 1]) / (values[right] - values[right - 1])
        result[right - 1], result[right] = 1 - weight, weight
    result.setflags(write=False)
    return result


def static_fallback_at_age(original: _T, source_age: float | None, target_age: float) -> _T:
    """Return the immutable original object; every requested shape stays static.

    Exact source reset includes any original PNG/GLB bytes owned by that object.
    A fractional source is retained, but does not authorize fractional SAM
    conditioning. Unknown source age blocks absolute-age requests.
    """
    validate_age(source_age)
    validate_age(target_age)
    return original


def _rgba(value: np.ndarray) -> np.ndarray:
    if (
        not isinstance(value, np.ndarray)
        or value.dtype != np.uint8
        or value.ndim != 3
        or value.shape[-1] != 4
        or min(value.shape[:2]) < 1
        or value.shape[0] * value.shape[1] > 16_000_000
    ):
        raise ValueError("Anchor atlas must be a bounded nonempty uint8 RGBA array.")
    alpha = value[:, :, 3]
    if not np.all((alpha == 0) | (alpha == 255)) or np.any(value[alpha == 0] != 0):
        raise ValueError("Anchor atlases require binary alpha and unknown RGBA exactly zero.")
    return value


def _unit(value: object) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError("Blend weight must be a finite number within 0--1.")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Blend weight must be a finite number within 0--1.")
    return value


def _linear(srgb: np.ndarray) -> np.ndarray:
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _srgb(linear: np.ndarray) -> np.ndarray:
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)


def blend_display_rgba(left: np.ndarray, right: np.ndarray, weight: float) -> np.ndarray:
    """Return float64 premultiplied linear RGBA, without filling unknown color.

    Where only one endpoint is supported its known color fades with alpha; it
    is not a newly observed/fully supported surface. Both-unknown stays zero.
    This continuous display proposal needs BLEND rendering; current MASK/0.5
    rendering can still change visibility abruptly.
    """
    left, right, weight = _rgba(left), _rgba(right), _unit(weight)
    if left.shape != right.shape:
        raise ValueError("Age atlases must use the exact same common UV raster size.")
    la, ra = left[:, :, 3:4].astype(np.float64) / 255, right[:, :, 3:4] / 255.0
    result = np.empty(left.shape, dtype=np.float64)
    result[:, :, :3] = (1 - weight) * la * _linear(left[:, :, :3] / 255.0) + weight * ra * _linear(
        right[:, :, :3] / 255.0
    )
    result[:, :, 3:4] = (1 - weight) * la + weight * ra
    result.setflags(write=False)
    return result


def _display(value: np.ndarray) -> np.ndarray:
    array = np.asarray(value)
    if (
        array.dtype.kind != "f"
        or array.ndim != 3
        or array.shape[-1] != 4
        or min(array.shape[:2]) < 1
        or not np.isfinite(array).all()
        or np.any(array < 0)
        or np.any(array > 1)
        or np.any(array[:, :, :3] > array[:, :, 3:4] + 1e-12)
    ):
        raise ValueError("Display must be finite premultiplied linear floating RGBA in 0--1.")
    return array


def quantize_display_rgba(display: np.ndarray) -> np.ndarray:
    """Encode an experimental straight sRGB RGBA atlas; not current viewer behavior."""
    display = _display(display)
    alpha = display[:, :, 3:4]
    straight = np.divide(
        display[:, :, :3], alpha, out=np.zeros_like(display[:, :, :3]), where=alpha > 0
    )
    result = np.empty(display.shape, dtype=np.uint8)
    result[:, :, :3] = np.rint(np.clip(_srgb(np.clip(straight, 0, 1)), 0, 1) * 255)
    result[:, :, 3:4] = np.rint(alpha * 255)
    result[result[:, :, 3] == 0] = 0
    result.setflags(write=False)
    return result


def sample_display_rgba(atlases: Mapping[float, np.ndarray], target_age: float) -> np.ndarray:
    """Interpolate existing atlases; no SAM run or source-age inference occurs."""
    anchors = age_anchors(list(atlases))
    weights = age_weights(target_age, anchors)
    active = np.flatnonzero(weights)
    left, right = int(active[0]), int(active[-1])
    return blend_display_rgba(
        atlases[anchors[left]], atlases[anchors[right]], 0 if left == right else weights[right]
    )


def support_metrics(left: np.ndarray, right: np.ndarray) -> dict:
    left, right = _rgba(left), _rgba(right)
    if left.shape != right.shape:
        raise ValueError("Age atlases must have matching common UV raster sizes.")
    a, b = left[:, :, 3] == 255, right[:, :, 3] == 255
    intersection, union = int((a & b).sum()), int((a | b).sum())
    return {
        "both_supported": intersection,
        "left_only": int((a & ~b).sum()),
        "right_only": int((~a & b).sum()),
        "both_unknown": int((~a & ~b).sum()),
        "support_xor_texels": int((a ^ b).sum()),
        "support_jaccard": intersection / union if union else 1.0,
        "empty_union_jaccard_policy": "one when both supports are empty",
    }


def _decoded_quantized(display: np.ndarray) -> np.ndarray:
    rgba = quantize_display_rgba(display)
    alpha = rgba[:, :, 3:4] / 255.0
    return np.concatenate((_linear(rgba[:, :, :3] / 255.0) * alpha, alpha), axis=2)


def display_step_metrics(first: np.ndarray, second: np.ndarray) -> dict:
    """Measure floating display change separately from quantized MASK visibility.

    RGB on common support alone omits appearing/disappearing regions, so alpha
    and composites over both black and white backgrounds are also reported.
    No result is an age, identity or visual-quality acceptance threshold.
    """
    first, second = _display(first), _display(second)
    if first.shape != second.shape:
        raise ValueError("Display arrays must have matching shapes.")
    delta = second - first
    qa, qb = _decoded_quantized(first), _decoded_quantized(second)
    both = (first[:, :, 3] > 0) & (second[:, :, 3] > 0)
    common_delta = second[both, :3] / second[both, 3:4] - first[both, :3] / first[both, 3:4]
    black, white = delta[:, :, :3], delta[:, :, :3] - delta[:, :, 3:4]
    errors = []
    for raw, decoded in ((first, qa), (second, qb)):
        error = decoded - raw
        errors.extend(
            [
                float(np.max(np.abs(error[:, :, :3]))),
                float(np.max(np.abs(error[:, :, :3] - error[:, :, 3:4]))),
            ]
        )
    return {
        "alpha_mean_abs_change": float(np.mean(np.abs(delta[:, :, 3]))),
        "alpha_max_abs_change": float(np.max(np.abs(delta[:, :, 3]))),
        "premultiplied_linear_rgb_rms_channel": float(np.sqrt(np.mean(black * black))),
        "black_composite_rms_channel": float(np.sqrt(np.mean(black * black))),
        "white_composite_rms_channel": float(np.sqrt(np.mean(white * white))),
        "float_mask_visibility_flip_texels": int(
            np.count_nonzero((first[:, :, 3] >= 0.5) != (second[:, :, 3] >= 0.5))
        ),
        "quantized_mask_visibility_flip_texels": int(
            np.count_nonzero((qa[:, :, 3] >= 0.5) != (qb[:, :, 3] >= 0.5))
        ),
        "common_positive_alpha_texels": int(both.sum()),
        "common_straight_linear_rgb_rms_channel": (
            float(np.sqrt(np.mean(common_delta * common_delta))) if both.any() else None
        ),
        "quantization_max_composite_channel_error": max(errors),
        "alpha_cutoff": 0.5,
        "interpretation": "display/transport diagnostics; no visual or age quality threshold",
    }
