"""Read-only checks for the L02 preparation script.

These tests do not install packages, start the real service, or mark L02 passed.
"""

import hashlib
import importlib
import json
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
repro = importlib.import_module("repro_check")

REAL_UV = ROOT / "backend" / "uv.lock"
REAL_NPM = ROOT / "frontend" / "package-lock.json"
VENV_PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"


def test_python_and_node_constraints_come_from_lock_syntax():
    assert repro.python_matches("3.11.16", "==3.11.*")
    assert repro.python_matches("3.11.18", "==3.11.*")
    assert not repro.python_matches("3.12.3", "==3.11.*")
    assert not repro.python_matches(None, "==3.11.*")
    assert repro.node_matches("v22.23.4", ">=22.18.0")
    assert repro.node_matches("v24.14.1", ">=22.18.0")
    assert not repro.node_matches("v22.17.9", ">=22.18.0")
    assert repro.node_matches("v22.18.0", ">=22.12.0 || >=22.18.0")


def test_markers_keep_windows_colorama_and_linux_uvloop():
    linux = repro.marker_env(extra="")
    linux["sys_platform"] = "linux"
    linux["platform_python_implementation"] = "CPython"
    windows = dict(linux)
    windows["sys_platform"] = "win32"
    assert not repro.marker_applies("sys_platform == 'win32'", linux)
    assert repro.marker_applies("sys_platform == 'win32'", windows)
    uvloop = (
        "platform_python_implementation != 'PyPy' and sys_platform != 'cygwin' "
        "and sys_platform != 'win32'"
    )
    assert repro.marker_applies(uvloop, linux)
    assert not repro.marker_applies(uvloop, windows)
    inference = dict(linux)
    inference["extra"] = "inference"
    assert not repro.marker_applies("extra == 'inference'", linux)
    assert repro.marker_applies("extra == 'inference'", inference)


def test_real_lock_selects_platform_packages():
    lock = tomllib.loads(REAL_UV.read_text(encoding="utf-8"))
    linux = repro.marker_env(extra="")
    groups = repro.locked_python_groups(lock, linux)
    required = {}
    required.update(groups["base"])
    required.update(groups["dev"])
    required.update(groups["inference"])
    assert "colorama" not in required
    assert required["uvloop"] == "0.23.0"
    assert required["fastapi"] == "0.146.0"
    assert required["numpy"] == "2.4.6"
    assert lock["requires-python"] == "==3.11.*"
    assert repro.lockfile_hash_gaps(lock) == []
    windows = dict(linux)
    windows["sys_platform"] = "win32"
    win_groups = repro.locked_python_groups(lock, windows)
    win_required = {}
    win_required.update(win_groups["base"])
    win_required.update(win_groups["dev"])
    win_required.update(win_groups["inference"])
    assert "colorama" in win_required
    assert "uvloop" not in win_required


def test_npm_lock_requires_this_platform_only():
    lock = json.loads(REAL_NPM.read_text(encoding="utf-8"))
    host = {"os": "linux", "cpu": "x64", "libc": "glibc"}
    required = [
        key
        for key, entry in lock["packages"].items()
        if isinstance(entry, dict) and repro.npm_package_required(key, entry, host)
    ]
    assert "node_modules/three" in required
    assert "node_modules/@rolldown/binding-linux-x64-gnu" in required
    assert "node_modules/@rolldown/binding-win32-x64-msvc" not in required
    assert lock["packages"][""]["engines"]["node"] == ">=22.18.0"


