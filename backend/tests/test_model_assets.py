"""Small byte fixtures test the verifier, not real model feasibility."""

import hashlib
import json
from pathlib import Path

import pytest

from agemorph3d.model_assets import ModelAssetError, load_verified_manifest


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    content = b"small model verifier fixture"
    (tmp_path / "fixture.onnx").write_bytes(content)
    data = {
        "schema_version": 1,
        "model_id": "fixture-detector",
        "backend": "yolov5_face_onnx",
        "revision": "test-revision",
        "code_license": "fixture-license",
        "code_license_url": "https://example.com/code-license",
        "weights_license": "fixture-license",
        "weights_license_url": "https://example.com/weights-license",
        "license_status": "verified",
        "artifacts": [
            {
                "path": "fixture.onnx",
                "source_url": "https://example.com/fixture.onnx",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "role": "detector",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def change_manifest(path: Path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_verifies_local_bytes_and_preserves_provenance(manifest_path: Path) -> None:
    result = load_verified_manifest(manifest_path)
    assert result.manifest.model_id == "fixture-detector"
    assert result.license_verified
    assert result.paths["detector"] == (manifest_path.parent / "fixture.onnx").resolve()
    assert str(result.manifest.artifacts[0].source_url) == "https://example.com/fixture.onnx"
    with pytest.raises(TypeError):
        result.paths["detector"] = Path("other.onnx")


def test_rejects_same_length_tampering(manifest_path: Path) -> None:
    artifact = manifest_path.parent / "fixture.onnx"
    artifact.write_bytes(b"x" * artifact.stat().st_size)
    with pytest.raises(ModelAssetError, match="SHA-256"):
        load_verified_manifest(manifest_path)


@pytest.mark.parametrize("content", [b"short", b"long" * 100])
def test_rejects_size_mismatch(manifest_path: Path, content: bytes) -> None:
    (manifest_path.parent / "fixture.onnx").write_bytes(content)
    with pytest.raises(ModelAssetError, match="size"):
        load_verified_manifest(manifest_path)


def test_rejects_missing_artifact_without_leaking_path(manifest_path: Path) -> None:
    (manifest_path.parent / "fixture.onnx").unlink()
    with pytest.raises(ModelAssetError, match="missing") as error:
        load_verified_manifest(manifest_path)
    assert str(manifest_path.parent) not in str(error.value)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.onnx",
        "models/../../outside.onnx",
        "/private/model.onnx",
        r"C:\private\model.onnx",
        r"C:model.onnx",
        r"\\server\models\model.onnx",
        "fixture.onnx:stream",
        ".",
    ],
)
def test_rejects_path_escape(manifest_path: Path, unsafe_path: str) -> None:
    change_manifest(manifest_path, lambda data: data["artifacts"][0].update(path=unsafe_path))
    with pytest.raises(ModelAssetError, match="Invalid model asset manifest") as error:
        load_verified_manifest(manifest_path)
    if len(unsafe_path) > 1:
        assert unsafe_path not in str(error.value)


def test_rejects_external_symlink(manifest_path: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.onnx"
    outside.write_bytes(b"external")
    link = tmp_path / "linked.onnx"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating a symbolic link requires host support or permissions.")
    try:
        change_manifest(manifest_path, lambda data: data["artifacts"][0].update(path=link.name))
        with pytest.raises(ModelAssetError, match="outside the manifest directory") as error:
            load_verified_manifest(manifest_path)
        assert str(outside) not in str(error.value)
    finally:
        outside.unlink()


def test_unresolved_license_requires_explicit_research_override(manifest_path: Path) -> None:
    change_manifest(manifest_path, lambda data: data.update(license_status="unresolved"))
    with pytest.raises(ModelAssetError, match="license is unresolved"):
        load_verified_manifest(manifest_path)
    result = load_verified_manifest(manifest_path, research_allow_unresolved=True)
    assert not result.license_verified
    assert result.manifest.license_status == "unresolved"


@pytest.mark.parametrize(
    "artifact_patch",
    [
        {"source_url": "http://example.com/model.onnx"},
        {"sha256": "bad-hash"},
        {"size_bytes": 0},
        {"size_bytes": True},
        {"role": "unknown"},
        {"unexpected": "field"},
    ],
)
def test_rejects_invalid_artifact_schema(manifest_path: Path, artifact_patch: dict) -> None:
    change_manifest(manifest_path, lambda data: data["artifacts"][0].update(artifact_patch))
    with pytest.raises(ModelAssetError, match="Invalid model asset manifest"):
        load_verified_manifest(manifest_path)


def test_rejects_duplicate_roles(manifest_path: Path) -> None:
    change_manifest(manifest_path, lambda data: data["artifacts"].append(data["artifacts"][0]))
    with pytest.raises(ModelAssetError, match="Invalid model asset manifest"):
        load_verified_manifest(manifest_path)


@pytest.mark.parametrize("patch", [{"schema_version": True}, {"unexpected": "field"}])
def test_rejects_invalid_manifest_schema(manifest_path: Path, patch: dict) -> None:
    change_manifest(manifest_path, lambda data: data.update(patch))
    with pytest.raises(ModelAssetError, match="Invalid model asset manifest"):
        load_verified_manifest(manifest_path)


def test_missing_manifest_hides_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ModelAssetError, match="could not be read") as error:
        load_verified_manifest(tmp_path / "private-manifest.json")
    assert str(tmp_path) not in str(error.value)
