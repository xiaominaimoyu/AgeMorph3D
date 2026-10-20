"""Offline strength/UV orchestration with synthetic models, not real G3 evidence."""

import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

np = pytest.importorskip("numpy")

from agemorph3d import age_research_probe as probe  # noqa: E402
from agemorph3d.age_shape import AgeDirection  # noqa: E402
from agemorph3d.model_assets import ModelAssetError  # noqa: E402
from agemorph3d.tddfa import TddfaResult  # noqa: E402


@pytest.fixture
def example(monkeypatch, tmp_path):
    image = tmp_path / "example.png"
    Image.new("RGB", (24, 24), (160, 40, 70)).save(image)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    raw = TddfaResult(
        shape=np.arange(40, dtype=np.float32),
        expr=np.arange(10, dtype=np.float32),
        vertices=np.array([[-1, -1, 0], [0, 1, 1], [1, -1, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int64),
        projection=np.array([[8, 0, 0, 12], [0, 8, 0, 108], [0, 0, 1, 0]], dtype=np.float32),
        roi=(0, 0, 24, 24),
        topology_sha256="a" * 64,
    )
    direction = AgeDirection(
        np.array([[0.001, 0, 0], [0, 0.002, 0.001], [-0.001, 0, 0]], dtype=np.float32),
        np.ones((3, 3), dtype=np.float32),
        np.arange(3, dtype=np.int32),
        raw.topology_sha256,
        "b" * 64,
        "c" * 64,
    )
    closed = []
    calls = []

    def construct(role, _assets):
        calls.append(role)
        return SimpleNamespace(
            provider="CPUExecutionProvider",
            license_verified=False,
            detect=lambda rgb: [SimpleNamespace(bbox=(1, 1, 20, 20))],
            reconstruct=lambda rgb, bbox: raw,
            close=lambda: closed.append(role),
        )

    def verify(path, **kwargs):
        role = "detector" if str(path).endswith("detector.json") else "reconstructor"
        return SimpleNamespace(
            license_verified=False,
            manifest=SimpleNamespace(
                backend="yolov5_face_onnx" if role == "detector" else "3ddfa_v2_onnx",
                model_id="explicit-synthetic",
                artifacts=[SimpleNamespace(role="bfm", sha256="b" * 64)],
            ),
        )

    detector_manifest = tmp_path / "detector.json"
    detector_manifest.write_text("{}")
    monkeypatch.setattr(probe, "load_verified_manifest", verify)
    monkeypatch.setattr("agemorph3d.static_probe._construct_model", construct)
    monkeypatch.setattr(probe, "detector_selftest", lambda model: None)
    monkeypatch.setattr(probe, "reconstructor_selftest", lambda model: None)
    monkeypatch.setattr("agemorph3d.age_shape.load_age_direction", lambda *a, **kw: direction)
    output = tmp_path / "result"
    arguments = [
        "--detector-manifest",
        str(detector_manifest),
        "--reconstructor-manifest",
        str(manifest),
        "--image",
        str(image),
        "--output-dir",
        str(output),
        "--research-allow-unresolved",
    ]
    return SimpleNamespace(
        raw=raw,
        direction=direction,
        image=image,
        output=output,
        arguments=arguments,
        calls=calls,
        closed=closed,
        directory=tmp_path,
    )


def read_report(example):
    return json.loads((example.output / "report.json").read_text(encoding="utf-8"))


def positions(path):
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + length])
    view = document["bufferViews"][document["accessors"][0]["bufferView"]]
    values = np.frombuffer(data[28 + length :], "<f4", count=9, offset=view["byteOffset"]).reshape(
        3, 3
    )
    return document, values


def with_direction(example):
    return [
        *example.arguments,
        "--direction",
        str(example.directory / "direction.npz"),
        "--direction-sha256",
        "d" * 64,
        "--strengths=-50,0,50",
    ]


def test_native_variants_use_fixed_source_frame_and_remain_static(example):
    assert probe.main(with_direction(example)) == 0
    report = read_report(example)
    assert report["technical_execution"] == "passed"
    assert (
        not report["years_calibrated"] and not report["g3_complete"] and not report["service_ready"]
    )
    assert report["numerical_checks"]["zero_preserves_exact_vertices"]
    assert report["numerical_checks"]["roundtrip_max_canonical_error"] < 1e-6
    _, original = positions(example.output / "mesh.glb")
    _, middle = positions(example.output / "strength-01.glb")
    np.testing.assert_array_equal(original, middle)
    for item in report["variants"]:
        document, values = positions(example.output / item["file"])
        expected = original + item["strength"] * example.direction.shape_direction / 2
        np.testing.assert_allclose(values, expected, atol=1e-7)
        assert document["extras"]["asset_mode"] == "static"
        assert not document["extras"]["attribute_research"]["years_calibrated"]
        assert "ageAnchors" not in document["extras"]
        assert item["shape_coefficients_unchanged"] and item["expression_coefficients_unchanged"]
    assert example.closed == ["detector", "reconstructor"]


