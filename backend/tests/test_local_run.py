"""Path, ownership and lifecycle boundaries for the local run entry.

These tests use ephemeral loopback ports and fake processes. They do not load
models, write manifests, or install dependencies. The fixed 8000/5173 stack is
opt-in through AGEMORPH_LOCAL_RUN_LIVE=1.
"""

import importlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
local_run = importlib.import_module("tools.local_run")

SERVER = r"""
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port = int(sys.argv[1])
child_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else ""
request_log = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else ""
if child_path:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    with open(child_path, "w", encoding="utf-8") as handle:
        handle.write(str(child.pid))

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if request_log:
            with open(request_log, "a", encoding="utf-8") as handle:
                handle.write(path + "\n")
        ready = os.environ.get("FAKE_READY") == "1"
        if path == "/api/health":
            body = json.dumps(
                {
                    "models": {
                        "detector": {
                            "state": "ready" if ready else "missing",
                            "backend": None,
                            "provider": None,
                            "detail": "reported-by-fake-service",
                        },
                        "reconstructor": {
                            "state": "ready" if ready else "missing",
                            "backend": None,
                            "provider": None,
                            "detail": "reported-by-fake-service",
                        },
                    },
                    "device": "cpu",
                    "version": "test",
                    "api_version": "1.2",
                    "capabilities": {
                        "reconstruction": ready,
                        "age_morph": False,
                        "age_texture": False,
                        "realtime": ready,
                    },
                }
            ).encode()
        else:
            body = b"frontend-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return

class Server(ThreadingHTTPServer):
    allow_reuse_address = True

Server(("127.0.0.1", port), Handler).serve_forever()
"""

FAKE_PYTHON = r"""
import sys

code = sys.argv[sys.argv.index("-c") + 1]
if "sys.version" in code:
    print("3.11.16")
    raise SystemExit(0)
print("ModuleNotFoundError: No module named 'fastapi'", file=sys.stderr)
raise SystemExit(1)
"""


def running(pid: int) -> bool:
    observed = local_run.observe(pid)
    return observed is not None and observed.get("state") != "Z"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project file"
    (root / "backend").mkdir(parents=True)
    (root / "frontend").mkdir()
    state = root / "output" / "local-run"
    state.mkdir(parents=True)
    return root, state


def write_server(root: Path) -> Path:
    path = root / "serve helper.py"
    path.write_text(SERVER, encoding="utf-8")
    return path


def make_plan(root: Path, state: Path, server: Path, **kwargs) -> object:
    backend_port = kwargs.pop("backend_port", free_port())
    frontend_port = kwargs.pop("frontend_port", free_port())
    child = kwargs.pop("child_path", "")
    request_log = kwargs.pop("request_log", "")
    backend_argv = kwargs.pop(
        "backend_argv",
        [sys.executable, str(server), str(backend_port), child or "-", request_log or "-"],
    )
    frontend_argv = kwargs.pop(
        "frontend_argv",
        [sys.executable, str(server), str(frontend_port), "-", request_log or "-"],
    )
    return local_run.Plan(
        root=root,
        state_dir=state,
        python_executable=Path(kwargs.pop("python_executable", sys.executable)),
        node_executable=kwargs.pop("node_executable", sys.executable),
        roles=kwargs.pop("roles", ("backend", "frontend")),
        backend_port=backend_port,
        frontend_port=frontend_port,
        startup_timeout=kwargs.pop("startup_timeout", 3),
        stop_grace_seconds=kwargs.pop("stop_grace_seconds", 1),
        allow_ephemeral_ports=True,
        dependency_probe=kwargs.pop("dependency_probe", False),
        backend_argv=backend_argv,
        frontend_argv=frontend_argv,
        mode=kwargs.pop("mode", "dev"),
        run_build=kwargs.pop("run_build", False),
        detector_manifest=kwargs.pop("detector_manifest", None),
        reconstructor_manifest=kwargs.pop("reconstructor_manifest", None),
    )


def stop_quiet(plan) -> None:
    try:
        local_run.stop_services(plan)
    except local_run.LocalRunError:
        pass


