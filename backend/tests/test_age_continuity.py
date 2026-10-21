"""Synthetic continuity/source-reset evidence, not real age quality acceptance."""

from dataclasses import dataclass

import pytest

np = pytest.importorskip("numpy")

from agemorph3d.age_continuity import (  # noqa: E402
    age_anchors,
    age_weights,
    blend_display_rgba,
    display_step_metrics,
    quantize_display_rgba,
    sam_integer_condition,
    sample_display_rgba,
    static_fallback_at_age,
    support_metrics,
    validate_age,
)


def atlas(color, support=None):
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    support = np.ones((2, 2), dtype=bool) if support is None else np.asarray(support)
    rgba[support, :3], rgba[support, 3] = color, 255
    return rgba


def test_fractional_source_is_preserved_and_unknown_never_acquires_a_default():
    assert validate_age(42.5) == 42.5
    assert validate_age(np.float64(20.25)) == 20.25
    assert validate_age(None, allow_unknown=True) is None
    with pytest.raises(ValueError, match="known"):
        static_fallback_at_age(object(), None, 45)


@pytest.mark.parametrize("value", [True, False, "42.5", 19.999, 70.001, float("nan"), float("inf")])
def test_age_rejects_invalid_inputs_without_rounding_or_clamping(value):
    with pytest.raises(ValueError):
        validate_age(value)


@pytest.mark.parametrize("age", [20, 45.0, np.float64(70)])
def test_sam_exact_integer_conditions(age):
    assert sam_integer_condition(age) == int(age)


@pytest.mark.parametrize("age", [20.01, 42.5, 69.999])
def test_sam_fractional_conditions_fail_instead_of_int_cast(age):
    with pytest.raises(ValueError, match="exact integer"):
        sam_integer_condition(age)


def test_static_route_returns_original_geometry_png_and_glb_object_for_every_age():
    @dataclass(frozen=True)
    class Original:
        vertices: object
        png: bytes
        glb: bytes

    vertices = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.float32)
    original = Original(vertices, b"original PNG\0\xff", b"original GLB\0\xfe")
    before = (vertices.tobytes(), original.png, original.glb)
    for age in (42.5, 20, 69.99, 45, 42.5, 70, 42.5):
        assert static_fallback_at_age(original, 42.5, age) is original
    assert (vertices.tobytes(), original.png, original.glb) == before


def test_source_anchor_is_exact_and_deduplicated_with_uneven_piecewise_weights():
    anchors = age_anchors([70, 20, 45, 45], 42.5)
    assert anchors == (20, 42.5, 45, 70)
    np.testing.assert_array_equal(age_weights(42.5, anchors), [0, 1, 0, 0])
    np.testing.assert_array_equal(age_weights(43.75, anchors), [0, 0.5, 0.5, 0])
    assert age_anchors([20, 45, 70], 45) == (20, 45, 70)
    assert age_anchors([20, 45, 70], None) == (20, 45, 70)
    assert not age_weights(42.5, anchors).flags.writeable


@pytest.mark.parametrize("anchors", [[], [45, 20], [20, 20], [20, float("nan")]])
def test_invalid_anchor_order_or_duplicates_are_rejected_by_weights(anchors):
    with pytest.raises(ValueError):
        age_weights(30, anchors)


def test_interpolation_rejects_uncovered_age_instead_of_extrapolating():
    with pytest.raises(ValueError, match="extrapolate"):
        age_weights(60, (20, 45))
    np.testing.assert_array_equal(age_weights(42.5, (42.5,)), [1])
    with pytest.raises(ValueError, match="extrapolate"):
        age_weights(45, (42.5,))


def test_rgb_interpolation_uses_linear_light_not_srgb_channel_averages():
    result = blend_display_rgba(atlas([0, 0, 0]), atlas([255, 255, 255]), 0.5)
    np.testing.assert_array_equal(result[:, :, :3], np.full((2, 2, 3), 0.5))
    np.testing.assert_array_equal(quantize_display_rgba(result)[:, :, :3], 188)
    assert not result.flags.writeable