def test_photo_uv_is_embedded_without_age_texture_claim_and_bound_asset_reusable(example):
    uv = example.directory / "uv.npz"
    np.savez(uv, uv=np.array([[0, 0], [0.5, 1], [1, 0]], dtype=np.float32))
    pin = hashlib.sha256(uv.read_bytes()).hexdigest()
    assert (
        probe.main(
            [*example.arguments, "--uv", str(uv), "--uv-sha256", pin, "--source-age", "42.5"]
        )
        == 0
    )
    report = read_report(example)
    assert not report["age_texture_generated"] and not report["base_texture"]["age_generated"]
    assert report["source_age"] == {"value": 42.5, "method": "user", "calibration_id": None}
    with np.load(example.output / "uv_bound.npz", allow_pickle=False) as bound:
        assert bound["topology_sha256"].item() == example.raw.topology_sha256
        np.testing.assert_array_equal(bound["uv"], [[0, 0], [0.5, 1], [1, 0]])
    assert "images" in positions(example.output / "mesh.glb")[0]
    with Image.open(example.output / "base-atlas.png") as image:
        assert image.mode == "RGBA" and image.size == (256, 256)


def test_unresolved_strict_loading_returns_only_failure_report(example, monkeypatch):
    def reject(*args, **kwargs):
        assert not kwargs["research_allow_unresolved"]
        raise ModelAssetError("private-model-directory")

    monkeypatch.setattr(probe, "load_verified_manifest", reject)
    args = [x for x in example.arguments if x != "--research-allow-unresolved"]
    assert probe.main(args) == 1
    assert read_report(example)["error_code"] == "MODEL_ASSET_ERROR"
    assert [x.name for x in example.output.iterdir()] == ["report.json"]
    assert "private" not in (example.output / "report.json").read_text(encoding="utf-8")
    assert not example.calls


def test_existing_directory_is_preserved_before_any_model_loading(example):
    example.output.mkdir()
    marker = example.output / "mesh.glb"
    marker.write_bytes(b"original private evidence")
    assert probe.main(example.arguments) == 1
    assert marker.read_bytes() == b"original private evidence"
    assert not example.calls


def test_wrong_uv_hash_is_rejected_before_arrays_and_closes_models(example):
    uv = example.directory / "uv.npz"
    uv.write_bytes(b"not even a valid archive")
    assert probe.main([*example.arguments, "--uv", str(uv), "--uv-sha256", "0" * 64]) == 1
    assert read_report(example)["error_code"] == "PROBE_FAILED"
    assert example.closed == ["detector", "reconstructor"]
    assert not (example.output / "mesh.glb").exists()


def test_failure_after_first_model_load_still_disposes_owned_model(example, monkeypatch):
    original = probe.load_verified_manifest
    calls = 0

    def verify(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ModelAssetError("private-second-model-path")
        return original(*args, **kwargs)

    monkeypatch.setattr(probe, "load_verified_manifest", verify)
    assert probe.main(example.arguments) == 1
    assert example.closed == ["detector"]
    assert "private" not in json.dumps(read_report(example))


def test_failed_write_removes_only_own_partial_files(example, monkeypatch):
    original = Path.open

    def failed_open(path, mode="r", *args, **kwargs):
        if path.name == "result.json" and mode == "xb":
            path.write_bytes(b"concurrent unrelated marker")
            raise FileExistsError("synthetic concurrent collision")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failed_open)
    assert probe.main(example.arguments) == 1
    assert not (example.output / "mesh.glb").exists()
    assert (example.output / "result.json").read_bytes() == b"concurrent unrelated marker"


@pytest.mark.parametrize(
    "values", ["nan", "inf", "-51", "51", "1,1", ",", ",".join(str(x) for x in range(10))]
)
def test_strength_argument_rejects_nonfinite_unbounded_or_ambiguous_values(example, values):
    with pytest.raises(SystemExit) as caught:
        probe.main([*example.arguments, "--strengths=" + values])
    assert caught.value.code == 2 and not example.calls


def test_nonzero_strength_cannot_be_inferred_from_source_age_without_direction(example):
    with pytest.raises(SystemExit) as caught:
        probe.main([*example.arguments, "--source-age", "45", "--strengths=20"])
    assert caught.value.code == 2 and not example.calls


def test_external_uv_cannot_silently_enter_strict_mode(example):
    args = [x for x in example.arguments if x != "--research-allow-unresolved"]
    with pytest.raises(SystemExit) as caught:
        probe.main([*args, "--uv", "fixture.npz", "--uv-sha256", "0" * 64])
    assert caught.value.code == 2 and not example.calls