def test_state_dir_must_stay_inside_ignored_project_directories(tmp_path):
    root, _state = workspace(tmp_path)
    with pytest.raises(local_run.LocalRunError) as caught:
        local_run.resolve_state_dir(root, root / "docs" / "local-run")
    assert caught.value.code == "STATE_DIR_NOT_IGNORED"
    assert not (root / "docs").exists()
    with pytest.raises(local_run.LocalRunError) as outside:
        local_run.resolve_state_dir(root, tmp_path / "elsewhere")
    assert outside.value.code == "STATE_DIR_OUTSIDE_PROJECT"
    resolved = local_run.resolve_state_dir(root, Path("output") / "local-run")
    assert resolved == (root / "output" / "local-run").resolve()
    logs = local_run.resolve_state_dir(root, root / "logs" / "session")
    assert logs == (root / "logs" / "session").resolve()


def test_supported_commands_keep_loopback_ports_and_do_not_grant_readiness():
    python = Path("D:/project file/AgeMorph3D/backend/.venv/Scripts/python.exe")
    node = "D:/JAVA run tools/node.exe"
    root = Path("D:/project file/AgeMorph3D")
    assert local_run.production_backend_argv(python) == [str(python), "-B", "-m", "agemorph3d"]
    frontend = local_run.development_frontend_argv(node, root)
    assert frontend[:2] == [node, str(root / "frontend/node_modules/vite/bin/vite.js")]
    assert frontend[2:] == ["--host", "127.0.0.1", "--port", "5173", "--strictPort"]
    assert "--research-allow-unresolved" not in frontend
    build = local_run.frontend_build_commands(node, root)
    assert build[0][2:5] == ["--noEmit", "--pretty", "false"]
    assert build[1][-1] == "build"
    assert all("npm" not in part for command in build for part in command)
    static = local_run.static_frontend_argv(
        python, root / "frontend" / "dist", local_run.PRODUCTION_FRONTEND_PORT
    )
    assert static[2].endswith("local_static_server.py")
    assert static[-1] == "4173"
    assert "5173" not in static
    source = Path(local_run.__file__).read_text(encoding="utf-8")
    assert 'launcher_grants_ready": True' not in source
    assert "shell=True" not in source
    with pytest.raises(local_run.LocalRunError) as host:
        local_run.Plan(
            root=root,
            state_dir=root / "output" / "local-run",
            python_executable=python,
            node_executable=node,
            roles=("backend",),
            host="0.0.0.0",
        )
    assert host.value.code == "HOST_NOT_LOOPBACK"
    with pytest.raises(local_run.LocalRunError) as port:
        local_run.Plan(
            root=root,
            state_dir=root / "output" / "local-run",
            python_executable=python,
            node_executable=node,
            roles=("backend",),
            backend_port=8001,
        )
    assert port.value.code == "PORT_FIXED"
    flags = local_run.windows_background_settings()
    assert flags["creationflags"] & local_run.CREATE_NO_WINDOW
    assert flags["creationflags"] & local_run.CREATE_NEW_PROCESS_GROUP
    assert flags["startup_flags"] == local_run.STARTF_USESHOWWINDOW
    assert flags["show_window"] == local_run.SW_HIDE
    if os.name != "nt":
        assert local_run.hidden_spawn_kwargs()["start_new_session"] is True


def test_identity_match_rejects_reuse_and_foreign_command_lines():
    stored = {
        "pid": 10,
        "creation_token": "100",
        "executable": "/tmp/project file/python",
        "argv": ["/tmp/project file/python", "-B", "-m", "agemorph3d"],
        "owner_token": "token",
        "role": "backend",
    }
    observed = {
        "pid": 10,
        "state": "S",
        "creation": "100",
        "executable": "/tmp/project file/python",
        "argv": ["/tmp/project file/python", "-B", "-m", "agemorph3d"],
        "owner_token": "token",
        "role": "backend",
    }
    assert local_run.identity_matches(stored, observed)
    for change in (
        {"creation": "101"},
        {"owner_token": "other"},
        {"owner_token": None},
        {"argv": ["/tmp/project file/python", "-B", "-m", "other"]},
        {"executable": "/usr/bin/other"},
        {"role": "frontend"},
        {"pid": 11},
        {"state": "Z"},
    ):
        assert not local_run.identity_matches(stored, {**observed, **change})
    assert not local_run.identity_matches(stored, None)
    block = b"AGEMORPH_LOCAL_RUN_OWNER=token\0AGEMORPH_LOCAL_RUN_ROLE=backend\0\0"
    parsed = local_run.parse_environment_block(block, encoding="utf-8")
    assert parsed[local_run.OWNER_ENV] == "token"
    wide = "A=1\0AGEMORPH_LOCAL_RUN_OWNER=token\0\0".encode("utf-16-le")
    assert (
        local_run.parse_environment_block(wide, encoding="utf-16-le")[local_run.OWNER_ENV]
        == "token"
    )


