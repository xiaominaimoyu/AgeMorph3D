"""CPU pose operator contracts using synthetic adapters, not camera/G2 evidence."""

from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from agemorph3d import static_mesh  # noqa: E402
from agemorph3d.errors import ApiError  # noqa: E402
from agemorph3d.realtime import infer_realtime  # noqa: E402


class Detector:
    def __init__(self):
        self.faces = [
            SimpleNamespace(
                bbox=(7.5, 5.0, 23.0, 25.0),
                landmarks=((12.0, 12.0), (26.0, 11.0), (20.0, 19.0), (14.0, 25.0), (25.0, 26.0)),
                confidence=np.float32(0.875),
            )
        ]
        self.calls = []
        self.failure = None

    def detect(self, rgb):
        self.calls.append(rgb)
        if self.failure is not None:
            raise self.failure
        return self.faces


class Reconstructor:
    def __init__(self):
        self.result = SimpleNamespace(
            coordinate_system="bfm_model_raw",
            projection=np.column_stack((np.eye(3) * 0.003, [60.0, 50.0, -40.0])),
        )
        self.calls = []
        self.failure = None

    def reconstruct(self, rgb, bbox):
        self.calls.append((rgb, bbox))
        if self.failure is not None:
            raise self.failure
        return self.result


@pytest.fixture
def operators():
    # Asymmetric input and measurements expose accidental mirroring or XY swaps.
    rgb = np.zeros((40, 64, 3), dtype=np.uint8)
    rgb[3:10, 4:12, 0] = 201
    return rgb, Detector(), Reconstructor()


def test_pixels_landmark_order_confidence_and_input_ownership_are_preserved(operators):
    rgb, detector, reconstructor = operators
    before = rgb.copy()
    result = infer_realtime(rgb, detector, reconstructor)
    assert set(result) == {"bbox", "landmarks", "pose", "conf"}
    assert result["bbox"] == [7.5, 5.0, 23.0, 25.0]
    assert result["landmarks"] == [[12, 12], [26, 11], [20, 19], [14, 25], [25, 26]]
    assert result["conf"] == 0.875
    assert result["pose"] == {"R": np.eye(3).reshape(-1).tolist(), "t": [0.0, 0.0, 0.0]}
    assert detector.calls[0] is rgb
    assert reconstructor.calls[0][0] is rgb
    assert reconstructor.calls[0][1] is detector.faces[0].bbox
    np.testing.assert_array_equal(rgb, before)


@pytest.mark.parametrize("scale", [1e-20, 0.003, 42.0, 1e20])
def test_right_handed_pose_removes_scale_shear_without_mirror_or_image_y_flip(operators, scale):
    rgb, detector, reconstructor = operators
    yaw, roll = np.deg2rad([31, -17])
    yaw_rotation = np.array(
        [[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]]
    )
    roll_rotation = np.array(
        [[np.cos(roll), -np.sin(roll), 0], [np.sin(roll), np.cos(roll), 0], [0, 0, 1]]
    )
    expected = roll_rotation @ yaw_rotation
    stretch = np.array([[1.2, 0.12, 0.07], [0.12, 1.5, -0.1], [0.07, -0.1, 1.8]])
    reconstructor.result.projection[:, :3] = scale * expected @ stretch
    result = infer_realtime(rgb, detector, reconstructor)
    rotation = np.array(result["pose"]["R"]).reshape(3, 3)
    np.testing.assert_allclose(rotation, expected, atol=1e-12)
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
    assert np.linalg.det(rotation) == pytest.approx(1)
    # The +Z nose rotates toward source +X for positive yaw; no preview flip.
    assert (rotation @ [0, 0, 1])[0] > 0
    assert result["pose"]["t"] == [0.0, 0.0, 0.0]


