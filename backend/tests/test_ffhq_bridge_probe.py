"""Synthetic bridge orchestration; passing tests do not establish real G3 quality."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

np = pytest.importorskip("numpy")

from agemorph3d.model_assets import ModelAssetError  # noqa: E402
from agemorph3d.tddfa import TddfaResult  # noqa: E402

_PATH = Path(__file__).resolve().parents[2] / "tools" / "ffhq_bridge_probe.py"
_SPEC = importlib.util.spec_from_file_location("ffhq_bridge_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


@pytest.fixture
def example(monkeypatch, tmp_path):
    image = tmp_path / "synthetic.png"
    y, x = np.mgrid[:320, :320]
    rgb = np.stack([x % 256, y % 256, (x + y) % 256], axis=-1).astype(np.uint8)
    Image.fromarray(rgb).save(image)
    points = np.zeros((68, 2), dtype=np.float32) + [160, 160]
    angles = np.linspace(0, 2 * np.pi, 6, endpoint=False)
    for start, center in ((36, [120, 120]), (42, [200, 120])):
        points[start : start + 6] = np.array(center) + np.stack(
            [np.cos(angles) * 8, np.sin(angles) * 4], axis=1
        )
    points[48], points[54] = [140, 200], [180, 200]
    points = points.astype(np.float32)
    raw = TddfaResult(
        shape=np.zeros(40, dtype=np.float32),
        expr=np.zeros(10, dtype=np.float32),
        vertices=np.column_stack([points, np.zeros(68)]).astype(np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int64),
        projection=np.array([[1, 0, 0, 1], [0, -1, 0, 120], [0, 0, 1, 1]], dtype=np.float32),
        roi=(0, 0, 120, 120),
        topology_sha256="a" * 64,
    )
    manifests = {}
    for role in ("detector", "reconstructor"):
        manifests[role] = tmp_path / (role + ".json")
        manifests[role].write_text("{}", encoding="utf-8")
    state = SimpleNamespace(faces=[SimpleNamespace(bbox=(60, 40, 200, 240))])
    calls, closed, checks, verified = [], [], [], []

    def construct(role, _assets):
        calls.append(role)
        return SimpleNamespace(
            provider="CPUExecutionProvider",
            license_verified=False,
            keypoint_coordinates=np.arange(204).reshape(68, 3),
            detect=lambda rgb: state.faces,
            reconstruct=lambda rgb, bbox: raw,
            close=lambda: closed.append(role),
        )

    def verify(path, *, research_allow_unresolved=False):
        verified.append(research_allow_unresolved)
        if not research_allow_unresolved:
            raise ModelAssetError("private location must not be exposed")
        role = path.stem
        return SimpleNamespace(
            license_verified=False,
            manifest=SimpleNamespace(
                backend="yolov5_face_onnx" if role == "detector" else "3ddfa_v2_onnx",
                model_id="synthetic-" + role,
                artifacts=[SimpleNamespace(role="bfm", sha256="b" * 64, size_bytes=1)],
            ),
        )

    monkeypatch.setattr(probe, "load_verified_manifest", verify)
    monkeypatch.setattr("agemorph3d.static_probe._construct_model", construct)
    monkeypatch.setattr(probe, "detector_selftest", lambda model: checks.append("detector"))
    monkeypatch.setattr(
        probe, "reconstructor_selftest", lambda model: checks.append("reconstructor")
    )
    output = tmp_path / "result"
    arguments = [
        "--image",
        str(image),
        "--detector-manifest",
        str(manifests["detector"]),
        "--reconstructor-manifest",
        str(manifests["reconstructor"]),
        "--output-dir",
        str(output),
        "--research-allow-unresolved",
    ]
    return SimpleNamespace(
        image=image,
        rgb=rgb,
        points=points,
        raw=raw,
        manifests=manifests,
        output=output,
        arguments=arguments,
        state=state,
        calls=calls,
        closed=closed,
        checks=checks,
        verified=verified,
    )


def read_report(example):
    return json.loads((example.output / "report.json").read_text(encoding="utf-8"))


def test_bridge_runs_real_alignment_on_projected_synthetic_points(example):
    assert probe.main(example.arguments) == 0
    report = read_report(example)
    assert report["technical_execution"] == "passed"
    assert all(
        not report[key]
        for key in (
            "service_ready",
            "g3_complete",
            "years_calibrated",
            "identity_accepted",
            "uv_registered",
            "sam_executed",
        )
    )
    assert example.calls == example.checks == example.closed == ["detector", "reconstructor"]
    assert example.verified == [True, True]
    assert report["input"]["sha256"] == hashlib.sha256(example.image.read_bytes()).hexdigest()
    assert (report["input"]["width"], report["input"]["height"]) == (320, 320)
    for role, path in example.manifests.items():
        assert (
            report["models"][role]["manifest_sha256"]
            == hashlib.sha256(path.read_bytes()).hexdigest()
        )
        assert not report["models"][role]["license_verified"]
    coords = json.loads((example.output / "coordinates.json").read_text(encoding="utf-8"))
    np.testing.assert_array_equal(coords["source_points"], example.points)
    assert not coords["independent_ground_truth"]
    assert coords["roundtrip_max_source_pixels"] < 1e-8
    assert "-0.5" in coords["half_pixel_convention"]
    aligned_points = np.array(coords["aligned_points"])
    assert aligned_points[48, 1] > aligned_points[36:48, 1].mean()
    assert aligned_points[36:42, 0].mean() < aligned_points[42:48, 0].mean()
    for name, item in report["artifacts"].items():
        content = (example.output / name).read_bytes()
        assert item == {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    with Image.open(example.output / "aligned.png") as aligned:
        assert aligned.mode == "RGB" and aligned.size == (256, 256)
    with Image.open(example.output / "valid-mask.png") as mask:
        coverage = np.asarray(mask) != 0
        assert coverage.mean() == report["alignment"]["valid_fraction"]
        assert 0 < coverage.mean() < 1
    assert not report["reconstruction"]["crop_120_exported"]


@pytest.mark.parametrize(("count", "code"), [(0, "NO_FACE"), (2, "MULTI_FACE")])
def test_face_cardinality_failure_saves_only_safe_report_and_closes_models(example, count, code):
    example.state.faces *= count
    assert probe.main(example.arguments) == 1
    assert read_report(example)["error_code"] == code
    assert [path.name for path in example.output.iterdir()] == ["report.json"]
    assert example.closed == ["detector", "reconstructor"]


def test_existing_output_is_preserved_before_loading_or_input_decode(example, capsys):
    example.output.mkdir()
    marker = example.output / "report.json"
    marker.write_bytes(b"foreign evidence")
    example.image.unlink()
    assert probe.main(example.arguments) == 1
    assert marker.read_bytes() == b"foreign evidence" and not example.calls
    assert json.loads(capsys.readouterr().out)["error_code"] == "OUTPUT_EXISTS"


def test_strict_license_default_rejects_before_constructing_any_model(example, capsys):
    args = [value for value in example.arguments if value != "--research-allow-unresolved"]
    assert probe.main(args) == 1
    assert read_report(example)["error_code"] == "MODEL_ASSET_ERROR"
    assert example.verified == [False] and not example.calls
    text = json.dumps(read_report(example)) + capsys.readouterr().out
    assert "private" not in text


def test_real_manifest_hash_mismatch_is_rejected_before_model_contents(example, monkeypatch):
    from agemorph3d.model_assets import load_verified_manifest

    path = example.manifests["detector"]
    (path.parent / "model.bin").write_bytes(b"x")
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model_id": "synthetic",
                "backend": "yolov5_face_onnx",
                "revision": "synthetic",
                "code_license": "MIT",
                "code_license_url": "https://example.com/code",
                "weights_license": "unknown",
                "weights_license_url": "https://example.com/weights",
                "license_status": "unresolved",
                "artifacts": [
                    {
                        "path": "model.bin",
                        "source_url": "https://example.com/model",
                        "sha256": "0" * 64,
                        "size_bytes": 1,
                        "role": "detector",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "load_verified_manifest", load_verified_manifest)
    assert probe.main(example.arguments) == 1
    assert read_report(example)["error_code"] == "MODEL_ASSET_ERROR" and not example.calls


def test_manifest_mutation_during_verification_is_rejected_before_model_loading(
    example, monkeypatch
):
    original = probe.load_verified_manifest

    def mutate(path, **kwargs):
        value = original(path, **kwargs)
        path.write_text('{"changed":true}', encoding="utf-8")
        return value

    monkeypatch.setattr(probe, "load_verified_manifest", mutate)
    assert probe.main(example.arguments) == 1
    assert read_report(example)["error_code"] == "MODEL_ASSET_ERROR" and not example.calls


def test_failed_second_verification_releases_first_model(example, monkeypatch):
    original = probe.load_verified_manifest

    def reject(path, **kwargs):
        if path.stem == "reconstructor":
            raise ModelAssetError("private second manifest")
        return original(path, **kwargs)

    monkeypatch.setattr(probe, "load_verified_manifest", reject)
    assert probe.main(example.arguments) == 1
    assert read_report(example)["error_code"] == "MODEL_ASSET_ERROR"
    assert example.closed == ["detector"]


def test_selftest_failure_also_releases_owned_model(example, monkeypatch):
    def reject(_model):
        raise ValueError("secret details")

    monkeypatch.setattr(probe, "detector_selftest", reject)
    assert probe.main(example.arguments) == 1
    assert example.closed == ["detector"]
    assert "secret" not in json.dumps(read_report(example))


@pytest.mark.parametrize("provider", ["CUDAExecutionProvider", "unexpected"])
def test_non_cpu_provider_never_passes_selftest(example, monkeypatch, provider):
    import agemorph3d.static_probe as static_probe

    original = static_probe._construct_model

    def non_cpu(role, assets):
        model = original(role, assets)
        model.provider = provider
        return model

    monkeypatch.setattr(static_probe, "_construct_model", non_cpu)
    assert probe.main(example.arguments) == 1
    assert read_report(example)["error_code"] == "MODEL_ASSET_ERROR"
    assert not example.checks and example.closed == ["detector"]


def test_alignment_failure_does_not_leak_input_or_leave_photo_outputs(example, monkeypatch):
    def reject(*args, **kwargs):
        raise ValueError("secret input path")

    monkeypatch.setattr("agemorph3d.ffhq_alignment.align_ffhq", reject)
    assert probe.main(example.arguments) == 1
    assert read_report(example)["stage"] == "alignment"
    assert [path.name for path in example.output.iterdir()] == ["report.json"]
    assert example.closed == ["detector", "reconstructor"]
    assert "secret" not in json.dumps(read_report(example))


def test_invalid_inverse_coordinate_mapping_never_publishes_aligned_photo(example, monkeypatch):
    from dataclasses import replace

    from agemorph3d import ffhq_alignment

    original = ffhq_alignment.align_ffhq

    def wrong_inverse(*args, **kwargs):
        aligned = original(*args, **kwargs)
        return replace(aligned, aligned_to_source=np.eye(3))

    monkeypatch.setattr(ffhq_alignment, "align_ffhq", wrong_inverse)
    assert probe.main(example.arguments) == 1
    assert read_report(example)["stage"] == "alignment"
    assert [path.name for path in example.output.iterdir()] == ["report.json"]
    assert example.closed == ["detector", "reconstructor"]


def test_one_close_error_does_not_skip_remaining_owned_model_cleanup(example, monkeypatch):
    import agemorph3d.static_probe as static_probe

    original = static_probe._construct_model

    def construct(role, assets):
        model = original(role, assets)
        if role == "detector":

            def close():
                example.closed.append(role)
                raise RuntimeError("private cleanup detail")

            model.close = close
        return model

    monkeypatch.setattr(static_probe, "_construct_model", construct)
    example.state.faces = []
    assert probe.main(example.arguments) == 1
    assert read_report(example)["error_code"] == "NO_FACE"
    assert example.closed == ["detector", "reconstructor"]
    assert "private" not in json.dumps(read_report(example))


def test_bad_decoder_input_fails_before_loading_models(example):
    example.image.write_bytes(b"not a PNG")
    assert probe.main(example.arguments) == 1
    assert read_report(example)["error_code"] == "BAD_INPUT" and not example.calls


def test_decoder_byte_budget_is_enforced_before_loading_models(example, monkeypatch):
    settings = probe.Settings()
    monkeypatch.setattr(probe, "Settings", lambda: SimpleNamespace(max_image_bytes=4))
    assert settings.max_image_bytes > 4
    assert probe.main(example.arguments) == 1
    assert read_report(example)["error_code"] == "INPUT_TOO_LARGE" and not example.calls


def test_collision_cleans_only_owned_files_and_keeps_foreign_payload(example, monkeypatch):
    original = Path.open

    def fail(path, mode="r", *args, **kwargs):
        if path.name == "aligned.png" and mode == "xb":
            path.write_bytes(b"foreign concurrent payload")
            raise FileExistsError("private collision detail")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    assert probe.main(example.arguments) == 1
    assert (example.output / "aligned.png").read_bytes() == b"foreign concurrent payload"
    assert not (example.output / "source-landmarks.png").exists()
    assert not (example.output / "source-roi.png").exists()
    assert read_report(example)["error_code"] == "OUTPUT_WRITE_FAILED"
    assert read_report(example)["stage"] == "output_write"
    assert "artifacts" not in read_report(example)