def test_missing_model_file_has_no_invented_hash(tmp_path):
    manifest = {
        "license_status": "unresolved",
        "artifacts": [
            {
                "path": "weights/model.onnx",
                "sha256": "ab" * 32,
                "size_bytes": 4,
                "role": "detector",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()
    report = repro.inspect_manifest("detector", path)
    assert path.read_bytes() == before
    artifact = report["artifacts"][0]
    assert artifact["status"] == "missing"
    assert artifact["observed_sha256"] is None
    assert report["registered_license_status"] == "unresolved"
    assert report["grants_service_readiness"] is False


def test_model_hash_match_and_mismatch_do_not_rewrite_manifest(tmp_path):
    body = b"onnx"
    digest = hashlib.sha256(body).hexdigest()
    folder = tmp_path / "model"
    folder.mkdir()
    (folder / "model.onnx").write_bytes(body)
    manifest = folder / "manifest.json"
    payload = {
        "license_status": "unresolved",
        "artifacts": [
            {"path": "model.onnx", "sha256": digest, "size_bytes": len(body), "role": "detector"}
        ],
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    matched = repro.inspect_manifest("detector", manifest)
    assert matched["artifacts"][0]["status"] == "match"
    assert matched["artifacts"][0]["observed_sha256"] == digest
    payload["artifacts"][0]["sha256"] = "cd" * 32
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    original = manifest.read_bytes()
    mismatched = repro.inspect_manifest("detector", manifest)
    assert mismatched["artifacts"][0]["status"] == "hash_mismatch"
    assert manifest.read_bytes() == original


def test_unconfigured_model_is_a_gap_not_a_pass(tmp_path):
    report = repro.inspect_manifest("detector", None)
    assert report["configured"] is False
    assert report["manifest_status"] == "not_configured"
    assert report["artifacts"] == []
    assert report["manifest_sha256"] is None


def test_installer_commands_are_refused(tmp_path):
    with pytest.raises(repro.ReproCheckError) as caught:
        repro.run_text(["npm", "ci"], tmp_path, 5)
    assert caught.value.code == "INSTALL_FORBIDDEN"
    with pytest.raises(repro.ReproCheckError):
        repro.run_text(["uv", "sync", "--locked"], tmp_path, 5)


def test_launcher_argv_is_the_existing_entry_without_installers(tmp_path):
    argv = repro.launcher_argv(
        tmp_path,
        tmp_path / "output" / "repro-check" / "state",
        "start",
        mode="production",
        python_executable=tmp_path / "backend" / ".venv" / "bin" / "python",
        node_executable="node",
        detector_manifest=None,
        reconstructor_manifest=None,
    )
    assert Path(argv[2]).name == "local_run.py"
    assert "start" in argv
    assert "--production" in argv
    assert "--research-allow-unresolved" not in argv
    assert all(Path(part).stem.lower() not in repro.INSTALLER_STEMS for part in argv)


def test_smoke_uses_launcher_start_health_stop_without_network_isolation(tmp_path, monkeypatch):
    calls = []

    def launch(argv, _timeout):
        calls.append(list(argv))
        command = argv[3]
        if command == "start":
            return 0, {"operation": "start"}
        return 0, {"operation": "stop"}

    def health():
        return 200, {
            "models": {
                "detector": {"state": "missing", "detail": "尚未配置已核验的模型清单。"},
                "reconstructor": {"state": "missing", "detail": "尚未配置已核验的模型清单。"},
            },
            "capabilities": {
                "reconstruction": False,
                "age_morph": False,
                "age_texture": False,
                "realtime": False,
            },
            "api_version": "1.2",
            "device": "cpu",
            "version": "0.1.0",
        }

    monkeypatch.setattr(repro, "_port_open", lambda _port: False)
    state = tmp_path / "output" / "state" / "dev"
    state.mkdir(parents=True)
    result = repro.run_smoke(
        tmp_path,
        state,
        mode="dev",
        python_executable=tmp_path / "python",
        node_executable="node",
        detector_manifest=None,
        reconstructor_manifest=None,
        isolate=False,
        launch=launch,
        health=health,
    )
    assert [item[3] for item in calls] == ["start", "stop"]
    assert all(Path(item[2]).name == "local_run.py" for item in calls)
    assert result["ok"] is True
    assert result["health_picture"] == "missing"
    assert result["network_isolation"]["status"] == "not_requested"
    assert result["health"]["capabilities"]["age_morph"] is False


def test_report_never_signs_off_l02_and_stays_inside_ignored_output(tmp_path):
    root = tmp_path / "project file"
    (root / "backend").mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "backend" / "uv.lock").write_text(
        'version = 1\nrequires-python = "==3.11.*"\n', encoding="utf-8"
    )
    (root / "frontend" / "package-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {"": {"engines": {"node": ">=22.18.0"}}},
            }
        ),
        encoding="utf-8",
    )
    output = root / "output" / "repro-check" / "report.json"
    code = repro.main(
        ["--root", str(root), "--output", str(output), "--skip-smoke", "--node", "missing-node"]
    )
    assert code == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["l02_executed"] is False
    assert report["l02_signed_off"] is False
    assert report["conclusion"] == "preparation_check_only"
    assert report["installs_dependencies"] is False
    assert report["modifies_manifests"] is False
    assert "passed" not in json.dumps(report["conclusion"])
    with pytest.raises(repro.ReproCheckError) as caught:
        repro.main(
            [
                "--root",
                str(root),
                "--output",
                str(root / "docs" / "report.json"),
                "--skip-smoke",
            ]
        )
    assert caught.value.exit_code == 6


def test_proc_address_parser_treats_loopback_as_local():
    assert repro._proc_ip("0100007F") == "127.0.0.1"
    assert repro._loopback("127.0.0.1")
    assert repro._loopback("0.0.0.0")
    assert not repro._loopback("8.8.8.8")


@pytest.mark.skipif(not VENV_PYTHON.is_file(), reason="project virtualenv is not installed")
def test_installed_environment_matches_lock_files_without_starting_services():
    node = repro.default_node()
    report = repro.build_report(
        ROOT,
        python_executable=VENV_PYTHON,
        node_executable=node,
        detector_manifest=None,
        reconstructor_manifest=None,
        smoke=None,
    )
    assert report["l02_executed"] is False
    assert report["python"]["version"].startswith("3.11.")
    assert report["python_packages"]["missing_count"] == 0
    assert report["python_packages"]["mismatch_count"] == 0
    assert report["npm_packages"]["missing_count"] == 0
    assert report["npm_packages"]["mismatch_count"] == 0
    codes = {item["code"] for item in report["problems"]}
    assert "PYTHON_PACKAGES" not in codes
    assert "NPM_PACKAGES" not in codes
    assert "MODELS_NOT_CONFIGURED" in {item["code"] for item in report["gaps"]}
    before = (ROOT / "backend" / "model-manifests" / "yolov5n05-face.research.json").read_bytes()
    configured = repro.build_report(
        ROOT,
        python_executable=VENV_PYTHON,
        node_executable=node,
        detector_manifest=ROOT / "backend" / "model-manifests" / "yolov5n05-face.research.json",
        reconstructor_manifest=ROOT / "backend" / "model-manifests" / "3ddfa-v2.research.json",
        smoke=None,
    )
    after = (ROOT / "backend" / "model-manifests" / "yolov5n05-face.research.json").read_bytes()
    assert before == after
    assert "ARTIFACT_MISSING" in {item["code"] for item in configured["problems"]}
    artifacts = configured["models"]["detector"]["artifacts"]
    assert artifacts[0]["status"] == "missing"
    assert artifacts[0]["observed_sha256"] is None