def test_no_glb_geometry_or_cache_work_and_no_coefficients_required(operators, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Realtime inference must not build or publish a GLB.")

    monkeypatch.setattr(static_mesh, "build_static_mesh", forbidden)
    monkeypatch.setattr(static_mesh, "_encode_glb", forbidden)
    result = infer_realtime(*operators)
    assert "shape" not in result and "expr" not in result
    assert "mesh_id" not in result and "topology_id" not in result


def test_signed_outside_landmarks_remain_unclipped(operators):
    rgb, detector, reconstructor = operators
    points = ((-3.0, 5.0), (65.0, 10.0), (20.0, 19.0), (14.0, 25.0), (25.0, 42.0))
    detector.faces[0].landmarks = points
    result = infer_realtime(rgb, detector, reconstructor)
    assert result["landmarks"] == [list(point) for point in points]


@pytest.mark.parametrize(("count", "code"), [(0, "NO_FACE"), (2, "MULTI_FACE")])
def test_frame_face_count_failure_can_recover_without_reconstruction(operators, count, code):
    rgb, detector, reconstructor = operators
    one_face = detector.faces[0]
    detector.faces = [one_face] * count
    with pytest.raises(ApiError) as failure:
        infer_realtime(rgb, detector, reconstructor)
    assert (failure.value.status_code, failure.value.code) == (422, code)
    assert reconstructor.calls == []
    detector.faces = [one_face]
    assert infer_realtime(rgb, detector, reconstructor)["conf"] == 0.875


@pytest.mark.parametrize(
    ("target", "name", "invalid"),
    [
        ("detector", "faces", ()),
        ("face", "bbox", (1, 2, 3)),
        ("face", "bbox", (1, 2, 3, float("nan"))),
        ("face", "bbox", (-1, 2, 3, 4)),
        ("face", "bbox", (1, 2, 0, 4)),
        ("face", "bbox", (1, 2, 64, 4)),
        ("face", "bbox", (1, 39, 3, 2)),
        ("face", "bbox", (True, False, True, True)),
        ("face", "landmarks", [(1, 2)] * 4),
        ("face", "landmarks", [(1, 2, 3)] * 5),
        ("face", "landmarks", [(1, float("inf"))] * 5),
        ("face", "landmarks", [(1, 16_385)] * 5),
        ("face", "landmarks", [(-16_385, 2)] * 5),
        ("face", "confidence", -0.01),
        ("face", "confidence", 1.01),
        ("face", "confidence", float("nan")),
        ("face", "confidence", True),
        ("face", "confidence", "0.875"),
        ("raw", "coordinate_system", "canonical"),
        ("raw", "projection", np.eye(3)),
        ("raw", "projection", np.zeros((3, 4))),
        ("raw", "projection", np.full((3, 4), float("nan"))),
        ("raw", "projection", np.column_stack((np.diag([1, 1, -1]), np.zeros(3)))),
        ("raw", "projection", np.column_stack((np.diag([1, 1, 1e-7]), np.zeros(3)))),
    ],
)
def test_malformed_detector_or_pose_outputs_fail_closed(operators, target, name, invalid):
    rgb, detector, reconstructor = operators
    instance = {
        "detector": detector,
        "face": detector.faces[0],
        "raw": reconstructor.result,
    }[target]
    setattr(instance, name, invalid)
    with pytest.raises(ApiError) as failure:
        infer_realtime(rgb, detector, reconstructor)
    assert failure.value.code == "POSE_FAILED"
    assert failure.value.status_code == 500


@pytest.mark.parametrize("target", ["detector", "reconstructor"])
@pytest.mark.parametrize(
    "exception",
    [RuntimeError("PRIVATE-PATH image-secret"), ApiError(418, "PRIVATE", "private-photo")],
)
def test_native_and_nested_api_errors_are_sanitized(operators, target, exception):
    rgb, detector, reconstructor = operators
    {"detector": detector, "reconstructor": reconstructor}[target].failure = exception
    with pytest.raises(ApiError) as failure:
        infer_realtime(rgb, detector, reconstructor)
    assert failure.value.code == "POSE_FAILED"
    assert failure.value.status_code == 500
    assert "PRIVATE" not in failure.value.detail and "private" not in failure.value.detail
    assert failure.value.__suppress_context__ is True


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        np.zeros((0, 4, 3), dtype=np.uint8),
        np.zeros((4, 4, 4), dtype=np.uint8),
        np.zeros((4, 4, 3), dtype=np.float32),
        np.zeros((4, 4), dtype=np.uint8),
    ],
)
def test_invalid_input_never_calls_models(operators, invalid):
    _, detector, reconstructor = operators
    with pytest.raises(ApiError) as failure:
        infer_realtime(invalid, detector, reconstructor)
    assert failure.value.code == "POSE_FAILED"
    assert detector.calls == []
    assert reconstructor.calls == []
