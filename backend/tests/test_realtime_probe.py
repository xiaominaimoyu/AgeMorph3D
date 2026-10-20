"""Synthetic offline orchestration checks; no physical camera or G2 acceptance."""

import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from agemorph3d import realtime_probe
from agemorph3d.model_assets import ModelAssetError

np = pytest.importorskip("numpy")


@pytest.fixture
def arguments(tmp_path):
    for name in ("detector", "reconstructor"):
        (tmp_path / f"{name}.json").write_text("synthetic manifest")
    with Image.new("RGB", (800, 400), "white") as image:
        image.save(tmp_path / "private-original-name.png")
    return [
        "--detector-manifest",
        str(tmp_path / "detector.json"),
        "--reconstructor-manifest",
        str(tmp_path / "reconstructor.json"),
        "--image",
        str(tmp_path / "private-original-name.png"),
        "--frame-count",
        "3",
        "--output",
        str(tmp_path / "report.json"),
    ]


@pytest.fixture
def synthetic(monkeypatch):
    calls = []
    closed = []
    frames = []
    state = SimpleNamespace(counts=[1, 1, 1], failure=None, verified=False)

    def verify(path, *, research_allow_unresolved=False):
        calls.append(research_allow_unresolved)
        if not research_allow_unresolved and not state.verified:
            raise ModelAssetError("private-original-name.png secret path")
        return SimpleNamespace(
            manifest=SimpleNamespace(
                model_id=f"synthetic-{path.stem}",
                backend=realtime_probe._BACKENDS[path.stem],
                revision="test",
            ),
            license_verified=state.verified,
        )

    def detect(rgb):
        frames.append(rgb.copy())
        count = state.counts.pop(0) if state.counts else 1
        face = SimpleNamespace(
            bbox=(1, 1, 6, 4),
            landmarks=((2, 2), (6, 2), (4, 3), (2, 4), (6, 4)),
            confidence=0.875,
        )
        return [face] * count

    def reconstruct(_rgb, _bbox):
        if state.failure:
            raise state.failure
        return SimpleNamespace(
            coordinate_system="bfm_model_raw",
            projection=np.column_stack((np.eye(3), [60, 50, 40])),
        )

    def construct(role, assets):
        return SimpleNamespace(
            provider="CPUExecutionProvider",
            license_verified=assets.license_verified,
            detect=detect,
            reconstruct=reconstruct,
            close=lambda: closed.append(role),
        )

    monkeypatch.setattr(realtime_probe, "load_verified_manifest", verify)
    monkeypatch.setattr(realtime_probe, "_construct_model", construct)
    # Fixtures isolate CLI ownership; real numerical rotation is still exercised.
    monkeypatch.setattr(realtime_probe, "detector_selftest", lambda _model: None)
    monkeypatch.setattr(realtime_probe, "reconstructor_selftest", lambda _model: None)
    return SimpleNamespace(calls=calls, closed=closed, frames=frames, state=state)


class Capture:
    def __init__(self, *, opened=True, okay=True):
        self.opened = opened
        self.okay = okay
        self.releases = 0
        self.reads = 0
        self.failure = None
        self.bgr = np.zeros((40, 80, 3), dtype=np.uint8)
        self.bgr[5, 7] = [11, 22, 33]

    def isOpened(self):
        return self.opened

    def read(self):
        self.reads += 1
        if self.failure:
            raise self.failure
        return self.okay, self.bgr

    def release(self):
        self.releases += 1


def camera_arguments(arguments):
    result = arguments.copy()
    result[4:6] = ["--camera-index", "0"]
    return [*result, "--research-allow-unresolved"]


def read_report(tmp_path):
    return json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))


def test_strict_default_refuses_unresolved_without_camera_or_model_loading(
    arguments, synthetic, monkeypatch, tmp_path, capsys
):
    def forbidden(*_args):
        pytest.fail("Strict unresolved probe must not open a camera or construct a model.")

    monkeypatch.setattr(realtime_probe, "_open_camera", forbidden)
    monkeypatch.setattr(realtime_probe, "_construct_model", forbidden)
    assert realtime_probe.main(arguments) == 1
    report = read_report(tmp_path)
    assert report["error_code"] == "MODEL_ASSET_ERROR"
    assert report["license_verified"] is False
    assert synthetic.calls == [False]
    assert "secret" not in json.dumps(report) and "private-original" not in json.dumps(report)
    assert "secret" not in capsys.readouterr().out


