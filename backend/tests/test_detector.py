"""Numerical adapter checks; synthetic predictions are not real-model evidence."""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("onnxruntime")

from agemorph3d.detector import Letterbox, decode_detections, letterbox  # noqa: E402


@pytest.mark.parametrize("size", [(640, 480), (480, 640), (517, 333), (333, 517), (1, 2000)])
def test_letterbox_uses_actual_resize_and_padding(size):
    width, height = size
    rgb = np.full((height, width, 3), [255, 127, 0], dtype=np.uint8)
    tensor, transform = letterbox(rgb)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32 and tensor.flags.c_contiguous
    points = np.array([[0, 0], [width - 1, height - 1], [width / 3, height / 4]])
    projected = points * [transform.resized_width / width, transform.resized_height / height]
    projected += [transform.left, transform.top]
    np.testing.assert_allclose(transform.restore(projected), points, atol=2e-4)
    np.testing.assert_allclose(tensor[0, :, transform.top, transform.left], [1, 127 / 255, 0])


def candidate(x, y, w=20, h=20, score=0.9, marker=8):
    return [x, y, w, h, score, *([marker, marker + 1] * 5), 1.0]


def decode(rows):
    return decode_detections(
        np.asarray([rows], dtype=np.float32).reshape(1, -1, 16),
        Letterbox(640, 640, 640, 640, 0, 0),
    )


def test_nms_retains_correct_landmarks_and_separate_faces():
    faces = decode(
        [
            candidate(100, 100, score=0.8, marker=10),
            candidate(101, 101, marker=20),
            candidate(300, 300, marker=30),
        ]
    )
    assert len(faces) == 2
    assert faces[0].bbox == (91, 91, 20, 20)
    assert faces[0].landmarks == ((20, 21),) * 5
    assert faces[1].landmarks == ((30, 31),) * 5


def test_nms_ties_are_stable_and_confidence_uses_both_probabilities():
    assert decode([candidate(50, 50, marker=1), candidate(50, 50, marker=5)])[0].landmarks[0] == (
        1,
        2,
    )
    row = candidate(50, 50, score=0.7)
    row[-1] = 0.7
    assert decode([row]) == []  # 0.49, below the fixed 0.5 threshold
    assert len(decode([candidate(50, 50, score=0.5)])) == 1


def test_empty_and_degenerate_detections():
    assert decode([]) == []
    assert decode([candidate(10, 10, w=0)]) == []
    assert decode([candidate(-100, -100)]) == []


def test_box_and_points_share_letterbox_inverse_without_mirroring():
    transform = Letterbox(320, 160, 640, 320, 0, 160)
    row = candidate(200, 300, 80, 100)
    row[5:15] = [160, 260, 240, 260, 200, 300, 170, 330, 230, 330]
    face = decode_detections(np.array([[row]], dtype=np.float32), transform)[0]
    assert face.bbox == (80, 45, 40, 50)
    assert face.landmarks == ((80, 50), (120, 50), (100, 70), (85, 85), (115, 85))


@pytest.mark.parametrize("bad", [np.zeros((1, 16)), np.zeros((1, 16, 1)), np.zeros((2, 1, 16))])
def test_rejects_other_output_layouts(bad):
    with pytest.raises(ValueError, match="decoded"):
        decode_detections(bad, Letterbox(640, 640, 640, 640, 0, 0))


@pytest.mark.parametrize(
    "index,value", [(0, float("nan")), (10, float("inf")), (2, -1), (4, -0.1), (15, 2)]
)
def test_rejects_invalid_predictions(index, value):
    row = candidate(10, 10)
    row[index] = value
    with pytest.raises(ValueError):
        decode([row])


def test_nms_work_is_bounded():
    with pytest.raises(ValueError, match="candidates"):
        decode([candidate(10, 10)] * 3001)