def test_premultiplied_alpha_keeps_missing_color_unknown_and_inputs_immutable():
    left = atlas([255, 0, 0], [[True, True], [False, False]])
    right = atlas([0, 0, 255], [[True, False], [True, False]])
    before = left.tobytes(), right.tobytes()
    display = blend_display_rgba(left, right, 0.25)
    np.testing.assert_array_equal(display[0, 0], [0.75, 0, 0.25, 1])
    np.testing.assert_array_equal(display[0, 1], [0.75, 0, 0, 0.75])
    np.testing.assert_array_equal(display[1, 0], [0, 0, 0.25, 0.25])
    np.testing.assert_array_equal(display[1, 1], 0)
    encoded = quantize_display_rgba(display)
    np.testing.assert_array_equal(encoded[0, 1], [255, 0, 0, 191])
    np.testing.assert_array_equal(encoded[1, 0], [0, 0, 255, 64])
    np.testing.assert_array_equal(encoded[1, 1], 0)
    assert (left.tobytes(), right.tobytes()) == before
    metrics = support_metrics(left, right)
    assert [
        metrics[name] for name in ("both_supported", "left_only", "right_only", "both_unknown")
    ] == [1, 1, 1, 1]
    assert metrics["support_jaccard"] == 1 / 3


def test_continuous_float_alpha_still_has_mask_visibility_flips():
    left = atlas([255, 255, 255], [[True, False], [False, False]])
    right = atlas([255, 255, 255], [[False, True], [False, False]])
    for epsilon in (1e-2, 1e-4, 1e-6):
        before = blend_display_rgba(left, right, 0.5 - epsilon)
        after = blend_display_rgba(left, right, 0.5 + epsilon)
        result = display_step_metrics(before, after)
        assert result["float_mask_visibility_flip_texels"] == 2
        assert result["quantized_mask_visibility_flip_texels"] == 2
        assert result["common_straight_linear_rgb_rms_channel"] == 0
        assert result["alpha_max_abs_change"] == pytest.approx(2 * epsilon)
        assert result["black_composite_rms_channel"] > 0


def test_quantization_preserves_all_srgb_endpoint_byte_values():
    value = np.zeros((1, 256, 4), dtype=np.uint8)
    value[0, :, :3] = np.arange(256, dtype=np.uint8)[:, None]
    value[:, :, 3] = 255
    np.testing.assert_array_equal(quantize_display_rgba(blend_display_rgba(value, value, 0)), value)


def test_all_unknown_and_tiny_alpha_quantization_keep_rgba_zero():
    empty = atlas([255, 255, 255], np.zeros((2, 2), dtype=bool))
    display = blend_display_rgba(empty, empty, 0.5)
    assert display_step_metrics(display, display)["common_straight_linear_rgb_rms_channel"] is None
    assert support_metrics(empty, empty)["support_jaccard"] == 1
    tiny = blend_display_rgba(empty, atlas([255, 0, 0]), 1e-9)
    np.testing.assert_array_equal(quantize_display_rgba(tiny), 0)


def test_source_texture_as_explicit_anchor_has_continuous_limits_and_exact_bytes():
    source = atlas([123, 87, 230], [[True, False], [True, True]])
    anchors = {20: atlas([40, 50, 60]), 42.5: source, 70: atlas([180, 90, 70])}
    at_source = sample_display_rgba(anchors, 42.5)
    np.testing.assert_array_equal(quantize_display_rgba(at_source), source)
    previous = None
    for epsilon in (0.1, 0.01, 0.001):
        left = sample_display_rgba(anchors, 42.5 - epsilon)
        right = sample_display_rgba(anchors, 42.5 + epsilon)
        difference = display_step_metrics(left, right)["black_composite_rms_channel"]
        if previous is not None:
            assert difference == pytest.approx(previous / 10, rel=1e-9)
        previous = difference


@pytest.mark.parametrize("bad", ["dtype", "hidden_rgb", "soft_alpha", "shape"])
def test_invalid_anchor_rgba_is_rejected(bad):
    image = atlas([20, 30, 40])
    if bad == "dtype":
        image = image.astype(np.float64)
    elif bad == "hidden_rgb":
        image[0, 0, 3] = 0
    elif bad == "soft_alpha":
        image[0, 0, 3] = 128
    else:
        image = image[:, :, :3]
    with pytest.raises(ValueError):
        blend_display_rgba(image, image, 0.5)


@pytest.mark.parametrize("weight", [True, -0.01, 1.01, float("nan")])
def test_invalid_blend_weights_are_rejected(weight):
    with pytest.raises(ValueError):
        blend_display_rgba(atlas([0, 0, 0]), atlas([1, 2, 3]), weight)


def test_invalid_premultiplied_values_do_not_escape_into_quantization():
    display = np.ones((2, 2, 4), dtype=float)
    display[0, 0, 3] = 0.5
    with pytest.raises(ValueError, match="premultiplied"):
        quantize_display_rgba(display)