def test_image_resize_aggregate_timings_and_research_boundary(arguments, synthetic, tmp_path):
    assert realtime_probe.main([*arguments, "--research-allow-unresolved"]) == 0
    report = read_report(tmp_path)
    assert report["technical_execution"] == "passed"
    assert report["service_ready"] is False and report["g2_complete"] is False
    assert report["license_verified"] is False
    assert report["counts"] == {"FACE_STATE": 3, "NO_FACE": 0, "MULTI_FACE": 0}
    assert report["frames_attempted"] == 3
    assert report["source_dimensions"] == [[800, 400]]
    assert report["submitted_dimensions"] == [[640, 320]]
    assert report["numerical_checks"]["valid_payloads"] == 3
    for step in ("capture", "resize", "detector", "regressor", "frame_total"):
        summary = report["timings_ms"][step]
        assert summary["count"] == 3 and 0 <= summary["p50"] <= summary["p95"]
    assert (
        report["input"]["sha256"]
        == hashlib.sha256((tmp_path / "private-original-name.png").read_bytes()).hexdigest()
    )
    assert report["saved_frames"] is False and report["saved_per_frame_parameters"] is False
    serialized = json.dumps(report)
    assert "private-original" not in serialized and str(tmp_path) not in serialized
    assert (
        '"bbox"' not in serialized and '"landmarks"' not in serialized and '"R"' not in serialized
    )
    assert synthetic.closed == ["detector", "reconstructor"]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "detector.json",
        "private-original-name.png",
        "reconstructor.json",
        "report.json",
    ]


def test_exif_orientation_is_applied_before_frame_resize(arguments, synthetic, tmp_path):
    source = tmp_path / "private-rotated.jpg"
    with Image.new("RGB", (800, 400), "white") as image:
        exif = Image.Exif()
        exif[274] = 6
        image.save(source, exif=exif)
    arguments[5] = str(source)
    assert realtime_probe.main([*arguments, "--research-allow-unresolved"]) == 0
    report = read_report(tmp_path)
    assert report["source_dimensions"] == [[400, 800]]
    assert report["submitted_dimensions"] == [[320, 640]]
    assert synthetic.frames[0].shape == (640, 320, 3)


def test_verified_metadata_does_not_grant_readiness(arguments, synthetic, tmp_path):
    synthetic.state.verified = True
    assert realtime_probe.main(arguments) == 0
    report = read_report(tmp_path)
    assert report["license_verified"] is True
    assert report["service_ready"] is False and report["g2_complete"] is False
    assert synthetic.calls == [False, False]


def test_no_face_and_multiple_faces_are_counted_and_next_frame_recovers(
    arguments, synthetic, tmp_path
):
    synthetic.state.counts = [0, 2, 1]
    assert realtime_probe.main([*arguments, "--research-allow-unresolved"]) == 0
    report = read_report(tmp_path)
    assert report["counts"] == {"FACE_STATE": 1, "NO_FACE": 1, "MULTI_FACE": 1}
    assert report["frames_attempted"] == 3
    assert report["timings_ms"]["detector"]["count"] == 3
    assert report["timings_ms"]["regressor"]["count"] == 1
    assert synthetic.closed == ["detector", "reconstructor"]


def test_camera_bgr_conversion_is_not_mirrored_and_capture_released(
    arguments, synthetic, monkeypatch, tmp_path
):
    capture = Capture()
    monkeypatch.setattr(realtime_probe, "_open_camera", lambda index: capture)
    assert realtime_probe.main(camera_arguments(arguments)) == 0
    report = read_report(tmp_path)
    assert report["input"]["type"] == "physical_camera"
    assert "sha256" not in report["input"]
    assert report["camera_release"] == "completed"
    assert capture.releases == 1 and capture.reads == 3
    assert synthetic.frames[0][5, 7].tolist() == [33, 22, 11]
    assert synthetic.frames[0][5, 72].tolist() == [0, 0, 0]
    assert synthetic.closed == ["detector", "reconstructor"]


@pytest.mark.parametrize(
    ("opened", "okay", "code"),
    [(False, True, "CAMERA_OPEN_FAILED"), (True, False, "CAMERA_READ_FAILED")],
)
def test_camera_failures_release_capture_and_models(
    arguments, synthetic, monkeypatch, tmp_path, opened, okay, code
):
    capture = Capture(opened=opened, okay=okay)
    monkeypatch.setattr(realtime_probe, "_open_camera", lambda _index: capture)
    assert realtime_probe.main(camera_arguments(arguments)) == 1
    assert read_report(tmp_path)["error_code"] == code
    assert capture.releases == 1
    assert synthetic.closed == ["detector", "reconstructor"]


