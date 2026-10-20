"""Independent geometric/color checks for the offline FFHQ alignment bridge."""

import pytest

np = pytest.importorskip("numpy")

from agemorph3d.ffhq_alignment import align_ffhq, transform_points  # noqa: E402


def face():
    points = np.zeros((68, 2), dtype=np.float64)
    points[:] = (100, 90)
    # Eye centers (80,80), (120,80); mouth center (100,120).
    contour = np.array([[-4, 0], [-2, -2], [2, -2], [4, 0], [2, 2], [-2, 2]])
    points[36:42] = contour + (80, 80)
    points[42:48] = contour + (120, 80)
    points[48], points[54] = (85, 120), (115, 120)
    return points


def coordinate_photo(size=200):
    yy, xx = np.mgrid[:size, :size]
    return np.stack((xx, yy, np.full_like(xx, 37)), axis=-1).astype(np.uint8)


def test_exact_crop_geometry_and_independent_linear_color_field():
    rgb, landmarks = coordinate_photo(), face()
    before = rgb.copy(), landmarks.copy()
    alignment = align_ffhq(rgb, landmarks, output_size=80)
    # For these eyes/mouth the FFHQ half-side is 80 and center is (100,84).
    np.testing.assert_allclose(alignment.source_quad, [[20, 4], [20, 164], [180, 164], [180, 4]])
    # Center (u,v) samples (21+2u,5+2v), not the 3DDFA 120px crop.
    yy, xx = np.mgrid[:80, :80]
    expected = np.stack((21 + 2 * xx, 5 + 2 * yy, np.full_like(xx, 37)), axis=-1)
    np.testing.assert_array_equal(alignment.rgb, expected)
    assert alignment.valid_mask.all()
    np.testing.assert_array_equal(rgb, before[0])
    np.testing.assert_array_equal(landmarks, before[1])
    for array in (
        alignment.rgb,
        alignment.valid_mask,
        alignment.source_quad,
        alignment.source_to_aligned,
        alignment.aligned_to_source,
    ):
        assert not array.flags.writeable
    assert alignment.metadata["geometry_compatible_with_upstream"] is True
    assert alignment.metadata["pixel_identical_to_upstream"] is False
    assert alignment.metadata["generated_pixels_eligible_for_uv"] is False


def test_quad_edges_pixel_centers_and_roundtrip_are_distinct():
    alignment = align_ffhq(coordinate_photo(), face())
    np.testing.assert_allclose(
        transform_points(alignment.source_quad, alignment.source_to_aligned),
        [[-0.5, -0.5], [-0.5, 255.5], [255.5, 255.5], [255.5, -0.5]],
        atol=1e-12,
    )
    points = np.array([[0.0, 0], [100.25, 84.75], [199, 199], [-3.1, 400.2]])
    aligned = transform_points(points, alignment.source_to_aligned)
    np.testing.assert_allclose(
        transform_points(aligned, alignment.aligned_to_source), points, atol=1e-12
    )
    np.testing.assert_allclose(
        transform_points([[127.5, 127.5]], alignment.aligned_to_source), [[100, 84]]
    )


@pytest.mark.parametrize("angle", [-60, -25, 30, 70])
def test_rotated_landmarks_keep_asymmetric_photo_orientation(angle):
    radians = np.deg2rad(angle)
    rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
    landmarks = (face() - [100, 100]) @ rotation.T + [100, 100]
    aligned = align_ffhq(coordinate_photo(), landmarks, output_size=80)
    unrotated_quad = np.array([[20, 4], [20, 164], [180, 164], [180, 4]])
    expected_quad = (unrotated_quad - [100, 100]) @ rotation.T + [100, 100]
    np.testing.assert_allclose(aligned.source_quad, expected_quad, atol=1e-12)
    # Compare interior pixels with an independently rotated analytic coordinate field.
    query = np.array([[30, 30], [40, 40], [50, 50]])
    original = (np.array([[81, 65], [101, 85], [121, 105]]) - [100, 100]) @ rotation.T + [100, 100]
    expected = np.column_stack((np.rint(original), [37, 37, 37])).astype(np.uint8)
    np.testing.assert_array_equal(aligned.rgb[query[:, 1], query[:, 0]], expected)
    assert aligned.valid_mask[query[:, 1], query[:, 0]].all()


def test_reflection_context_never_becomes_valid_original_photo():
    rgb = coordinate_photo()
    landmarks = face() - [50, 40]
    aligned = align_ffhq(rgb, landmarks, output_size=80)
    # Top-left source coordinate is (-29,-35); reflection gives original (29,35).
    np.testing.assert_array_equal(aligned.rgb[0, 0], [29, 35, 37])
    assert not aligned.valid_mask[0, 0]
    # First positive source coordinates are x=1 at u=15 and y=1 at v=18.
    assert not aligned.valid_mask[17, 15]
    assert not aligned.valid_mask[18, 14]
    assert aligned.valid_mask[18, 15]
    np.testing.assert_array_equal(aligned.rgb[18, 15], [1, 1, 37])
    assert aligned.metadata["reflected_or_unsupported_pixels"] > 0
    assert aligned.metadata["reflected_pixels_eligible_for_uv"] is False


