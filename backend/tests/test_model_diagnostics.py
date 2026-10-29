"""Model inventory checks separate integrity, registration and actual readiness."""

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from agemorph3d import model_diagnostics as diagnostics


def make_manifest(tmp_path, role="detector", license_status="unresolved", uv=False):
    folder = tmp_path / role
    folder.mkdir(parents=True, exist_ok=True)
    roles = ["detector"] if role == "detector" else ["regressor", "bfm", "param_stats"]
    if uv:
        roles.append("uv")
    artifacts = []
    for name in roles:
        content = (name + "-NEVER_ECHO_BINARY_CONTENT").encode()
        (folder / f"{name}.bin").write_bytes(content)
        artifacts.append(
            {
                "role": name,
                "path": f"{name}.bin",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "source_url": "https://example.org/research-asset",
            }
        )
    manifest = {
        "schema_version": 1,
        "model_id": "synthetic-model",
        "backend": "yolov5_face_onnx" if role == "detector" else "3ddfa_v2_onnx",
        "revision": "test",
        "code_license": "synthetic",
        "weights_license": "synthetic",
        "code_license_url": "https://example.org/license",
        "weights_license_url": "https://example.org/weights-license",
        "license_status": license_status,
        "artifacts": artifacts,
    }
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_unresolved_registration_does_not_hide_valid_integrity_or_grant_readiness(tmp_path):
    path, manifest = make_manifest(tmp_path)
    before = path.read_bytes()
    result = diagnostics.inspect_model("detector", path)
    assert result["manifest_status"] == "valid"
    assert result["registered_license_status"] == "unresolved"
    assert result["blocking_reasons"] == ["LICENSE_REGISTRATION_UNRESOLVED"]
    assert result["artifacts"][0]["status"] == "verified"
    assert result["artifacts"][0]["observed_sha256"] == manifest["artifacts"][0]["sha256"]
    assert result["strict_load_preconditions_met"] is False
    assert result["operator_selftests_run"] is result["grants_service_readiness"] is False
    assert path.read_bytes() == before
    assert "NEVER_ECHO" not in json.dumps(result) and str(tmp_path) not in json.dumps(result)


def test_all_integrity_failures_reported_even_when_registration_is_unresolved(tmp_path):
    path, _ = make_manifest(tmp_path, "reconstructor")
    (path.parent / "regressor.bin").unlink()
    bfm = path.parent / "bfm.bin"
    bfm.write_bytes(b"x" * bfm.stat().st_size)
    stats = path.parent / "param_stats.bin"
    stats.write_bytes(stats.read_bytes() + b"x")
    result = diagnostics.inspect_model("reconstructor", path)
    assert [a["status"] for a in result["artifacts"]] == [
        "missing",
        "hash_mismatch",
        "size_mismatch",
    ]
    assert result["blocking_reasons"] == [
        "LICENSE_REGISTRATION_UNRESOLVED",
        "ARTIFACT_INTEGRITY_FAILED",
    ]


def test_registered_and_intact_is_only_a_load_precondition_never_operator_or_service_ready(
    tmp_path, monkeypatch
):
    from agemorph3d import model_lifecycle

    def forbidden(*args, **kwargs):
        raise AssertionError("No model loader or inference is allowed in diagnostics")

    monkeypatch.setattr(model_lifecycle, "load_model", forbidden)
    detector, _ = make_manifest(tmp_path, license_status="verified")
    reconstructor, _ = make_manifest(tmp_path, "reconstructor", "verified", uv=True)
    result = diagnostics.diagnose(detector, reconstructor)
    assert result["status"] == "preconditions_met"
    assert all(m["strict_load_preconditions_met"] for m in result["models"])
    assert result["model_inference"] is result["operator_selftests_run"] is False
    assert result["grants_service_readiness"] is result["observes_running_service"] is False


@pytest.mark.parametrize("kind", ["backend", "role_set", "unknown_field", "duplicate_role"])
def test_manifest_role_and_schema_conflicts_do_not_pass(tmp_path, kind):
    path, data = make_manifest(tmp_path, license_status="verified")
    if kind == "backend":
        data["backend"] = "3ddfa_v2_onnx"
    elif kind == "role_set":
        data["artifacts"][0]["role"] = "bfm"
    elif kind == "unknown_field":
        data["private_extra"] = "NEVER_ECHO_MARKER"
    else:
        data["artifacts"].append(dict(data["artifacts"][0]))
    path.write_text(json.dumps(data), encoding="utf-8")
    result = diagnostics.inspect_model("detector", path)
    assert result["strict_load_preconditions_met"] is False
    assert result["blocking_reasons"]
    assert "NEVER_ECHO" not in json.dumps(result)


def test_unconfigured_missing_invalid_and_oversized_manifests_remain_distinct(tmp_path):
    assert diagnostics.inspect_model("detector", None)["manifest_status"] == "unconfigured"
    assert (
        diagnostics.inspect_model("detector", tmp_path / "absent.json")["manifest_status"]
        == "missing"
    )
    path = tmp_path / "bad.json"
    path.write_bytes(b'{"invalid":"NEVER_ECHO_MARKER",')
    invalid = diagnostics.inspect_model("detector", path)
    assert invalid["manifest_status"] == "invalid" and "NEVER_ECHO" not in json.dumps(invalid)
    path.write_bytes(b"x" * (diagnostics.MAX_MANIFEST_BYTES + 1))
    assert diagnostics.inspect_model("detector", path)["manifest_status"] == "oversized"
    assert diagnostics.inspect_model("detector", tmp_path)["manifest_status"] == "invalid"