@pytest.mark.parametrize("target", ["capture", "model"])
def test_runtime_failure_closes_resources_and_never_exposes_private_messages(
    arguments, synthetic, monkeypatch, tmp_path, target, capsys
):
    capture = Capture()
    if target == "capture":
        capture.failure = OSError("private-frame-private-path")
    else:
        synthetic.state.failure = RuntimeError("private-frame-private-path")
    monkeypatch.setattr(realtime_probe, "_open_camera", lambda _index: capture)
    assert realtime_probe.main(camera_arguments(arguments)) == 1
    report = read_report(tmp_path)
    assert report["technical_execution"] == "failed"
    assert capture.releases == 1
    assert synthetic.closed == ["detector", "reconstructor"]
    assert "private" not in json.dumps(report) and "private" not in capsys.readouterr().out


def test_wall_budget_checked_between_native_operations_and_resources_released(
    arguments, synthetic, monkeypatch, tmp_path
):
    capture = Capture()
    monkeypatch.setattr(realtime_probe, "_open_camera", lambda _index: capture)
    monkeypatch.setattr(realtime_probe, "_MAX_SECONDS", -1)
    assert realtime_probe.main(camera_arguments(arguments)) == 1
    report = read_report(tmp_path)
    assert report["error_code"] == "FRAME_BUDGET_EXCEEDED"
    assert report["frames_attempted"] == 0 and capture.reads == 0
    assert capture.releases == 1
    assert synthetic.closed == ["detector", "reconstructor"]


def test_selftest_failure_closes_already_created_models(
    arguments, synthetic, monkeypatch, tmp_path
):
    def fail(_model):
        raise RuntimeError("private-checkpoint")

    monkeypatch.setattr(realtime_probe, "reconstructor_selftest", fail)
    assert realtime_probe.main([*arguments, "--research-allow-unresolved"]) == 1
    report = read_report(tmp_path)
    assert report["error_code"] == "PROBE_FAILED"
    assert synthetic.closed == ["detector", "reconstructor"]
    assert "private" not in json.dumps(report)


def test_release_failure_is_reported_and_remaining_models_are_closed(
    arguments, synthetic, monkeypatch, tmp_path
):
    capture = Capture()

    def fail_release():
        capture.releases += 1
        raise OSError("private-device-name")

    capture.release = fail_release
    monkeypatch.setattr(realtime_probe, "_open_camera", lambda _index: capture)
    assert realtime_probe.main(camera_arguments(arguments)) == 1
    report = read_report(tmp_path)
    assert report["error_code"] == "CAMERA_RELEASE_FAILED"
    assert report["technical_execution"] == "failed" and report["camera_release"] == "failed"
    assert synthetic.closed == ["detector", "reconstructor"]
    assert "private" not in json.dumps(report)


def test_existing_report_is_preserved_before_loading_or_camera(
    arguments, synthetic, monkeypatch, tmp_path, capsys
):
    path = tmp_path / "report.json"
    previous = b"previous private report"
    path.write_bytes(previous)
    assert realtime_probe.main(camera_arguments(arguments)) == 1
    assert path.read_bytes() == previous
    assert synthetic.calls == [] and synthetic.closed == []
    assert "OUTPUT_EXISTS" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--frame-count", "0"),
        ("--frame-count", "121"),
        ("--camera-index", "-1"),
        ("--camera-index", "16"),
    ],
)
def test_cli_limits_reject_before_model_loading(arguments, synthetic, option, value):
    limited = arguments.copy()
    if option == "--camera-index":
        limited[4:6] = [option, value]
    else:
        limited[7] = value
    with pytest.raises(SystemExit) as exit_info:
        realtime_probe.main(limited)
    assert exit_info.value.code == 2
    assert synthetic.calls == []


def test_camera_and_image_arguments_are_mutually_exclusive(arguments, synthetic):
    with pytest.raises(SystemExit) as exit_info:
        realtime_probe.main([*arguments, "--camera-index", "0"])
    assert exit_info.value.code == 2 and synthetic.calls == []


def test_import_does_not_load_optional_cpu_libraries():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import agemorph3d.realtime_probe; "
            "assert not {'numpy', 'cv2', 'onnxruntime'} & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