def test_missing_interpreter_and_imports_do_not_spawn_or_install(tmp_path, monkeypatch):
    root, state = workspace(tmp_path)
    fake = root / "tools dir" / "python"
    fake.parent.mkdir()
    fake.write_text("#!/usr/bin/env python3\n" + FAKE_PYTHON, encoding="utf-8")
    fake.chmod(0o755)
    calls = []
    real_run = subprocess.run

    def record(argv, *args, **kwargs):
        calls.append((list(argv), kwargs.get("shell")))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(local_run.subprocess, "run", record)
    code = local_run.main(
        [
            "check",
            "--root",
            str(root),
            "--state-dir",
            str(state),
            "--python",
            str(fake),
            "--backend-only",
        ]
    )
    assert code == 2
    assert calls
    assert all(shell is False for _argv, shell in calls)
    joined = " ".join(" ".join(argv) for argv, _shell in calls)
    assert "pip" not in joined and "npm" not in joined and " uv " not in joined
    assert all(
        Path(argv[0]).stem.lower() not in local_run.FORBIDDEN_STEMS for argv, _shell in calls
    )


def test_check_cli_reports_missing_runtime_without_creating_a_service(tmp_path, capsys):
    root, state = workspace(tmp_path)
    fake = root / "venv path" / "python"
    fake.parent.mkdir()
    fake.write_text("#!/usr/bin/env python3\n" + FAKE_PYTHON, encoding="utf-8")
    fake.chmod(0o755)
    code = local_run.main(
        [
            "check",
            "--root",
            str(root),
            "--state-dir",
            str(state),
            "--python",
            str(fake),
            "--backend-only",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["installs_dependencies"] is False
    assert payload["launcher_grants_ready"] is False
    assert payload["launcher_grants_aging"] is False
    assert payload["backend_imports"]["ok"] is False
    assert "fastapi" in " ".join(payload["backend_imports"]["missing"])
    assert payload["python"]["version"] == "3.11.16"
    assert (
        not (state / "state.json").exists()
        or json.loads((state / "state.json").read_text())["services"] == {}
    )


def test_port_owned_by_a_stranger_is_not_cleared(tmp_path):
    root, state = workspace(tmp_path)
    server = write_server(root)
    plan = make_plan(root, state, server, roles=("backend",))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", plan.backend_port))
    sock.listen(1)
    try:
        with pytest.raises(local_run.LocalRunError) as caught:
            local_run.start_services(plan)
        assert caught.value.code == "PORT_IN_USE"
        assert local_run.load_state(state)["services"] == {}
        assert sock.getsockname()[1] == plan.backend_port
        sock.settimeout(0.2)
        try:
            queued, _addr = sock.accept()
            queued.close()
        except TimeoutError:
            pass
        client = socket.create_connection(("127.0.0.1", plan.backend_port), timeout=1)
        client.close()
    finally:
        sock.close()


def test_duplicate_start_keeps_the_original_process(tmp_path):
    root, state = workspace(tmp_path)
    server = write_server(root)
    plan = make_plan(root, state, server, roles=("backend",))
    try:
        started = local_run.start_services(plan)
        pid = started["status"]["services"]["backend"]["process"]["pid"]
        with pytest.raises(local_run.LocalRunError) as caught:
            local_run.start_services(plan)
        assert caught.value.code == "ALREADY_RUNNING"
        assert local_run.load_state(state)["services"]["backend"]["pid"] == pid
        assert running(pid)
        status, _body = local_run.http_probe("127.0.0.1", plan.backend_port, "/api/health")
        assert status == 200
    finally:
        stop_quiet(plan)


def test_partial_frontend_failure_rolls_back_backend_and_its_child(tmp_path):
    root, state = workspace(tmp_path)
    server = write_server(root)
    child_path = root / "child pid.txt"
    plan = make_plan(
        root,
        state,
        server,
        roles=("backend", "frontend"),
        child_path=str(child_path),
        frontend_argv=[sys.executable, "-c", "import sys; sys.exit(3)"],
    )
    try:
        with pytest.raises(local_run.LocalRunError) as caught:
            local_run.start_services(plan)
        assert caught.value.exit_code == 5
        assert local_run.load_state(state)["services"] == {}
        assert not local_run.port_accepting("127.0.0.1", plan.backend_port)
        assert child_path.is_file()
        assert not running(int(child_path.read_text(encoding="utf-8")))
    finally:
        stop_quiet(plan)


def test_stop_refuses_foreign_pid_and_then_restarts_owned_service(tmp_path):
    root, state = workspace(tmp_path)
    server = write_server(root)
    request_log = root / "requests.txt"
    plan = make_plan(root, state, server, roles=("backend",), request_log=str(request_log))
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        local_run.start_services(plan)
        owned = local_run.load_state(state)["services"]["backend"]["pid"]
        saved = json.loads((state / "state.json").read_text(encoding="utf-8"))
        tampered = json.loads(json.dumps(saved))
        tampered["services"]["backend"]["pid"] = stranger.pid
        local_run.save_state(state, tampered)
        with pytest.raises(local_run.LocalRunError) as caught:
            local_run.stop_services(plan)
        assert caught.value.exit_code == 4
        assert running(stranger.pid)
        assert running(owned)
        local_run.save_state(state, saved)
        stopped = local_run.stop_services(plan)
        assert stopped["results"]["backend"]["result"] == "stopped"
        assert stopped["killed_unknown_listeners"] is False
        assert stopped["launcher_grants_aging"] is False
        assert not running(owned)
        assert running(stranger.pid)
        assert not local_run.port_accepting("127.0.0.1", plan.backend_port)
        restarted = local_run.start_services(plan)
        new_pid = restarted["status"]["services"]["backend"]["process"]["pid"]
        assert new_pid != owned
        assert running(new_pid)
        report = local_run.status_report(plan)
        http = report["services"]["backend"]["http"]
        assert http["http_reachable"] is True
        assert http["service_reported_capabilities"]["reconstruction"] is False
        assert http["launcher_grants_ready"] is False
        assert "/api/aging" not in request_log.read_text(encoding="utf-8")
    finally:
        stop_quiet(plan)
        stranger.kill()
        stranger.wait(timeout=2)


def test_status_reports_service_claims_without_granting_them(tmp_path, monkeypatch):
    root, state = workspace(tmp_path)
    server = write_server(root)
    monkeypatch.setenv("FAKE_READY", "1")
    plan = make_plan(root, state, server, roles=("backend",))
    try:
        local_run.start_services(plan)
        report = local_run.status_report(plan)
        http = report["services"]["backend"]["http"]
        assert http["service_reported_capabilities"]["reconstruction"] is True
        assert http["service_health"]["models"]["detector"]["state"] == "ready"
        assert report["launcher_grants_ready"] is False
        assert report["launcher_grants_aging"] is False
        assert report["http_reachable_is_model_ready"] is False
        assert http["launcher_grants_ready"] is False
    finally:
        stop_quiet(plan)


def test_owned_stop_does_not_close_a_different_listener(tmp_path):
    root, state = workspace(tmp_path)
    server = write_server(root)
    plan = make_plan(root, state, server, roles=("backend",))
    other_port = free_port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", other_port))
    sock.listen(1)
    try:
        local_run.start_services(plan)
        local_run.stop_services(plan)
        assert not local_run.port_accepting("127.0.0.1", plan.backend_port)
        client = socket.create_connection(("127.0.0.1", other_port), timeout=1)
        client.close()
    finally:
        stop_quiet(plan)
        sock.close()


def test_second_command_does_not_take_the_state_lock(tmp_path):
    root, state = workspace(tmp_path)
    with local_run.state_lock(state):
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(local_run.__file__).resolve()),
                "status",
                "--root",
                str(root),
                "--state-dir",
                str(state),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    assert completed.returncode == 3
    assert "LOCK_HELD" in completed.stdout
    assert "launcher_grants_ready" in completed.stdout


def test_diagnose_forwards_manifests_without_writing_or_granting_ready(tmp_path, capsys):
    root, state = workspace(tmp_path)
    package = root / "backend" / "agemorph3d"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "model_diagnostics.py").write_text(
        "import json, sys\n"
        "print(json.dumps({'status':'blocked','grants_service_readiness':True,"
        "'models':[{'role':'detector','manifest_status':'unconfigured',"
        "'blocking_reasons':['MANIFEST_NOT_CONFIGURED']}],"
        "'operator_selftests_run':False}))\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    manifest = root / "manifest.json"
    body = b'{"license_status":"unresolved","do_not_touch":true}\n'
    manifest.write_bytes(body)
    manifest.chmod(0o444)
    code = local_run.main(
        [
            "diagnose",
            "--root",
            str(root),
            "--state-dir",
            str(state),
            "--python",
            sys.executable,
            "--backend-only",
            "--detector-manifest",
            str(manifest),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert manifest.read_bytes() == body
    assert payload["launcher_grants_ready"] is False
    assert payload["launcher_grants_aging"] is False
    assert payload["manifests_modified_by_launcher"] is False
    assert payload["diagnostics"]["grants_service_readiness"] is True
    assert payload["diagnostics"]["models"][0]["blocking_reasons"] == ["MANIFEST_NOT_CONFIGURED"]
    assert payload["reported_grant_is_not_launcher_authorization"] is True


def test_diagnose_resolves_relative_manifests_from_the_project_root(tmp_path, capsys):
    root, state = workspace(tmp_path)
    package = root / "backend" / "agemorph3d"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "model_diagnostics.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "flag = '--detector-manifest'\n"
        "path = sys.argv[sys.argv.index(flag) + 1]\n"
        "print(json.dumps({'status':'blocked','grants_service_readiness':False,"
        "'seen_path':path,'seen_is_file':Path(path).is_file(),"
        "'models':[{'role':'detector','manifest_status':'valid',"
        "'blocking_reasons':['LICENSE_REGISTRATION_UNRESOLVED'],"
        "'grants_service_readiness':False}],"
        "'operator_selftests_run':False}))\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    manifest = root / "data" / "models" / "yolov5n05-face" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    body = b'{"license_status":"unresolved"}\n'
    manifest.write_bytes(body)
    manifest.chmod(0o444)
    code = local_run.main(
        [
            "diagnose",
            "--root",
            str(root),
            "--state-dir",
            str(state),
            "--python",
            sys.executable,
            "--backend-only",
            "--detector-manifest",
            "data/models/yolov5n05-face/manifest.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    seen = Path(payload["diagnostics"]["seen_path"])
    assert code == 1
    assert seen.is_absolute()
    assert seen == manifest.resolve()
    assert payload["diagnostics"]["seen_is_file"] is True
    assert payload["diagnostics"]["models"][0]["blocking_reasons"] == [
        "LICENSE_REGISTRATION_UNRESOLVED"
    ]
    assert manifest.read_bytes() == body
    assert local_run.resolve_manifest_argument(root, Path("data/models/a.json")) == str(
        (root / "data/models/a.json").resolve()
    )


def test_partial_environment_read_keeps_owner_when_a_large_read_would_fail():
    text = f"PATH=C:\\\\Windows\0{local_run.OWNER_ENV}=abc123\0{local_run.ROLE_ENV}=backend\0\0"
    encoded = text.encode("utf-16-le")
    blob = encoded + b"\x00" * (17920 - len(encoded))
    base = 0x30000 + 100

    def reader(address, size):
        if size > local_run._MEMORY_PAGE:
            return b""
        start = address - base
        if start < 0 or start >= len(blob) or size <= 0:
            return b""
        return blob[start : start + min(size, len(blob) - start)]

    assert reader(base, 128 * 1024) == b""
    copied = local_run.read_available_memory(reader, base, 128 * 1024)
    assert len(copied) == 17920
    parsed = local_run.terminated_utf16_environment(copied)
    assert parsed[local_run.OWNER_ENV] == "abc123"
    assert parsed[local_run.ROLE_ENV] == "backend"
    truncated = f"{local_run.OWNER_ENV}=abc123".encode("utf-16-le")
    assert local_run.terminated_utf16_environment(truncated) is None
    short = local_run.read_available_memory(
        lambda address, size: truncated[:size] if address == base else b"",
        base,
        128 * 1024,
    )
    assert local_run.terminated_utf16_environment(short) is None


def test_command_line_read_crosses_a_page_and_fails_closed_when_short():
    command = "D:\\project file\\AgeMorph3D\\backend\\.venv\\Scripts\\python.exe -B -m agemorph3d"
    blob = command.encode("utf-16-le")
    base = 4096 - 30

    def reader(blob_bytes):
        def read(address, size):
            start = address - base
            if start < 0 or start >= len(blob_bytes) or size <= 0:
                return b""
            return blob_bytes[start : start + min(size, len(blob_bytes) - start)]

        return read

    assert local_run.read_exact_memory(reader(blob), base, len(blob)) == blob
    assert local_run.read_exact_memory(reader(blob[:40]), base, len(blob)) is None


def test_manifest_flags_are_rejected_outside_diagnose(tmp_path, capsys):
    root, state = workspace(tmp_path)
    code = local_run.main(
        [
            "stop",
            "--root",
            str(root),
            "--state-dir",
            str(state),
            "--detector-manifest",
            str(root / "manifest.json"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 6
    assert payload["code"] == "MANIFEST_FLAG_SCOPE"
    assert local_run.load_state(state)["services"] == {}


def test_spawn_rejects_install_commands_and_research_bypass():
    with pytest.raises(local_run.LocalRunError) as install:
        local_run.assert_spawn_allowed(["/usr/bin/pip", "install", "fastapi"])
    assert install.value.code == "INSTALL_OR_SHELL_FORBIDDEN"
    with pytest.raises(local_run.LocalRunError) as bypass:
        local_run.assert_spawn_allowed(
            [sys.executable, "-m", "agemorph3d.static_probe", "--research-allow-unresolved"]
        )
    assert bypass.value.code == "RESEARCH_BYPASS_FORBIDDEN"


@pytest.mark.skipif(
    os.environ.get("AGEMORPH_LOCAL_RUN_LIVE") != "1",
    reason="set AGEMORPH_LOCAL_RUN_LIVE=1 to exercise the real 8000/5173 commands",
)
def test_static_server_stays_inside_its_directory(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("built-page", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("do-not-serve", encoding="utf-8")
    port = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-B",
            str(ROOT / "tools" / "local_static_server.py"),
            "--directory",
            str(dist),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 3
        status = None
        while time.monotonic() < deadline:
            status, body = local_run.http_probe("127.0.0.1", port, "/index.html")
            if status == 200:
                break
            time.sleep(0.05)
        assert status == 200
        assert body == b"built-page"

        def raw_get(target: str) -> bytes:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                sock.sendall(f"GET {target} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
                return sock.recv(4096)

        assert b"do-not-serve" not in raw_get("/../secret.txt")
        assert b"do-not-serve" not in raw_get("/%2e%2e/secret.txt")
    finally:
        proc.terminate()
        proc.wait(timeout=2)


def test_production_start_builds_passes_model_path_and_cleans_up(tmp_path, monkeypatch):
    root, state = workspace(tmp_path)
    server = write_server(root)
    manifest = root / "data" / "models" / "yolov5n05-face" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    body = b'{"license_status":"unresolved"}\n'
    manifest.write_bytes(body)
    manifest.chmod(0o444)
    calls = []

    def fake_build(plan):
        calls.append(local_run.frontend_build_commands(plan.node_executable, plan.root))
        dist = plan.root / "frontend" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("production-html", encoding="utf-8")
        return {"ran": True, "returncodes": [0, 0], "index": str(dist / "index.html")}

    monkeypatch.setattr(local_run, "build_frontend", fake_build)
    plan = make_plan(
        root,
        state,
        server,
        roles=("backend", "frontend"),
        mode="production",
        run_build=True,
        frontend_argv=None,
        detector_manifest=str(manifest.resolve()),
    )
    try:
        started = local_run.start_services(plan)
        assert calls and calls[0][1][-1] == "build"
        assert started["mode"] == "production"
        assert started["launcher_grants_ready"] is False
        assert started["model_paths"]["detector"]["exists"] is True
        assert started["model_paths"]["launcher_grants_aging"] is False
        pid = started["status"]["services"]["backend"]["process"]["pid"]
        environ = local_run.parse_environment_block(
            Path(f"/proc/{pid}/environ").read_bytes(), encoding="utf-8"
        )
        assert environ["AGEMORPH_DETECTOR_MANIFEST"] == str(manifest.resolve())
        assert manifest.read_bytes() == body
        page, page_body = local_run.http_probe("127.0.0.1", plan.frontend_port, "/index.html")
        assert page == 200 and page_body == b"production-html"
        other = make_plan(
            root,
            state,
            server,
            roles=("backend", "frontend"),
            mode="dev",
            frontend_port=free_port(),
            backend_port=free_port(),
        )
        stopped = local_run.stop_services(other)
        assert stopped["ports"]["frontend"]["port"] == plan.frontend_port
        assert stopped["results"]["backend"]["result"] == "stopped"
        assert stopped["results"]["frontend"]["result"] == "stopped"
        assert not local_run.port_accepting("127.0.0.1", plan.backend_port)
        assert not local_run.port_accepting("127.0.0.1", plan.frontend_port)
        assert not running(pid)
    finally:
        stop_quiet(plan)


def test_failed_production_build_starts_nothing(tmp_path, monkeypatch):
    root, state = workspace(tmp_path)
    server = write_server(root)

    def fake_build(_plan):
        raise local_run.LocalRunError("BUILD_FAILED", "构建失败。", 5)

    monkeypatch.setattr(local_run, "build_frontend", fake_build)
    monkeypatch.setattr(
        local_run.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("spawned")),
    )
    plan = make_plan(root, state, server, mode="production", run_build=True, roles=("frontend",))
    with pytest.raises(local_run.LocalRunError) as caught:
        local_run.start_services(plan)
    assert caught.value.code == "BUILD_FAILED"
    assert local_run.load_state(state)["services"] == {}


def test_real_stack_start_stop_restart(tmp_path):
    root = local_run.project_root()
    python = local_run.default_python(root)
    node = local_run.default_node()
    vite = root / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    if not python.is_file() or not vite.is_file() or not local_run.executable_exists(node):
        pytest.skip("project interpreter or Vite entry is not installed")
    if local_run.port_accepting("127.0.0.1", 8000) or local_run.port_accepting("127.0.0.1", 5173):
        pytest.skip("8000 or 5173 is already in use")
    state = tmp_path / "output" / "local-run"
    plan = local_run.Plan(
        root=root,
        state_dir=state,
        python_executable=python,
        node_executable=node,
        roles=("backend", "frontend"),
        startup_timeout=30,
        stop_grace_seconds=5,
    )
    try:
        started = local_run.start_services(plan)
        health = started["status"]["services"]["backend"]["http"]["service_health"]
        assert health["capabilities"]["age_morph"] is False
        assert health["capabilities"]["age_texture"] is False
        assert started["launcher_grants_ready"] is False
        status, body = local_run.http_probe("127.0.0.1", 5173, "/")
        assert status == 200 and body
        aging = subprocess.run(
            [
                str(python),
                "-B",
                "-c",
                "import json,urllib.request; "
                "req=urllib.request.Request('http://127.0.0.1:8000/api/aging',"
                "data=json.dumps({'mesh_id':'abc','age':30}).encode(),"
                "headers={'Content-Type':'application/json'},method='POST'); "
                "\ntry:\n r=urllib.request.urlopen(req, timeout=5)\n print(r.status)\n"
                "except Exception as e:\n print(getattr(e,'code',type(e).__name__))\n",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert aging.stdout.strip() == "503"
        local_run.stop_services(plan)
        assert not local_run.port_accepting("127.0.0.1", 8000)
        assert not local_run.port_accepting("127.0.0.1", 5173)
        local_run.start_services(plan)
        status, body = local_run.http_probe("127.0.0.1", 8000, "/api/health")
        assert status == 200
        assert json.loads(body)["capabilities"]["age_morph"] is False
    finally:
        stop_quiet(plan)
