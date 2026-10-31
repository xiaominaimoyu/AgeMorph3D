"""Unified local start/stop/status entry for the AgeMorph3D dev stack.

Dev mode keeps one loopback backend process (``python -B -m agemorph3d`` on
127.0.0.1:8000) and the Vite dev server (127.0.0.1:5173, ``--strictPort``).
Production mode runs the locked ``tsc --noEmit`` and ``vite build``, then serves
``frontend/dist`` from a separate loopback static process on 127.0.0.1:4173.
The API process is unchanged. This tool does not install dependencies,
edit manifests, or grant model/aging readiness. HTTP reachability is reported
separately from the health payload the service itself returns.

Stop signals only processes recorded by this launcher whose pid, creation
token, executable, command line, and owner token still match. Listeners that
fail that check are left untouched.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173
PRODUCTION_FRONTEND_PORT = 4173
OWNER_ENV = "AGEMORPH_LOCAL_RUN_OWNER"
ROLE_ENV = "AGEMORPH_LOCAL_RUN_ROLE"
SCHEMA_VERSION = 1
STATE_ROOTS = ("output", "logs")
# Win32 constants. Checked against subprocess on Windows when those names exist.
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0
FORBIDDEN_STEMS = {
    "apt",
    "apt-get",
    "bash",
    "choco",
    "cmd",
    "npm",
    "npx",
    "pip",
    "pip3",
    "powershell",
    "pwsh",
    "sh",
    "sudo",
    "uv",
    "winget",
}
_MAX_STATE_BYTES = 64 * 1024
_MAX_HTTP_BYTES = 64 * 1024
_MAX_LOG_TAIL = 500


class LocalRunError(Exception):
    """A refused launcher action. Nothing is signaled unless exit handling says so."""

    def __init__(
        self,
        code: str,
        detail: str,
        exit_code: int = 6,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.exit_code = exit_code
        self.extra = dict(extra or {})


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "backend" / ".venv" / "Scripts" / "python.exe"
    return root / "backend" / ".venv" / "bin" / "python"


def default_node() -> str:
    configured = os.environ.get("AGEMORPH_NODE")
    if configured:
        return configured
    if os.name == "nt":
        candidate = Path(r"D:\JAVA run tools\node.exe")
        if candidate.is_file():
            return str(candidate)
    return "node"


def windows_background_settings() -> dict[str, int]:
    """Hidden-window flags for Windows helper processes. No console is created."""
    return {
        "creationflags": CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        "startup_flags": STARTF_USESHOWWINDOW,
        "show_window": SW_HIDE,
    }


def hidden_spawn_kwargs() -> dict[str, object]:
    if os.name == "nt":
        settings = windows_background_settings()
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= int(settings["startup_flags"])
        startup.wShowWindow = int(settings["show_window"])
        creationflags = int(settings["creationflags"])
        for name, expected in (
            ("CREATE_NO_WINDOW", CREATE_NO_WINDOW),
            ("CREATE_NEW_PROCESS_GROUP", CREATE_NEW_PROCESS_GROUP),
            ("STARTF_USESHOWWINDOW", STARTF_USESHOWWINDOW),
            ("SW_HIDE", SW_HIDE),
        ):
            actual = getattr(subprocess, name, expected)
            if actual != expected:
                raise LocalRunError(
                    "WINDOWS_FLAG_MISMATCH",
                    "Windows 隐藏窗口常量与当前 Python 不一致，已拒绝启动。",
                    6,
                )
        return {"startupinfo": startup, "creationflags": creationflags}
    return {"start_new_session": True}


def production_backend_argv(python_executable: Path) -> list[str]:
    return [str(python_executable), "-B", "-m", "agemorph3d"]


def development_frontend_argv(node_executable: str, root: Path) -> list[str]:
    vite = root / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    return [
        node_executable,
        str(vite),
        "--host",
        HOST,
        "--port",
        str(FRONTEND_PORT),
        "--strictPort",
    ]


def production_frontend_argv(node_executable: str, root: Path) -> list[str]:
    """Dev-server command kept under the previous name for existing callers."""
    return development_frontend_argv(node_executable, root)


def frontend_build_commands(node_executable: str, root: Path) -> list[list[str]]:
    """Match ``npm run build`` using the already installed local binaries."""
    frontend = root / "frontend"
    tsc = frontend / "node_modules" / "typescript" / "bin" / "tsc"
    vite = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    return [
        [node_executable, str(tsc), "--noEmit", "--pretty", "false", "-p", "."],
        [node_executable, str(vite), "build"],
    ]


def static_frontend_argv(python_executable: Path, directory: Path, port: int) -> list[str]:
    script = Path(__file__).resolve().with_name("local_static_server.py")
    return [
        str(python_executable),
        "-B",
        str(script),
        "--directory",
        str(directory),
        "--host",
        HOST,
        "--port",
        str(port),
    ]


def base_payload(operation: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "launcher_grants_ready": False,
        "launcher_grants_aging": False,
        "http_reachable_is_model_ready": False,
        "installs_dependencies": False,
        "changes_system_config": False,
    }


def resolve_root(value: Path | None) -> Path:
    root = (project_root() if value is None else value).expanduser()
    try:
        return root.resolve(strict=True)
    except OSError as error:
        raise LocalRunError("ROOT_MISSING", "项目根目录不存在。", 6) from error


def resolve_state_dir(root: Path, requested: Path | None) -> Path:
    """Keep pid files and logs under ignored output/ or logs/ only."""
    if requested is None:
        path = (root / "output" / "local-run").resolve()
    else:
        raw = requested.expanduser()
        path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not path.is_relative_to(root):
        raise LocalRunError("STATE_DIR_OUTSIDE_PROJECT", "状态目录不能超出项目根目录。", 6)
    relative = path.relative_to(root)
    if not relative.parts or relative.parts[0] not in STATE_ROOTS:
        raise LocalRunError(
            "STATE_DIR_NOT_IGNORED",
            "状态和日志只能写在被 Git 忽略的 output/ 或 logs/ 目录中。",
            6,
        )
    return path


def assert_spawn_allowed(argv: Sequence[str]) -> None:
    if not argv or not str(argv[0]).strip():
        raise LocalRunError("EMPTY_COMMAND", "启动命令为空。", 6)
    stem = Path(str(argv[0])).stem.lower()
    if stem in FORBIDDEN_STEMS:
        raise LocalRunError(
            "INSTALL_OR_SHELL_FORBIDDEN",
            "启动器不会安装依赖、打开 shell，或修改系统配置。",
            2,
        )
    if "--research-allow-unresolved" in argv:
        raise LocalRunError(
            "RESEARCH_BYPASS_FORBIDDEN",
            "启动器不能打开研究许可绕过，也不会改写模型清单。",
            6,
        )


def argv_matches(expected: Sequence[str], observed: Sequence[str]) -> bool:
    if len(expected) != len(observed) or not expected:
        return False
    if os.name == "nt":
        if os.path.normcase(str(expected[0])) != os.path.normcase(str(observed[0])):
            return False
        return list(expected[1:]) == list(observed[1:])
    return list(expected) == list(observed)


def normalize_exe(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _state_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


def load_state(state_dir: Path) -> dict:
    path = _state_path(state_dir)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "services": {}}
    try:
        if path.stat().st_size > _MAX_STATE_BYTES:
            raise LocalRunError("STATE_CORRUPT", "状态文件超过读取上限，未停止任何进程。", 4)
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LocalRunError("STATE_CORRUPT", "状态文件无法读取，未停止任何进程。", 4) from error
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != SCHEMA_VERSION
        or not isinstance(data.get("services"), dict)
    ):
        raise LocalRunError("STATE_CORRUPT", "状态文件格式无效，未停止任何进程。", 4)
    return data


def save_state(state_dir: Path, data: Mapping[str, object]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _state_path(state_dir)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(payload)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


@contextlib.contextmanager
def state_lock(state_dir: Path) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    handle = (state_dir / "state.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise LocalRunError(
                    "LOCK_HELD", "另一个启动器命令正在占用本地状态锁。", 3
                ) from error
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise LocalRunError(
                    "LOCK_HELD", "另一个启动器命令正在占用本地状态锁。", 3
                ) from error
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            with contextlib.suppress(OSError):
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def parse_environment_block(block: bytes, *, encoding: str) -> dict[str, str]:
    text = block.decode(encoding, errors="surrogateescape")
    found: dict[str, str] = {}
    for part in text.split("\0"):
        if not part:
            break
        key, separator, value = part.partition("=")
        if separator and key:
            found[key] = value
    return found


def _linux_stat(pid: int) -> tuple[str, int, str] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        end = raw.rfind(")")
        fields = raw[end + 2 :].split()
        return fields[0], int(fields[1]), fields[19]
    except (OSError, IndexError, ValueError):
        return None


def _observe_linux(pid: int) -> dict[str, object] | None:
    stat = _linux_stat(pid)
    if stat is None:
        return None
    state, ppid, creation = stat
    proc = Path(f"/proc/{pid}")
    try:
        parts = (proc / "cmdline").read_bytes().split(b"\0")
        if parts and parts[-1] == b"":
            parts = parts[:-1]
        argv = [part.decode("utf-8", errors="surrogateescape") for part in parts]
        executable = os.readlink(proc / "exe")
        environment = parse_environment_block((proc / "environ").read_bytes(), encoding="utf-8")
    except OSError:
        return None
    return {
        "pid": pid,
        "state": state,
        "ppid": ppid,
        "creation": creation,
        "executable": executable,
        "argv": argv,
        "owner_token": environment.get(OWNER_ENV),
        "role": environment.get(ROLE_ENV),
    }


def _creation_linux(pid: int) -> str | None:
    stat = _linux_stat(pid)
    if stat is None or stat[0] == "Z":
        return None
    return stat[2]


def _process_table_linux() -> dict[int, dict[str, object]]:
    table: dict[int, dict[str, object]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        stat = _linux_stat(int(entry.name))
        if stat is None:
            continue
        state, ppid, creation = stat
        table[int(entry.name)] = {"ppid": ppid, "creation": creation, "state": state}
    return table


def _windows_creation_and_exe(pid: int) -> tuple[str, str] | None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    access = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
    handle = kernel.OpenProcess(access, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        unused = wintypes.FILETIME()
        kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel.GetProcessTimes.restype = wintypes.BOOL
        if not kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(unused),
            ctypes.byref(unused),
            ctypes.byref(unused),
        ):
            return None
        creation = str((int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime))
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return creation, buffer.value
    finally:
        kernel.CloseHandle(handle)


_MEMORY_PAGE = 4096
_MAX_ENV_BYTES = 128 * 1024


def read_available_memory(
    reader, address: int, size: int, *, page_size: int = _MEMORY_PAGE
) -> bytes:
    """Copy up to ``size`` bytes, never asking for more than the rest of one page.

    One ``ReadProcessMemory`` of a whole environment block returns
    ``ERROR_PARTIAL_COPY`` (299) when the request continues past the committed
    pages. A short or empty chunk ends the copy; bytes already copied stay.
    """
    if size <= 0 or address <= 0 or page_size <= 0:
        return b""
    copied = bytearray()
    cursor = address
    remaining = size
    while remaining:
        step = min(remaining, page_size - (cursor % page_size))
        chunk = reader(cursor, step)
        if not chunk:
            break
        copied.extend(chunk)
        cursor += len(chunk)
        remaining -= len(chunk)
        if len(chunk) < step:
            break
    return bytes(copied)


def read_exact_memory(
    reader, address: int, size: int, *, page_size: int = _MEMORY_PAGE
) -> bytes | None:
    """Return exactly ``size`` bytes, or None when any page is missing."""
    data = read_available_memory(reader, address, size, page_size=page_size)
    if len(data) != size:
        return None
    return data


def terminated_utf16_environment(data: bytes) -> dict[str, str] | None:
    """Parse a UTF-16 environment only when its terminating double-NUL is present."""
    if len(data) < 4:
        return None
    end = None
    for index in range(0, len(data) - 3, 2):
        if data[index : index + 4] == b"\x00\x00\x00\x00":
            end = index
            break
    if end is None:
        return None
    return parse_environment_block(data[: end + 4], encoding="utf-16-le")


def resolve_manifest_argument(root: Path, value: Path) -> str:
    """Documented diagnose paths are relative to the project root, not ``backend/``."""
    candidate = value if value.is_absolute() else root / value
    return str(candidate.resolve())


def _windows_peb_text(pid: int) -> tuple[list[str] | None, dict[str, str] | None]:
    """Read command line and environment. Any uncertainty returns None, None."""
    if ctypes_pointer_bits() != 64:
        return None, None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

    class PROCESS_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Reserved1", ctypes.c_void_p),
            ("PebBaseAddress", ctypes.c_void_p),
            ("Reserved2", ctypes.c_void_p * 2),
            ("UniqueProcessId", ctypes.c_void_p),
            ("Reserved3", ctypes.c_void_p),
        ]

    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        return None, None

    def read_some(address: int, size: int) -> bytes:
        """Return only the bytes copied. A short copy does not count as a full read."""
        if size <= 0 or address <= 0:
            return b""
        buffer = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        kernel.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(got))
        copied = int(got.value)
        if copied <= 0 or copied > size:
            return b""
        return buffer.raw[:copied]

    def read_full(address: int, size: int) -> bytes | None:
        data = read_some(address, size)
        if len(data) != size:
            return None
        return data

    try:
        kernel.ReadProcessMemory.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel.ReadProcessMemory.restype = wintypes.BOOL
        info = PROCESS_BASIC_INFORMATION()
        status = ntdll.NtQueryInformationProcess(
            handle, 0, ctypes.byref(info), ctypes.sizeof(info), None
        )
        if status != 0 or not info.PebBaseAddress:
            return None, None
        parameters = read_full(int(info.PebBaseAddress) + 0x20, 8)
        if parameters is None:
            return None, None
        params = int.from_bytes(parameters, "little")
        command = read_full(params + 0x70, 16)
        environment_ptr = read_full(params + 0x80, 8)
        if command is None or environment_ptr is None:
            return None, None
        length = int.from_bytes(command[0:2], "little")
        command_address = int.from_bytes(command[8:16], "little")
        if not 0 < length <= 32768 or length % 2:
            return None, None
        env_address = int.from_bytes(environment_ptr, "little")
        if not env_address:
            return None, None
        command_bytes = read_exact_memory(read_some, command_address, length)
        env_bytes = read_available_memory(read_some, env_address, _MAX_ENV_BYTES)
        environment = terminated_utf16_environment(env_bytes)
        if command_bytes is None or environment is None:
            return None, None
        command_line = command_bytes.decode("utf-16-le", errors="strict")
        argc = ctypes.c_int()
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.CommandLineToArgvW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_int),
        ]
        shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
        shell32.LocalFree.argtypes = [ctypes.c_void_p]
        parsed = shell32.CommandLineToArgvW(command_line, ctypes.byref(argc))
        if not parsed or argc.value <= 0:
            return None, None
        try:
            argv = [parsed[index] for index in range(argc.value)]
        finally:
            shell32.LocalFree(parsed)
        return argv, environment
    except (OSError, UnicodeError, ValueError):
        return None, None
    finally:
        kernel.CloseHandle(handle)


def ctypes_pointer_bits() -> int:
    import ctypes

    return ctypes.sizeof(ctypes.c_void_p) * 8


def _observe_windows(pid: int) -> dict[str, object] | None:
    basics = _windows_creation_and_exe(pid)
    if basics is None:
        return None
    creation, executable = basics
    argv, environment = _windows_peb_text(pid)
    if argv is None or environment is None:
        return None
    return {
        "pid": pid,
        "state": "R",
        "ppid": None,
        "creation": creation,
        "executable": executable,
        "argv": argv,
        "owner_token": environment.get(OWNER_ENV),
        "role": environment.get(ROLE_ENV),
    }


def _process_table_windows() -> dict[int, dict[str, object]] | None:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("_pad0", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_ulonglong),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return None
    table: dict[int, dict[str, object]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        kernel.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        kernel.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        kernel.Process32FirstW.restype = wintypes.BOOL
        kernel.Process32NextW.restype = wintypes.BOOL
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            return None
        while True:
            basics = _windows_creation_and_exe(int(entry.th32ProcessID))
            if basics is not None:
                table[int(entry.th32ProcessID)] = {
                    "ppid": int(entry.th32ParentProcessID),
                    "creation": basics[0],
                    "state": "R",
                }
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel.CloseHandle(snapshot)
    return table


def observe(pid: int) -> dict[str, object] | None:
    if pid <= 0:
        return None
    if os.name == "nt":
        return _observe_windows(pid)
    return _observe_linux(pid)


def process_table() -> dict[int, dict[str, object]] | None:
    if os.name == "nt":
        return _process_table_windows()
    return _process_table_linux()


def identity_matches(stored: Mapping[str, object], observed: Mapping[str, object] | None) -> bool:
    if not observed or observed.get("state") == "Z":
        return False
    try:
        same_pid = int(stored["pid"]) == int(observed["pid"])
    except (TypeError, ValueError):
        return False
    token = stored.get("owner_token")
    argv = stored.get("argv")
    observed_argv = observed.get("argv")
    return bool(
        same_pid
        and token
        and observed.get("owner_token") == token
        and stored.get("role") == observed.get("role")
        and str(stored.get("creation_token")) == str(observed.get("creation"))
        and normalize_exe(str(stored.get("executable", "")))
        == normalize_exe(str(observed.get("executable", "")))
        and isinstance(argv, list)
        and isinstance(observed_argv, list)
        and argv_matches(argv, observed_argv)
    )


def creation_still(pid: int, creation: str) -> bool:
    if os.name == "nt":
        basics = _windows_creation_and_exe(pid)
        return basics is not None and basics[0] == creation
    current = _creation_linux(pid)
    return current is not None and current == creation


def descendant_snapshots(root_pid: int, root_creation: str) -> list[dict[str, str]] | None:
    """Owned descendants only. None means the tree could not be enumerated safely."""
    table = process_table()
    if table is None:
        return None
    if root_pid not in table:
        return []
    if str(table[root_pid]["creation"]) != root_creation or table[root_pid]["state"] == "Z":
        return None
    children: dict[int, list[int]] = {}
    for pid, info in table.items():
        children.setdefault(int(info["ppid"]), []).append(pid)
    owned = [root_pid]
    cursor = 0
    while cursor < len(owned):
        parent = owned[cursor]
        cursor += 1
        parent_creation = int(table[parent]["creation"])
        for child in children.get(parent, []):
            if child in owned or table[child]["state"] == "Z":
                continue
            try:
                child_creation = int(table[child]["creation"])
            except (TypeError, ValueError):
                continue
            if child_creation >= parent_creation:
                owned.append(child)
    owned.reverse()
    return [
        {"pid": str(pid), "creation": str(table[pid]["creation"])}
        for pid in owned
        if table[pid]["state"] != "Z"
    ]


def _signal_creation(pid: int, creation: str, sig: int) -> bool:
    if not creation_still(pid, creation):
        return False
    try:
        os.kill(pid, sig)
    except OSError:
        return False
    return True


def _terminate_windows(pid: int, creation: str) -> bool:
    if not creation_still(pid, creation):
        return False
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel.OpenProcess(0x0001, False, pid)
    if not handle:
        return False
    try:
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        return bool(kernel.TerminateProcess(handle, 1))
    finally:
        kernel.CloseHandle(handle)


def reap(pid: int) -> None:
    if os.name == "nt":
        return
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)


def _graceful(pid: int, creation: str) -> str:
    if os.name == "nt":
        if _signal_creation(pid, creation, signal.CTRL_BREAK_EVENT):
            return "ctrl_break"
        return "not_signaled"
    if _signal_creation(pid, creation, signal.SIGTERM):
        return "sigterm"
    return "not_signaled"


def _force(pid: int, creation: str) -> bool:
    if os.name == "nt":
        return _terminate_windows(pid, creation)
    return _signal_creation(pid, creation, signal.SIGKILL)


def _alive(pid: int, creation: str) -> bool:
    return creation_still(pid, creation)


def _wait_until_dead(members: Sequence[Mapping[str, str]], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_alive(int(item["pid"]), item["creation"]) for item in members):
            return
        time.sleep(0.05)


def stop_record(record: Mapping[str, object], grace: float) -> dict[str, object]:
    """Signal one verified service tree. Mismatched records are not signaled."""
    pid = int(record["pid"])
    observed = observe(pid)
    same_zombie = observed is not None and observed.get("state") == "Z"
    same_creation = (
        str(observed.get("creation")) == str(record["creation_token"]) if observed else False
    )
    if observed is None or (same_zombie and same_creation):
        reap(pid)
        return {"result": "already_exited", "forced": False, "signaled": False}
    if not identity_matches(record, observed):
        return {"result": "identity_mismatch", "forced": False, "signaled": False}
    root_creation = str(record["creation_token"])
    tree = descendant_snapshots(pid, root_creation)
    if tree is None or (not tree and _alive(pid, root_creation)):
        return {"result": "tree_unverified", "forced": False, "signaled": False}
    if not tree:
        reap(pid)
        return {"result": "already_exited", "forced": False, "signaled": False}
    method = _graceful(pid, root_creation)
    _wait_until_dead([{"pid": str(pid), "creation": root_creation}], grace)
    members = list(tree)
    if _alive(pid, root_creation):
        refreshed = descendant_snapshots(pid, root_creation)
        if refreshed:
            members = refreshed

    def pending(items: Sequence[Mapping[str, str]]) -> list[Mapping[str, str]]:
        return [item for item in items if _alive(int(item["pid"]), item["creation"])]

    for item in pending(members):
        if int(item["pid"]) != pid:
            _graceful(int(item["pid"]), item["creation"])
    _wait_until_dead(pending(members), min(grace, 1))
    forced = bool(pending(members))
    for item in pending(members):
        _force(int(item["pid"]), item["creation"])
    _wait_until_dead(members, 1)
    reap(pid)
    if pending(members):
        return {
            "result": "still_running",
            "forced": forced,
            "signaled": True,
            "stop_method": method,
        }
    return {
        "result": "stopped",
        "forced": forced,
        "signaled": True,
        "stop_method": method,
    }


def child_env(
    owner_token: str, role: str, manifests: Mapping[str, str] | None = None
) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if "\0" not in key and "\0" not in value}
    env[OWNER_ENV] = owner_token
    env[ROLE_ENV] = role
    env["PYTHONUNBUFFERED"] = "1"
    if role == "backend" and manifests:
        if manifests.get("detector"):
            env["AGEMORPH_DETECTOR_MANIFEST"] = manifests["detector"]
        if manifests.get("reconstructor"):
            env["AGEMORPH_RECONSTRUCTOR_MANIFEST"] = manifests["reconstructor"]
    return env


def _kill_popen(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=1)
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def _redact(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "[redacted]")
    return text[-_MAX_LOG_TAIL:]


def _log_tail(path: Path, token: str) -> str:
    try:
        data = path.read_bytes()[-4096:]
    except OSError:
        return ""
    return _redact(data.decode("utf-8", errors="replace"), token)


def http_probe(host: str, port: int, path: str, timeout: float = 0.4) -> tuple[int | None, bytes]:
    if host != HOST or not path.startswith("/"):
        raise LocalRunError("HOST_NOT_LOOPBACK", "只探测 127.0.0.1 上的固定本机入口。", 6)
    url = f"http://{HOST}:{port}{path}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(_MAX_HTTP_BYTES)
    except urllib.error.HTTPError as error:
        with contextlib.suppress(OSError):
            return error.code, error.read(_MAX_HTTP_BYTES)
        return error.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, b""


def port_accepting(host: str, port: int) -> bool:
    status, _ = http_probe(host, port, "/", timeout=0.2)
    if status is not None:
        return True
    if host != HOST:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        try:
            sock.connect((host, port))
        except OSError:
            return False
    return True


def _run_text(argv: Sequence[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    assert_spawn_allowed(argv)
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def executable_exists(path: str) -> bool:
    candidate = Path(path)
    if candidate.is_file():
        return True
    return "/" not in path and "\\" not in path and os.name != "nt" and _which(path) is not None


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def probe_version(executable: str, root: Path) -> dict[str, object]:
    resolved = executable
    if not Path(executable).is_file():
        found = _which(executable) if "/" not in executable and "\\" not in executable else None
        if found is None:
            return {"path": executable, "exists": False, "version": None}
        resolved = found
    try:
        if Path(resolved).stem.lower().startswith("python"):
            completed = _run_text(
                [resolved, "-B", "-c", "import sys; print(sys.version.split()[0])"],
                root,
                20,
            )
        else:
            completed = _run_text([resolved, "--version"], root, 20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "path": resolved,
            "exists": True,
            "version": None,
            "error": type(error).__name__,
        }
    version = completed.stdout.strip().splitlines()[0] if completed.returncode == 0 else None
    return {
        "path": resolved,
        "exists": True,
        "version": version,
        "returncode": completed.returncode,
    }


def probe_backend_imports(python_executable: Path, root: Path) -> dict[str, object]:
    if not python_executable.is_file():
        return {
            "ok": False,
            "missing": ["interpreter"],
            "detail": "项目虚拟环境解释器不存在。",
        }
    code = "import fastapi, uvicorn, agemorph3d.__main__"
    try:
        completed = _run_text([str(python_executable), "-B", "-c", code], root / "backend", 60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "ok": False,
            "missing": ["probe_failed"],
            "detail": type(error).__name__,
        }
    if completed.returncode == 0:
        return {"ok": True, "missing": [], "detail": "导入检查通过，不代表模型已就绪。"}
    missing = []
    for line in completed.stderr.splitlines():
        if "No module named" in line:
            missing.append(line.strip())
    return {
        "ok": False,
        "missing": missing or ["import_failed"],
        "detail": "项目环境缺少运行依赖。启动器不会执行安装。",
    }


def probe_frontend_files(root: Path, node_executable: str) -> dict[str, object]:
    vite = root / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    node_ok = executable_exists(node_executable)
    return {
        "node_exists": node_ok,
        "vite_entry": str(vite),
        "vite_entry_exists": vite.is_file(),
        "ok": node_ok and vite.is_file(),
        "detail": "前端入口文件已找到。"
        if node_ok and vite.is_file()
        else "未找到 Node 或 Vite 入口。启动器不会执行 npm install。",
    }


def _public_process(record: Mapping[str, object] | None, kind: str) -> dict[str, object]:
    if record is None:
        return {"owned": False, "identity": "absent", "pid": None}
    return {
        "owned": kind == "verified",
        "identity": kind,
        "pid": record.get("pid") if kind != "absent" else None,
        "port": record.get("port"),
        "log_path": record.get("log_path"),
    }


def _health_view(status: int | None, body: bytes) -> dict[str, object]:
    reported = None
    parse = "not_json"
    if body:
        try:
            loaded = json.loads(body.decode("utf-8"))
            if isinstance(loaded, dict):
                reported = loaded
                parse = "object"
            else:
                parse = "not_object"
        except (UnicodeError, json.JSONDecodeError):
            parse = "invalid"
    capabilities = None
    if isinstance(reported, dict) and isinstance(reported.get("capabilities"), dict):
        capabilities = reported["capabilities"]
    return {
        "http_status": status,
        "http_reachable": status is not None,
        "service_health": reported,
        "service_health_parse": parse,
        "service_reported_capabilities": capabilities,
        "launcher_grants_ready": False,
        "launcher_grants_aging": False,
    }


def model_path_report(plan: Plan) -> dict[str, object]:
    """Show configured manifest paths without reading them or granting readiness."""

    def one(path: str | None) -> dict[str, object]:
        if not path:
            return {
                "configured": False,
                "path": None,
                "exists": False,
                "launcher_grants_ready": False,
            }
        return {
            "configured": True,
            "path": path,
            "exists": Path(path).is_file(),
            "launcher_grants_ready": False,
        }

    return {
        "detector": one(plan.detector_manifest),
        "reconstructor": one(plan.reconstructor_manifest),
        "launcher_grants_ready": False,
        "launcher_grants_aging": False,
    }


def build_frontend(plan: Plan) -> dict[str, object]:
    """Run the locked typecheck and vite build. Never installs packages."""
    frontend = plan.root / "frontend"
    tsc = frontend / "node_modules" / "typescript" / "bin" / "tsc"
    vite = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    if not executable_exists(plan.node_executable) or not tsc.is_file() or not vite.is_file():
        raise LocalRunError(
            "MISSING_FRONTEND_RUNTIME",
            "未找到 Node、TypeScript 或 Vite。启动器不会执行 npm install。",
            2,
        )
    commands = frontend_build_commands(plan.node_executable, plan.root)
    for command in commands:
        assert_spawn_allowed(command)
    log_path = plan.state_dir / "frontend-build.log"
    _append_log(log_path, "frontend-build")
    returncodes = []
    with log_path.open("ab") as stream:
        for command in commands:
            stream.write((" ".join(command) + "\n").encode())
            stream.flush()
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(frontend),
                    shell=False,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=180,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise LocalRunError(
                    "BUILD_FAILED",
                    f"前端生产构建没有完成：{type(error).__name__}。没有安装依赖，也没有启动服务。",
                    5,
                    {"log_tail": _log_tail(log_path, "")},
                ) from error
            returncodes.append(completed.returncode)
            if completed.returncode != 0:
                break
    index = frontend / "dist" / "index.html"
    if any(code != 0 for code in returncodes) or not index.is_file():
        raise LocalRunError(
            "BUILD_FAILED",
            "前端生产构建未生成 dist/index.html。启动器没有安装依赖，也没有启动服务。",
            5,
            {"returncodes": returncodes, "log_tail": _log_tail(log_path, "")},
        )
    return {
        "ran": True,
        "returncodes": returncodes,
        "index": str(index),
        "installs_dependencies": False,
    }


def status_report(plan: Plan) -> dict[str, object]:
    payload = base_payload("status")
    state = load_state(plan.state_dir)
    services: dict[str, object] = {}
    for role, port, path in (
        ("backend", plan.backend_port, "/api/health"),
        ("frontend", plan.frontend_port, "/"),
    ):
        record = state["services"].get(role)
        if not isinstance(record, dict):
            record = None
            kind = "absent"
        else:
            observed = observe(int(record["pid"])) if str(record.get("pid", "")).isdigit() else None
            if observed is None or observed.get("state") == "Z":
                kind = "exited"
            elif identity_matches(record, observed):
                kind = "verified"
            else:
                kind = "identity_mismatch"
            recorded_port = record.get("port")
            recorded_path = record.get("http_path")
            if type(recorded_port) is int and 1 <= recorded_port <= 65535:
                port = recorded_port
            if (
                isinstance(recorded_path, str)
                and recorded_path.startswith("/")
                and ".." not in recorded_path
            ):
                path = recorded_path
        status, body = http_probe(plan.host, port, path)
        view = _health_view(status, body if role == "backend" else b"")
        if role != "backend":
            view["service_health"] = None
            view["service_reported_capabilities"] = None
            view["service_health_parse"] = "not_applicable"
        services[role] = {
            "process": _public_process(record if isinstance(record, dict) else None, kind),
            "http": view,
            "listener_without_ownership": bool(view["http_reachable"] and kind != "verified"),
        }
    payload["services"] = services
    payload["mode"] = plan.mode
    payload["model_paths"] = model_path_report(plan)
    payload["aging_policy"] = (
        "launcher_does_not_call_/api/aging_and_does_not_change_MODEL_NOT_READY"
    )
    return payload


def check_report(plan: Plan) -> tuple[dict[str, object], int]:
    payload = base_payload("check")
    payload["python"] = probe_version(str(plan.python_executable), plan.root)
    payload["node"] = probe_version(plan.node_executable, plan.root)
    backend = probe_backend_imports(plan.python_executable, plan.root)
    frontend = probe_frontend_files(plan.root, plan.node_executable)
    payload["backend_imports"] = backend
    payload["frontend_files"] = frontend
    payload["mode"] = plan.mode
    payload["model_paths"] = model_path_report(plan)
    payload["frontend_dist_exists"] = (plan.root / "frontend" / "dist" / "index.html").is_file()
    tsc = plan.root / "frontend" / "node_modules" / "typescript" / "bin" / "tsc"
    payload["typescript_entry_exists"] = tsc.is_file()
    payload["status"] = status_report(plan)
    code = 0
    problems = []
    if "backend" in plan.roles and (not plan.python_executable.is_file() or not backend["ok"]):
        code = 2
        problems.append("MISSING_BACKEND_RUNTIME")
    if "frontend" in plan.roles and not frontend["ok"]:
        code = 2
        problems.append("MISSING_FRONTEND_RUNTIME")
    if plan.mode == "production" and "frontend" in plan.roles and not tsc.is_file():
        code = 2
        problems.append("MISSING_FRONTEND_RUNTIME")
    status = payload["status"]
    assert isinstance(status, dict)
    services = status["services"]
    assert isinstance(services, dict)
    for role, port in (
        ("backend", plan.backend_port),
        ("frontend", plan.frontend_port),
    ):
        if role not in plan.roles:
            continue
        info = services[role]
        assert isinstance(info, dict)
        process = info["process"]
        assert isinstance(process, dict)
        if process["identity"] == "identity_mismatch":
            code = 4
            problems.append(f"{role.upper()}_IDENTITY_MISMATCH")
        elif process["identity"] == "verified":
            problems.append(f"{role.upper()}_ALREADY_RUNNING")
            if code == 0:
                code = 3
        elif port_accepting(plan.host, port):
            code = 3
            problems.append(f"{role.upper()}_PORT_IN_USE")
    payload["problems"] = problems
    payload["detail"] = (
        "检查完成。进程可达和模型就绪是两项不同结果；启动器不授予 ready 或年龄能力。"
    )
    return payload, code


def _append_log(path: Path, role: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        stream.write(f"\n--- start {role} {stamp} ---\n".encode())


def _wait_http(
    proc: subprocess.Popen[bytes], host: str, port: int, path: str, timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        status, _ = http_probe(host, port, path, timeout=0.3)
        if status == 200:
            return True
        time.sleep(0.05)
    return False


def spawn_service(plan: Plan, role: str) -> None:
    manifests = {
        key: value
        for key, value in (
            ("detector", plan.detector_manifest),
            ("reconstructor", plan.reconstructor_manifest),
        )
        if value
    }
    if role == "backend":
        argv = list(plan.backend_argv or production_backend_argv(plan.python_executable))
        cwd = plan.root / "backend"
        port = plan.backend_port
        http_path = "/api/health"
    elif role == "frontend":
        if plan.frontend_argv is not None:
            argv = list(plan.frontend_argv)
        elif plan.mode == "production":
            argv = static_frontend_argv(
                plan.python_executable,
                plan.root / "frontend" / "dist",
                plan.frontend_port,
            )
        else:
            argv = development_frontend_argv(plan.node_executable, plan.root)
        cwd = (
            plan.root
            if plan.mode == "production" and plan.frontend_argv is None
            else plan.root / "frontend"
        )
        port = plan.frontend_port
        http_path = "/"
    else:
        raise LocalRunError("UNKNOWN_ROLE", "只支持 backend 与 frontend。", 6)
    assert_spawn_allowed(argv)
    token = secrets.token_hex(16)
    log_path = plan.state_dir / f"{role}.log"
    _append_log(log_path, role)
    with log_path.open("ab") as stream:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=child_env(token, role, manifests if role == "backend" else None),
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            shell=False,
            **hidden_spawn_kwargs(),
        )
    observed = None
    for _ in range(50):
        if proc.poll() is not None:
            break
        observed = observe(proc.pid)
        if (
            observed
            and observed.get("owner_token") == token
            and observed.get("state") != "Z"
            and argv_matches(argv, list(observed["argv"]))
        ):
            break
        time.sleep(0.02)
    if proc.poll() is not None or not observed or observed.get("owner_token") != token:
        _kill_popen(proc)
        raise LocalRunError(
            "START_FAILED",
            f"{role} 进程未能保持可核对身份。已结束本次创建的进程，没有改动其他监听者。",
            5,
            {"log_tail": _log_tail(log_path, token), "role": role},
        )
    if not argv_matches(argv, list(observed["argv"])):
        _kill_popen(proc)
        raise LocalRunError(
            "IDENTITY_MISMATCH",
            f"{role} 的实际命令行与请求不一致，已结束本次创建的进程。",
            5,
            {"role": role},
        )
    record = {
        "pid": observed["pid"],
        "creation_token": observed["creation"],
        "executable": observed["executable"],
        "argv": argv,
        "owner_token": token,
        "role": role,
        "cwd": str(cwd),
        "log_path": str(log_path),
        "host": plan.host,
        "port": port,
        "http_path": http_path,
    }
    state = load_state(plan.state_dir)
    state["services"][role] = record
    save_state(plan.state_dir, state)
    if not _wait_http(proc, plan.host, port, http_path, plan.startup_timeout):
        outcome = stop_record(record, plan.stop_grace_seconds)
        if outcome["result"] in {"stopped", "already_exited"}:
            state = load_state(plan.state_dir)
            state["services"].pop(role, None)
            save_state(plan.state_dir, state)
        raise LocalRunError(
            "START_FAILED",
            f"{role} 未在限定时间内返回 HTTP 200，已回滚本次拥有的进程。",
            5,
            {"role": role, "rollback": outcome, "log_tail": _log_tail(log_path, token)},
        )


def _preflight_ports(plan: Plan) -> None:
    state = load_state(plan.state_dir)
    for role, port in (
        ("backend", plan.backend_port),
        ("frontend", plan.frontend_port),
    ):
        if role not in plan.roles:
            continue
        record = state["services"].get(role)
        if isinstance(record, dict):
            observed = observe(int(record["pid"]))
            if (
                observed is not None
                and observed.get("state") != "Z"
                and identity_matches(record, observed)
            ):
                raise LocalRunError(
                    "ALREADY_RUNNING",
                    f"{role} 已由本启动器启动且身份核对通过，拒绝重复启动。",
                    3,
                    {"role": role, "pid": record.get("pid")},
                )
            if observed is not None and observed.get("state") != "Z":
                raise LocalRunError(
                    "IDENTITY_MISMATCH",
                    f"{role} 的状态记录与现存进程不一致，拒绝启动，也没有结束该进程。",
                    4,
                    {"role": role},
                )
            state["services"].pop(role, None)
            save_state(plan.state_dir, state)
        if port_accepting(plan.host, port):
            raise LocalRunError(
                "PORT_IN_USE",
                f"{HOST}:{port} 已有监听者。启动器不会结束未知进程。",
                3,
                {"role": role, "port": port},
            )


def start_services(plan: Plan) -> dict[str, object]:
    build_info: dict[str, object] = {"ran": False}
    if plan.dependency_probe:
        report, code = check_report(plan)
        if code == 2:
            raise LocalRunError(
                "MISSING_RUNTIME",
                "解释器或依赖缺失。启动器不会安装依赖，也没有启动进程。",
                2,
                {"check": report},
            )
        if code in {3, 4}:
            problems = report["problems"]
            assert isinstance(problems, list)
            if any(
                item.endswith("_PORT_IN_USE") or item.endswith("_ALREADY_RUNNING")
                for item in problems
            ):
                raise LocalRunError(
                    "START_BLOCKED",
                    "端口被占用或本启动器的进程已在运行，没有启动新进程。",
                    3,
                    {"check": report},
                )
            raise LocalRunError(
                "IDENTITY_MISMATCH",
                "现有状态与进程身份不一致，没有启动或结束进程。",
                4,
                {"check": report},
            )
    else:
        _preflight_ports(plan)
    if plan.mode == "production" and plan.run_build and "frontend" in plan.roles:
        build_info = build_frontend(plan)
    started: list[str] = []
    try:
        for role in plan.roles:
            spawn_service(plan, role)
            started.append(role)
    except LocalRunError as error:
        if started:
            error.extra["previous_rollback"] = stop_services(plan, tuple(started))
        raise
    payload = base_payload("start")
    payload["mode"] = plan.mode
    payload["build"] = build_info
    payload["model_paths"] = model_path_report(plan)
    payload["started"] = started
    payload["status"] = status_report(plan)
    payload["detail"] = "进程已启动并可访问 HTTP。这不是模型 ready，也不授予年龄能力。"
    return payload


def stop_services(plan: Plan, roles: Sequence[str] | None = None) -> dict[str, object]:
    selected = tuple(roles or plan.roles)
    state = load_state(plan.state_dir)
    defaults = {"backend": plan.backend_port, "frontend": plan.frontend_port}
    owned_ports = {}
    for role, default in defaults.items():
        record = state["services"].get(role)
        port = default
        if isinstance(record, dict) and type(record.get("port")) is int:
            port = record["port"]
        owned_ports[role] = port
    results = {}
    exit_code = 0
    for role in selected:
        record = state["services"].get(role)
        if not isinstance(record, dict):
            results[role] = {
                "result": "not_recorded",
                "forced": False,
                "signaled": False,
            }
            continue
        outcome = stop_record(record, plan.stop_grace_seconds)
        results[role] = outcome
        if outcome["result"] in {"stopped", "already_exited"}:
            state["services"].pop(role, None)
        elif outcome["result"] == "identity_mismatch":
            exit_code = 4
        else:
            exit_code = 5
    save_state(plan.state_dir, state)
    payload = base_payload("stop")
    payload["results"] = results
    payload["killed_unknown_listeners"] = False
    payload["ports"] = {
        role: {"port": port, "accepting": port_accepting(plan.host, port)}
        for role, port in owned_ports.items()
    }
    payload["detail"] = "只处理身份核对通过的本启动器进程；未知端口监听者保持不动。"
    if exit_code:
        raise LocalRunError("STOP_INCOMPLETE", str(payload["detail"]), exit_code, payload)
    return payload


def diagnose_report(
    plan: Plan,
    detector_manifest: Path | None,
    reconstructor_manifest: Path | None,
) -> tuple[dict[str, object], int]:
    payload = base_payload("diagnose")
    if not plan.python_executable.is_file():
        raise LocalRunError(
            "MISSING_INTERPRETER",
            "未找到项目虚拟环境解释器。不会改用系统 Python，也不会安装依赖。",
            2,
        )
    argv = [str(plan.python_executable), "-B", "-m", "agemorph3d.model_diagnostics"]
    if detector_manifest is not None:
        argv.extend(
            [
                "--detector-manifest",
                resolve_manifest_argument(plan.root, detector_manifest),
            ]
        )
    if reconstructor_manifest is not None:
        argv.extend(
            [
                "--reconstructor-manifest",
                resolve_manifest_argument(plan.root, reconstructor_manifest),
            ]
        )
    assert_spawn_allowed(argv)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(plan.root / "backend"),
            shell=False,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LocalRunError(
            "DIAGNOSE_FAILED", f"模型诊断没有完成：{type(error).__name__}。", 2
        ) from error
    parsed = None
    try:
        loaded = json.loads(completed.stdout.decode("utf-8"))
        if isinstance(loaded, dict):
            parsed = loaded
    except (UnicodeError, json.JSONDecodeError):
        parsed = None
    payload["diagnostics_exit_code"] = completed.returncode
    payload["diagnostics"] = parsed
    payload["diagnostics_stderr_tail"] = completed.stderr.decode("utf-8", errors="replace")[
        -_MAX_LOG_TAIL:
    ]
    payload["reported_grant_is_not_launcher_authorization"] = True
    payload["manifests_modified_by_launcher"] = False
    payload["status"] = status_report(plan)
    payload["detail"] = (
        "诊断沿用只读模型清单检查。退出码 1 表示登记/完整性仍阻塞；"
        "启动器不把该结果改成 ready，也不调用 /api/aging。"
    )
    if parsed is None:
        return payload, 2
    if completed.returncode == 0 and parsed.get("status") == "preconditions_met":
        return payload, 0
    if completed.returncode == 1:
        return payload, 1
    return payload, 2


class Plan:
    def __init__(
        self,
        *,
        root: Path,
        state_dir: Path,
        python_executable: Path,
        node_executable: str,
        roles: tuple[str, ...],
        backend_port: int = BACKEND_PORT,
        frontend_port: int = FRONTEND_PORT,
        host: str = HOST,
        startup_timeout: float = 30.0,
        stop_grace_seconds: float = 5.0,
        allow_ephemeral_ports: bool = False,
        dependency_probe: bool = True,
        backend_argv: Sequence[str] | None = None,
        frontend_argv: Sequence[str] | None = None,
        mode: str = "dev",
        run_build: bool = True,
        detector_manifest: str | None = None,
        reconstructor_manifest: str | None = None,
    ) -> None:
        if host != HOST:
            raise LocalRunError(
                "HOST_NOT_LOOPBACK", "只允许绑定 127.0.0.1，以保持现有 Host 限制。", 6
            )
        if mode not in {"dev", "production"}:
            raise LocalRunError("UNKNOWN_MODE", "运行方式只支持 dev 或 production。", 6)
        expected_frontend = PRODUCTION_FRONTEND_PORT if mode == "production" else FRONTEND_PORT
        if not allow_ephemeral_ports and (
            backend_port != BACKEND_PORT or frontend_port != expected_frontend
        ):
            raise LocalRunError(
                "PORT_FIXED",
                "开发入口固定为 127.0.0.1:8000 与 127.0.0.1:5173；生产前端固定为 127.0.0.1:4173。",
                6,
            )
        for port in (backend_port, frontend_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise LocalRunError("PORT_INVALID", "端口必须是 1—65535 的整数。", 6)
        if not math_finite_positive(startup_timeout) or not math_finite_positive(
            stop_grace_seconds
        ):
            raise LocalRunError("TIMEOUT_INVALID", "超时必须是有限正数。", 6)
        if not roles or any(role not in {"backend", "frontend"} for role in roles):
            raise LocalRunError("UNKNOWN_ROLE", "只支持 backend 与 frontend。", 6)
        self.root = root
        self.state_dir = state_dir
        self.python_executable = python_executable
        self.node_executable = node_executable
        self.roles = roles
        self.backend_port = backend_port
        self.frontend_port = frontend_port
        self.host = host
        self.startup_timeout = startup_timeout
        self.stop_grace_seconds = stop_grace_seconds
        self.allow_ephemeral_ports = allow_ephemeral_ports
        self.dependency_probe = dependency_probe
        self.backend_argv = None if backend_argv is None else tuple(backend_argv)
        self.frontend_argv = None if frontend_argv is None else tuple(frontend_argv)
        self.mode = mode
        self.run_build = run_build
        self.detector_manifest = detector_manifest
        self.reconstructor_manifest = reconstructor_manifest


def math_finite_positive(value: float) -> bool:
    return type(value) in {int, float} and value > 0 and value == value and value != float("inf")


def _emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local_run.py",
        description="检查、启动、停止或诊断本机后端与前端。不安装依赖，不授予模型就绪。",
    )
    parser.add_argument("command", choices=("check", "status", "start", "stop", "diagnose"))
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--python", type=Path, default=None, dest="python_executable")
    parser.add_argument("--node", default=None, dest="node_executable")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--backend-only", action="store_true")
    group.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--detector-manifest", type=Path, default=None)
    parser.add_argument("--reconstructor-manifest", type=Path, default=None)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    return parser


def plan_from_namespace(args: argparse.Namespace) -> Plan:
    if args.command in {"stop", "status"} and (
        args.detector_manifest is not None or args.reconstructor_manifest is not None
    ):
        raise LocalRunError(
            "MANIFEST_FLAG_SCOPE",
            "模型路径只在 check、start、diagnose 设置，且不改写清单。",
            6,
        )
    root = resolve_root(args.root)
    roles: tuple[str, ...]
    if args.backend_only:
        roles = ("backend",)
    elif args.frontend_only:
        roles = ("frontend",)
    else:
        roles = ("backend", "frontend")
    mode = "production" if args.production else "dev"
    manifests = {}
    if args.detector_manifest is not None:
        manifests["detector_manifest"] = resolve_manifest_argument(root, args.detector_manifest)
    if args.reconstructor_manifest is not None:
        manifests["reconstructor_manifest"] = resolve_manifest_argument(
            root, args.reconstructor_manifest
        )
    return Plan(
        root=root,
        state_dir=resolve_state_dir(root, args.state_dir),
        python_executable=Path(args.python_executable)
        if args.python_executable is not None
        else default_python(root),
        node_executable=args.node_executable or default_node(),
        roles=roles,
        frontend_port=PRODUCTION_FRONTEND_PORT if mode == "production" else FRONTEND_PORT,
        startup_timeout=args.startup_timeout,
        mode=mode,
        **manifests,
    )


def main(argv: Sequence[str] | None = None) -> int:
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        plan = plan_from_namespace(args)
        with state_lock(plan.state_dir):
            if args.command == "check":
                payload, code = check_report(plan)
            elif args.command == "status":
                payload, code = status_report(plan), 0
            elif args.command == "start":
                payload, code = start_services(plan), 0
            elif args.command == "stop":
                payload, code = stop_services(plan), 0
            else:
                payload, code = diagnose_report(
                    plan, args.detector_manifest, args.reconstructor_manifest
                )
        _emit(payload)
        return code
    except LocalRunError as error:
        payload = base_payload("error")
        payload.update({"code": error.code, "detail": error.detail}, **error.extra)
        _emit(payload)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