def test_fractional_sample_beyond_last_center_is_not_complete_bilinear_support():
    landmarks = face() + [18.75, 34.75]
    aligned = align_ffhq(coordinate_photo(), landmarks, output_size=80)
    # Last row/column sample (197.75,197.75) is still supported. Moving 2 pixels
    # takes the last column to199.75: inside the image edge but outside centers.
    assert aligned.valid_mask[-1, -1]
    moved = align_ffhq(coordinate_photo(), landmarks + [2, 0], output_size=80)
    assert not moved.valid_mask[-1, -1]
    assert moved.valid_mask[-1, -2]


def test_z_is_ignored_only_after_validation_and_readonly_inputs_are_allowed():
    rgb, landmarks = coordinate_photo(), face()
    rgb.setflags(write=False)
    landmarks.setflags(write=False)
    points3 = np.column_stack((landmarks, np.arange(68)))
    actual = align_ffhq(rgb, points3)
    expected = align_ffhq(rgb, landmarks)
    np.testing.assert_array_equal(actual.rgb, expected.rgb)
    points3[4, 2] = np.nan
    with pytest.raises(ValueError, match="finite"):
        align_ffhq(rgb, points3)


@pytest.mark.parametrize("size", [32, 1024])
def test_both_allowed_output_size_boundaries_produce_valid_geometry(size):
    aligned = align_ffhq(coordinate_photo(), face(), output_size=size)
    assert aligned.rgb.shape == (size, size, 3)
    assert aligned.valid_mask.all()
    np.testing.assert_allclose(
        transform_points([[100, 84]], aligned.source_to_aligned),
        [[size / 2 - 0.5, size / 2 - 0.5]],
    )


@pytest.mark.parametrize("size", [True, 31, 1025, 64.0])
def test_output_size_bounds(size):
    with pytest.raises(ValueError, match="output_size"):
        align_ffhq(coordinate_photo(), face(), output_size=size)


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((68, 2), dtype=bool),
        np.zeros((67, 2)),
        np.zeros((68, 4)),
        np.zeros((68, 2), dtype=complex),
        np.full((68, 2), np.inf),
        np.full((68, 2), "x"),
    ],
)
def test_landmark_shape_dtype_and_finiteness(bad):
    with pytest.raises(ValueError):
        align_ffhq(coordinate_photo(), bad)


@pytest.mark.parametrize(
    "mode",
    [
        "coincident",
        "mirror",
        "upside_down",
        "mouth_above",
        "collapsed_eye",
        "wide_mouth",
        "far",
        "huge",
    ],
)
def test_implausible_or_explosive_geometry_is_rejected(mode):
    points = face()
    if mode == "coincident":
        points[42:48] = points[36:42]
    elif mode == "mirror":
        points[:, 0] = 200 - points[:, 0]
    elif mode == "upside_down":
        points = 200 - points
    elif mode == "mouth_above":
        points[[48, 54], 1] = 40
    elif mode == "collapsed_eye":
        points[36:42] = [80, 80]
    elif mode == "wide_mouth":
        points[54, 0] = 1000
    elif mode == "far":
        points += 1000
    else:
        points = (points - 100) * 100 + 100
    with pytest.raises(ValueError):
        align_ffhq(coordinate_photo(), points)


def test_source_type_shape_and_pixel_budget_are_checked_before_sampling():
    for source in (
        np.zeros((20, 20, 3)),
        np.zeros((20, 20), dtype=np.uint8),
        np.zeros((1, 20, 3), dtype=np.uint8),
    ):
        with pytest.raises(ValueError, match="RGB"):
            align_ffhq(source, face())
    # A broadcast view proves the budget without allocating a 48MB source copy.
    oversized = np.broadcast_to(np.zeros((1, 1, 3), dtype=np.uint8), (4001, 4000, 3))
    with pytest.raises(ValueError, match="16,000,000"):
        align_ffhq(oversized, face())


@pytest.mark.parametrize(
    "points,matrix",
    [
        ([[1, 2, 3]], np.eye(3)),
        ([[True, False]], np.eye(3)),
        ([[1, np.nan]], np.eye(3)),
        ([[1, 2]], np.eye(2)),
        ([[1, 2]], np.zeros((3, 3))),
        ([[1, 2]], np.array([[1, 0, 0], [0, 1, 0], [1, 0, -1]])),
    ],
)
def test_transform_rejects_malformed_singular_or_undefined_coordinates(points, matrix):
    with pytest.raises(ValueError):
        transform_points(points, matrix)


def test_transform_accepts_independent_projective_reference():
    points = transform_points([[2, 4], [0, 1]], [[2, 0, 1], [0, 3, -1], [0.5, 0, 1]])
    np.testing.assert_allclose(points, [[2.5, 5.5], [1, 2]])