@pytest.mark.parametrize("unsafe", ["../outside.bin", "C:/private.bin", "/private.bin"])
def test_traversal_manifests_are_rejected_before_artifact_read(tmp_path, unsafe):
    path, data = make_manifest(tmp_path)
    data["artifacts"][0]["path"] = unsafe
    path.write_text(json.dumps(data), encoding="utf-8")
    result = diagnostics.inspect_model("detector", path)
    assert result["manifest_status"] == "invalid" and not result["artifacts"]


def test_symlink_outside_manifest_is_not_read(tmp_path):
    path, data = make_manifest(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"NEVER_ECHO_MARKER")
    link = path.parent / "linked.bin"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Host cannot create test symlinks")
    data["artifacts"][0]["path"] = link.name
    path.write_text(json.dumps(data), encoding="utf-8")
    assert (
        diagnostics.inspect_model("detector", path)["artifacts"][0]["status"]
        == "outside_manifest_directory"
    )


def test_nonregular_artifact_and_read_error_are_sanitized(tmp_path, monkeypatch):
    path, data = make_manifest(tmp_path)
    artifact = path.parent / data["artifacts"][0]["path"]
    artifact.unlink()
    artifact.mkdir()
    assert (
        diagnostics.inspect_model("detector", path)["artifacts"][0]["status"] == "not_regular_file"
    )
    artifact.rmdir()
    artifact.write_bytes(b"x" * data["artifacts"][0]["size_bytes"])
    old_open = Path.open

    def fail(target, *args, **kwargs):
        if target == artifact:
            raise OSError("NEVER_ECHO_MARKER")
        return old_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    result = diagnostics.inspect_model("detector", path)
    assert result["artifacts"][0]["status"] == "unreadable"
    assert "NEVER_ECHO" not in json.dumps(result)


def test_changed_artifact_cannot_pass_snapshot_check(tmp_path, monkeypatch):
    path, _ = make_manifest(tmp_path, license_status="verified")
    old_stamp = diagnostics._stamp
    calls = 0

    def changed(target):
        nonlocal calls
        calls += 1
        dev, ino, size, mtime = old_stamp(target)
        return dev, ino, size, mtime + calls

    monkeypatch.setattr(diagnostics, "_stamp", changed)
    result = diagnostics.inspect_model("detector", path)
    assert result["artifacts"][0]["status"] == "changed_during_check"
    assert result["strict_load_preconditions_met"] is False


def test_growing_artifact_read_is_bounded_to_declared_size_plus_one(tmp_path, monkeypatch):
    path, data = make_manifest(tmp_path)
    artifact = path.parent / data["artifacts"][0]["path"]
    amount = data["artifacts"][0]["size_bytes"]
    requests = []
    old_open = Path.open

    class Growing(io.BytesIO):
        def read(self, size=-1):
            requests.append(size)
            return super().read(size)

    def opened(target, *args, **kwargs):
        if target == artifact:
            return Growing(b"x" * (amount + 10000))
        return old_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    result = diagnostics.inspect_model("detector", path)
    assert requests == [amount + 1]
    assert result["artifacts"][0]["status"] == "changed_during_check"


def test_manifest_change_during_integrity_scan_invalidates_preconditions(tmp_path, monkeypatch):
    path, _ = make_manifest(tmp_path, license_status="verified")
    original = diagnostics._artifact

    def changed(root, artifact):
        result = original(root, artifact)
        path.write_text("{}", encoding="utf-8")
        return result

    monkeypatch.setattr(diagnostics, "_artifact", changed)
    result = diagnostics.inspect_model("detector", path)
    assert result["manifest_status"] == "changed_during_check"
    assert "MANIFEST_CHANGED_DURING_CHECK" in result["blocking_reasons"]


def test_cli_environment_and_explicit_override_report_blockers_without_running_server(tmp_path):
    path, _ = make_manifest(tmp_path)
    root = Path(__file__).resolve().parents[2]
    env = dict(
        os.environ,
        PYTHONPATH=str(root / "backend/src"),
        AGEMORPH_DETECTOR_MANIFEST=str(tmp_path / "env-missing.json"),
    )
    env.pop("AGEMORPH_RECONSTRUCTOR_MANIFEST", None)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "agemorph3d.model_diagnostics",
            "--detector-manifest",
            str(path),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["models"][0]["manifest_status"] == "valid"
    assert data["models"][1]["manifest_status"] == "unconfigured"
    assert data["status"] == "blocked" and not data["grants_service_readiness"]
    assert result.stderr == b"" and b"NEVER_ECHO" not in result.stdout


def test_cli_success_means_preconditions_only_and_missing_configuration_is_blocked(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("AGEMORPH_DETECTOR_MANIFEST", raising=False)
    monkeypatch.delenv("AGEMORPH_RECONSTRUCTOR_MANIFEST", raising=False)
    assert diagnostics.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    detector, _ = make_manifest(tmp_path, license_status="verified")
    reconstructor, _ = make_manifest(tmp_path, "reconstructor", "verified")
    assert (
        diagnostics.main(
            ["--detector-manifest", str(detector), "--reconstructor-manifest", str(reconstructor)]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "preconditions_met" and not result["grants_service_readiness"]
