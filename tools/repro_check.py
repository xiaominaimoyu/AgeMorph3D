"""Read-only L02 preparation check.

Compares the local Python 3.11 virtualenv and npm tree with the lock files,
hashes those lock files, and optionally hashes model artifacts named by a
manifest. It then asks tools/local_run.py to start, reads /api/health, and
stops. It does not install packages, edit manifests, or sign off L02.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

HOST = "127.0.0.1"
BACKEND_PORT = 8000
DEV_FRONTEND_PORT = 5173
PRODUCTION_FRONTEND_PORT = 4173
PROJECT_NAME = "agemorph3d-backend"
SCHEMA_VERSION = 1
IGNORED_ROOTS = ("output", "logs")
INSTALLER_STEMS = frozenset(
    {"apt", "apt-get", "choco", "npm", "npx", "pip", "pip3", "uv", "winget"}
)
VERSION_CODE = "import sys; print(sys.version.split()[0])"
DISTRIBUTIONS_CODE = """
import importlib.metadata as metadata
import json
rows = []
for dist in metadata.distributions():
    name = dist.metadata["Name"]
    if name:
        rows.append({"name": name, "version": dist.version})
print(json.dumps(rows))
""".strip()
MAX_REPORT_LIST = 40


class ReproCheckError(Exception):
    def __init__(self, code: str, detail: str, exit_code: int = 6) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.exit_code = exit_code


class MarkerError(ValueError):
    """A lock-file environment marker used a form this check does not evaluate."""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def marker_env(*, extra: str) -> dict[str, str]:
    return {
        "extra": extra,
        "implementation_name": sys.implementation.name,
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "python_full_version": platform.python_version(),
        "python_version": f"{sys.version_info[0]}.{sys.version_info[1]}",
        "sys_platform": sys.platform,
    }


def _skip(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        return_index = index + 1
        index = return_index
    return index


def _identifier(text: str, index: int) -> tuple[str, int]:
    start = index
    while index < len(text) and (text[index].isalnum() or text[index] == "_"):
        index += 1
    if start == index:
        raise MarkerError(text)
    return text[start:index], index


def _quoted(text: str, index: int) -> tuple[str, int]:
    quote = text[index]
    if quote not in {"'", '"'}:
        raise MarkerError(text)
    end = text.find(quote, index + 1)
    if end < 0:
        raise MarkerError(text)
    return text[index + 1 : end], end + 1


def _keyword(text: str, index: int, word: str) -> bool:
    if not text.startswith(word, index):
        return False
    after = index + len(word)
    return after == len(text) or not (text[after].isalnum() or text[after] == "_")


def _parse_or(text: str, index: int, env: Mapping[str, str]) -> tuple[bool, int]:
    value, index = _parse_and(text, index, env)
    while True:
        index = _skip(text, index)
        if _keyword(text, index, "or"):
            other, index = _parse_and(text, index + 2, env)
            value = value or other
            continue
        return value, index


def _parse_and(text: str, index: int, env: Mapping[str, str]) -> tuple[bool, int]:
    value, index = _parse_primary(text, index, env)
    while True:
        index = _skip(text, index)
        if _keyword(text, index, "and"):
            other, index = _parse_primary(text, index + 3, env)
            value = value and other
            continue
        return value, index


def _parse_primary(text: str, index: int, env: Mapping[str, str]) -> tuple[bool, int]:
    index = _skip(text, index)
    if index >= len(text):
        raise MarkerError(text)
    if text[index] == "(":
        value, index = _parse_or(text, index + 1, env)
        index = _skip(text, index)
        if index >= len(text) or text[index] != ")":
            raise MarkerError(text)
        return value, index + 1
    name, index = _identifier(text, index)
    index = _skip(text, index)
    if text.startswith("==", index):
        operator = "=="
        index += 2
    elif text.startswith("!=", index):
        operator = "!="
        index += 2
    else:
        raise MarkerError(text)
    index = _skip(text, index)
    expected, index = _quoted(text, index)
    if name not in env:
        raise MarkerError(name)
    actual = env[name]
    return (actual == expected) if operator == "==" else (actual != expected), index


def marker_applies(expression: str | None, env: Mapping[str, str]) -> bool:
    if expression is None or not expression.strip():
        return True
    value, index = _parse_or(expression, 0, env)
    if expression[index:].strip():
        raise MarkerError(expression)
    return value


def _edges(
    items: Sequence[Mapping[str, object]] | None,
) -> list[tuple[str, tuple[str, ...], str | None]]:
    edges = []
    for item in items or []:
        name = item.get("name")
        if not isinstance(name, str):
            continue
        extra = item.get("extra") or []
        extras = tuple(extra) if isinstance(extra, list) else ()
        marker = item.get("marker")
        edges.append((name, extras, marker if isinstance(marker, str) else None))
    return edges


def _closure(
    packages: Mapping[str, Mapping[str, object]],
    roots: Sequence[tuple[str, tuple[str, ...], str | None]],
    env_base: Mapping[str, str],
    extra_name: str,
) -> dict[str, str]:
    env = dict(env_base)
    env["extra"] = extra_name
    wanted: dict[str, str] = {}
    stack = [(name, extras) for name, extras, marker in roots if marker_applies(marker, env)]
    seen: set[tuple[str, tuple[str, ...]]] = set()
    while stack:
        name, extras = stack.pop()
        key = (name, extras)
        if key in seen:
            continue
        seen.add(key)
        package = packages[name]
        if name != PROJECT_NAME:
            version = package.get("version")
            if not isinstance(version, str):
                raise MarkerError(name)
            wanted.setdefault(name, version)
        edges = _edges(package.get("dependencies"))  # type: ignore[arg-type]
        optional = package.get("optional-dependencies") or {}
        if isinstance(optional, dict):
            for extra in extras:
                group = optional.get(extra)
                if isinstance(group, list):
                    edges.extend(_edges(group))
        for dep_name, dep_extras, marker in edges:
            if marker_applies(marker, env):
                stack.append((dep_name, dep_extras))
    return wanted


def locked_python_groups(
    lock: Mapping[str, object], env_base: Mapping[str, str]
) -> dict[str, dict[str, str]]:
    raw_packages = lock.get("package")
    if not isinstance(raw_packages, list):
        raise ReproCheckError("LOCK_UNREADABLE", "uv.lock 没有 package 列表。", 1)
    packages: dict[str, Mapping[str, object]] = {}
    for item in raw_packages:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            packages[item["name"]] = item
    project = packages[PROJECT_NAME]
    base = _closure(packages, _edges(project.get("dependencies")), env_base, "")  # type: ignore[arg-type]
    version = project.get("version")
    if isinstance(version, str):
        base[PROJECT_NAME] = version
    dev_table = project.get("dev-dependencies") or {}
    dev_roots = dev_table.get("dev") if isinstance(dev_table, dict) else None
    inference_table = project.get("optional-dependencies") or {}
    inference_roots = (
        inference_table.get("inference") if isinstance(inference_table, dict) else None
    )
    return {
        "base": base,
        "dev": _closure(packages, _edges(dev_roots), env_base, ""),  # type: ignore[arg-type]
        "inference": _closure(packages, _edges(inference_roots), env_base, "inference"),  # type: ignore[arg-type]
    }


def lockfile_hash_gaps(lock: Mapping[str, object]) -> list[str]:
    missing = []
    packages = lock.get("package")
    if not isinstance(packages, list):
        return ["package"]
    for package in packages:
        if not isinstance(package, dict):
            continue
        source = package.get("source") or {}
        if isinstance(source, dict) and (source.get("editable") or source.get("virtual")):
            continue
        hashes = []
        sdist = package.get("sdist")
        if isinstance(sdist, dict) and isinstance(sdist.get("hash"), str):
            hashes.append(sdist["hash"])
        wheels = package.get("wheels")
        if isinstance(wheels, list):
            hashes.extend(
                item["hash"]
                for item in wheels
                if isinstance(item, dict) and isinstance(item.get("hash"), str)
            )
        name = package.get("name")
        if not hashes or any(not str(item).startswith("sha256:") for item in hashes):
            missing.append(str(name))
    return missing


def python_matches(version: str | None, constraint: str) -> bool:
    if not version:
        return False
    text = constraint.strip()
    if text.startswith("==") and text.endswith(".*"):
        prefix = text[2:-2]
        return version == prefix or version.startswith(prefix + ".")
    return False


def _version_tuple(version: str) -> tuple[int, ...]:
    numbers = []
    for part in version.lstrip("v").split("."):
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        numbers.append(int(digits))
    return tuple(numbers)


def node_matches(version: str | None, constraint: str) -> bool:
    if not version:
        return False
    actual = _version_tuple(version)
    for part in constraint.split("||"):
        expr = part.strip()
        if expr.startswith(">="):
            if actual >= _version_tuple(expr[2:]):
                return True
            continue
        raise MarkerError(expr)
    return False


def npm_platform() -> dict[str, str]:
    machine = platform.machine().lower()
    cpu = {
        "x86_64": "x64",
        "amd64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "i686": "ia32",
        "x86": "ia32",
    }.get(machine, machine)
    libc_name, _libc_version = platform.libc_ver()
    libc = "glibc" if libc_name == "glibc" else ""
    system = {"linux": "linux", "win32": "win32", "darwin": "darwin", "cygwin": "win32"}.get(
        sys.platform, sys.platform
    )
    return {"os": system, "cpu": cpu, "libc": libc}


def npm_package_required(key: str, entry: Mapping[str, object], host: Mapping[str, str]) -> bool:
    if not key.startswith("node_modules/") or not isinstance(entry.get("version"), str):
        return False
    if not entry.get("optional"):
        return True
    for field, value in (("os", host["os"]), ("cpu", host["cpu"]), ("libc", host["libc"])):
        allowed = entry.get(field)
        if isinstance(allowed, list) and value not in allowed:
            return False
    return True


def default_python(root: Path) -> Path:
    folder = "Scripts" if os.name == "nt" else "bin"
    name = "python.exe" if os.name == "nt" else "python"
    return root / "backend" / ".venv" / folder / name


def default_node() -> str:
    configured = os.environ.get("AGEMORPH_NODE")
    if configured:
        return configured
    if os.name == "nt":
        candidate = Path(r"D:\JAVA run tools\node.exe")
        if candidate.is_file():
            return str(candidate)
    return "node"


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def command_exists(command: str) -> bool:
    path = Path(command)
    if path.is_file():
        return True
    return "/" not in command and "\\" not in command and _which(command) is not None


def run_text(argv: Sequence[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    stem = Path(str(argv[0])).stem.lower()
    version_query = stem == "uv" and list(argv[1:]) == ["--version"]
    if stem in INSTALLER_STEMS and not version_query:
        raise ReproCheckError("INSTALL_FORBIDDEN", "复现检查不安装依赖，也不调用安装器。", 2)
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def probe_python(executable: Path, root: Path) -> dict[str, object]:
    if not executable.is_file():
        return {"path": str(executable), "exists": False, "version": None}
    completed = run_text([str(executable), "-B", "-c", VERSION_CODE], root, 20)
    version = completed.stdout.strip() if completed.returncode == 0 else None
    return {
        "path": str(executable),
        "exists": True,
        "version": version,
        "returncode": completed.returncode,
    }


def installed_distributions(executable: Path, root: Path) -> list[dict[str, str]]:
    completed = run_text([str(executable), "-B", "-c", DISTRIBUTIONS_CODE], root, 30)
    if completed.returncode != 0:
        raise ReproCheckError("DIST_QUERY_FAILED", "未能读取虚拟环境中已安装的分发包。", 1)
    loaded = json.loads(completed.stdout)
    if not isinstance(loaded, list):
        raise ReproCheckError("DIST_QUERY_FAILED", "已安装分发包清单不是列表。", 1)
    rows = []
    for item in loaded:
        if (
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("version"), str)
        ):
            rows.append({"name": item["name"], "version": item["version"]})
    return rows


def compare_distributions(
    required: Mapping[str, str], installed: Sequence[Mapping[str, str]]
) -> dict[str, object]:
    found: dict[str, str] = {}
    mismatch = []
    for item in installed:
        key = normalize_name(item["name"])
        previous = found.get(key)
        if previous is not None and previous != item["version"]:
            mismatch.append(
                {"name": item["name"], "locked": previous, "installed": item["version"]}
            )
        found[key] = item["version"]
    missing = []
    for name, version in sorted(required.items()):
        actual = found.get(normalize_name(name))
        if actual is None:
            missing.append({"name": name, "locked": version})
        elif actual != version:
            mismatch.append({"name": name, "locked": version, "installed": actual})
    return {
        "required_count": len(required),
        "matched_count": len(required) - len(missing) - len(mismatch),
        "missing": missing[:MAX_REPORT_LIST],
        "missing_count": len(missing),
        "mismatch": mismatch[:MAX_REPORT_LIST],
        "mismatch_count": len(mismatch),
    }


def probe_node(executable: str, root: Path) -> dict[str, object]:
    if not command_exists(executable):
        return {"path": executable, "exists": False, "version": None}
    completed = run_text([executable, "--version"], root, 20)
    version = completed.stdout.strip().splitlines()[0] if completed.returncode == 0 else None
    return {
        "path": executable,
        "exists": True,
        "version": version,
        "returncode": completed.returncode,
    }


def probe_uv(root: Path) -> dict[str, object]:
    if _which("uv") is None:
        return {
            "on_path": False,
            "version": None,
            "pinned_by_uv_lock": False,
            "detail": "uv.lock 不记录 uv 自身版本。未在 PATH 上发现 uv。",
        }
    completed = run_text(["uv", "--version"], root, 20)
    version = completed.stdout.strip().splitlines()[0] if completed.returncode == 0 else None
    return {
        "on_path": True,
        "version": version,
        "pinned_by_uv_lock": False,
        "detail": "uv.lock 不记录 uv 自身版本。这里只报告本机 uv --version。",
    }


def git_snapshot(root: Path) -> dict[str, object]:
    def invoke(args: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return run_text(["git", "-C", str(root), *args], root, 20)
        except (OSError, subprocess.TimeoutExpired, ReproCheckError):
            return None

    commit = invoke(["rev-parse", "HEAD"])
    branch = invoke(["rev-parse", "--abbrev-ref", "HEAD"])
    status = invoke(["status", "--porcelain"])
    if commit is None or commit.returncode != 0:
        return {
            "available": False,
            "commit": None,
            "branch": None,
            "dirty": None,
            "status_count": None,
        }
    lines = status.stdout.splitlines() if status and status.returncode == 0 else []
    return {
        "available": True,
        "commit": commit.stdout.strip(),
        "branch": branch.stdout.strip() if branch and branch.returncode == 0 else None,
        "dirty": bool(lines),
        "status_count": len(lines),
        "status_preview": lines[:MAX_REPORT_LIST],
    }


def resolve_inside_project(root: Path, requested: Path | None, default: Path) -> Path:
    path = default if requested is None else requested
    raw = path.expanduser()
    chosen = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not chosen.is_relative_to(root):
        raise ReproCheckError("OUTPUT_OUTSIDE_PROJECT", "报告只能写在项目内。", 6)
    relative = chosen.relative_to(root)
    if not relative.parts or relative.parts[0] not in IGNORED_ROOTS:
        raise ReproCheckError(
            "OUTPUT_NOT_IGNORED",
            "报告只能写在被 Git 忽略的 output/ 或 logs/ 目录中。",
            6,
        )
    return chosen


def _relative_artifact(value: str) -> bool:
    normalized = value.replace("\\", "/")
    parts = Path(normalized).parts
    return (
        not value.startswith(("/", "\\"))
        and ".." not in parts
        and ":" not in normalized
        and normalized not in {"", "."}
    )


def inspect_manifest(role: str, path: Path | None) -> dict[str, object]:
    result: dict[str, object] = {
        "role": role,
        "configured": path is not None,
        "manifest_status": "not_configured",
        "manifest_sha256": None,
        "registered_license_status": None,
        "artifacts": [],
        "grants_service_readiness": False,
    }
    if path is None:
        return result
    try:
        if path.suffix.lower() != ".json" or not path.is_file():
            result["manifest_status"] = "missing" if not path.exists() else "invalid"
            return result
        raw = path.read_bytes()
        if len(raw) > 64 * 1024:
            result["manifest_status"] = "oversized"
            return result
        loaded = json.loads(raw)
        if not isinstance(loaded, dict) or not isinstance(loaded.get("artifacts"), list):
            result["manifest_status"] = "invalid"
            return result
    except (OSError, json.JSONDecodeError):
        result["manifest_status"] = "invalid"
        return result
    result["manifest_status"] = "valid"
    result["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    license_status = loaded.get("license_status")
    result["registered_license_status"] = (
        license_status if isinstance(license_status, str) else None
    )
    root = path.parent.resolve()
    artifacts = []
    for item in loaded["artifacts"]:
        if not isinstance(item, dict):
            artifacts.append({"status": "invalid"})
            continue
        relative = item.get("path")
        expected = item.get("sha256")
        size = item.get("size_bytes")
        artifact_role = item.get("role")
        record: dict[str, object] = {
            "role": artifact_role if isinstance(artifact_role, str) else None,
            "relative_path": relative if isinstance(relative, str) else None,
            "expected_sha256": expected if isinstance(expected, str) else None,
            "expected_size_bytes": size if type(size) is int else None,
            "observed_sha256": None,
            "observed_size_bytes": None,
            "status": "invalid",
        }
        if (
            not isinstance(relative, str)
            or not _relative_artifact(relative)
            or not isinstance(expected, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", expected)
            or type(size) is not int
            or size <= 0
        ):
            artifacts.append(record)
            continue
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            record["status"] = "outside_manifest_directory"
        elif not candidate.exists():
            record["status"] = "missing"
        elif not candidate.is_file():
            record["status"] = "not_regular_file"
        else:
            observed_size = candidate.stat().st_size
            record["observed_size_bytes"] = observed_size
            if observed_size != size:
                record["status"] = "size_mismatch"
            else:
                observed = sha256_file(candidate)
                record["observed_sha256"] = observed
                record["status"] = (
                    "match" if observed.lower() == expected.lower() else "hash_mismatch"
                )
        artifacts.append(record)
    result["artifacts"] = artifacts
    return result


def _problem(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def build_report(
    root: Path,
    *,
    python_executable: Path,
    node_executable: str,
    detector_manifest: Path | None,
    reconstructor_manifest: Path | None,
    smoke: dict[str, object] | None,
    env_base: Mapping[str, str] | None = None,
) -> dict[str, object]:
    problems: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    env = dict(env_base or marker_env(extra=""))
    uv_path = root / "backend" / "uv.lock"
    npm_path = root / "frontend" / "package-lock.json"
    locks: dict[str, object] = {}
    groups = {"base": {}, "dev": {}, "inference": {}}
    python_constraint = None
    node_constraint = None
    if not uv_path.is_file():
        problems.append(_problem("LOCK_MISSING", "缺少 backend/uv.lock。"))
    else:
        lock = tomllib.loads(uv_path.read_text(encoding="utf-8"))
        python_constraint = (
            lock.get("requires-python") if isinstance(lock.get("requires-python"), str) else None
        )
        hash_gaps = lockfile_hash_gaps(lock)
        locks["uv_lock"] = {
            "path": "backend/uv.lock",
            "sha256": sha256_file(uv_path),
            "bytes": uv_path.stat().st_size,
            "requires_python": python_constraint,
            "packages_missing_hash": hash_gaps,
        }
        if hash_gaps:
            problems.append(_problem("LOCK_HASH_MISSING", "uv.lock 中有包没有 sha256。"))
        try:
            groups = locked_python_groups(lock, env)
        except (KeyError, MarkerError, ReproCheckError) as error:
            problems.append(
                _problem("LOCK_UNREADABLE", f"无法按本机平台解释 uv.lock：{type(error).__name__}。")
            )
    if not npm_path.is_file():
        problems.append(_problem("LOCK_MISSING", "缺少 frontend/package-lock.json。"))
        npm_lock: dict[str, object] | None = None
    else:
        try:
            parsed_npm = json.loads(npm_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            problems.append(_problem("LOCK_UNREADABLE", "package-lock.json 不是合法 JSON。"))
            npm_lock = None
            parsed_npm = None
        if isinstance(parsed_npm, dict):
            npm_lock = parsed_npm
        elif parsed_npm is not None:
            problems.append(_problem("LOCK_UNREADABLE", "package-lock.json 的顶层不是对象。"))
            npm_lock = None
        if isinstance(npm_lock, dict):
            root_package = (
                npm_lock.get("packages", {}).get("", {})
                if isinstance(npm_lock.get("packages"), dict)
                else {}
            )
            engines = root_package.get("engines", {}) if isinstance(root_package, dict) else {}
            node_constraint = engines.get("node") if isinstance(engines, dict) else None
            raw_packages = npm_lock.get("packages")
            packages = raw_packages if isinstance(raw_packages, dict) else {}
            missing_integrity = [
                key
                for key, entry in packages.items()
                if isinstance(entry, dict)
                and npm_package_required(key, entry, npm_platform())
                and not (
                    isinstance(entry.get("integrity"), str) and entry["integrity"].startswith("sha")
                )
            ]
            locks["npm_lock"] = {
                "path": "frontend/package-lock.json",
                "sha256": sha256_file(npm_path),
                "bytes": npm_path.stat().st_size,
                "lockfileVersion": npm_lock.get("lockfileVersion"),
                "node_engines": node_constraint,
                "packages_missing_integrity": missing_integrity[:MAX_REPORT_LIST],
                "packages_missing_integrity_count": len(missing_integrity),
            }
            if missing_integrity:
                problems.append(
                    _problem("LOCK_HASH_MISSING", "package-lock.json 中有适用包没有 integrity。")
                )
    python_info = probe_python(python_executable, root)
    node_info = probe_node(node_executable, root)
    if not python_info["exists"]:
        problems.append(
            _problem(
                "MISSING_BACKEND_RUNTIME",
                "没有项目虚拟环境解释器。检查不会安装它，也不改用系统 Python 充当服务。",
            )
        )
    elif python_constraint and not python_matches(
        str(python_info.get("version")), str(python_constraint)
    ):
        problems.append(
            _problem("PYTHON_VERSION", "虚拟环境 Python 不满足 uv.lock 的 requires-python。")
        )
    if not node_info["exists"]:
        problems.append(_problem("MISSING_NODE", "没有找到 Node。检查不会安装它。"))
    elif isinstance(node_constraint, str):
        try:
            matched = node_matches(str(node_info.get("version")), node_constraint)
        except MarkerError:
            matched = False
            problems.append(
                _problem(
                    "NODE_CONSTRAINT_UNSUPPORTED",
                    "package-lock.json 的 engines.node 不是本检查能判断的形式。",
                )
            )
        if not matched and "NODE_CONSTRAINT_UNSUPPORTED" not in {item["code"] for item in problems}:
            problems.append(
                _problem("NODE_VERSION", "Node 不满足 package-lock.json 根 engines.node。")
            )
    distribution_report: dict[str, object] = {"skipped": True}
    if python_info["exists"] and groups["base"]:
        required: dict[str, str] = {}
        required.update(groups["base"])
        required.update(groups["dev"])
        required.update(groups["inference"])
        try:
            distribution_report = compare_distributions(
                required, installed_distributions(python_executable, root)
            )
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ReproCheckError):
            distribution_report = {"skipped": True}
            problems.append(_problem("DIST_QUERY_FAILED", "未能比较虚拟环境与 uv.lock。"))
        else:
            if distribution_report["missing_count"] or distribution_report["mismatch_count"]:
                problems.append(
                    _problem(
                        "PYTHON_PACKAGES", "已安装的 Python 包与 uv.lock 的版本不一致或有缺失。"
                    )
                )
    npm_report: dict[str, object] = {"skipped": True}
    if isinstance(npm_lock, dict) and isinstance(npm_lock.get("packages"), dict):
        host = npm_platform()
        missing = []
        mismatch = []
        required_count = 0
        for key, entry in npm_lock["packages"].items():
            if not isinstance(entry, dict) or not npm_package_required(key, entry, host):
                continue
            required_count += 1
            package_json = root / "frontend" / key / "package.json"
            if not package_json.is_file():
                missing.append(key)
                continue
            try:
                installed = json.loads(package_json.read_text(encoding="utf-8")).get("version")
            except (OSError, json.JSONDecodeError):
                missing.append(key)
                continue
            if installed != entry.get("version"):
                mismatch.append(
                    {"path": key, "locked": entry.get("version"), "installed": installed}
                )
        npm_report = {
            "required_count": required_count,
            "missing_count": len(missing),
            "mismatch_count": len(mismatch),
            "missing": missing[:MAX_REPORT_LIST],
            "mismatch": mismatch[:MAX_REPORT_LIST],
        }
        if not (root / "frontend" / "node_modules").is_dir():
            problems.append(
                _problem(
                    "MISSING_FRONTEND_RUNTIME", "没有 frontend/node_modules。检查不会执行 npm ci。"
                )
            )
        elif missing or mismatch:
            problems.append(
                _problem("NPM_PACKAGES", "node_modules 与 package-lock.json 的版本不一致或有缺失。")
            )
    models = {
        "detector": inspect_manifest("detector", detector_manifest),
        "reconstructor": inspect_manifest("reconstructor", reconstructor_manifest),
    }
    configured = detector_manifest is not None or reconstructor_manifest is not None
    if not configured:
        gaps.append(
            _problem(
                "MODELS_NOT_CONFIGURED",
                "没有传入模型清单。未配置的权重按缺失报告，不编造文件或哈希。",
            )
        )
    else:
        for model in models.values():
            if model["manifest_status"] != "valid":
                problems.append(_problem("MANIFEST_UNREADABLE", "传入的模型清单缺失或无法读取。"))
                continue
            for artifact in model["artifacts"]:
                if not isinstance(artifact, dict):
                    continue
                status = artifact.get("status")
                if status == "missing":
                    problems.append(_problem("ARTIFACT_MISSING", "清单点名的模型文件不存在。"))
                elif status != "match":
                    problems.append(
                        _problem("ARTIFACT_HASH", "清单点名的模型文件大小或哈希不一致。")
                    )
            if model.get("registered_license_status") == "unresolved":
                gaps.append(
                    _problem(
                        "LICENSE_REGISTRATION_UNRESOLVED",
                        "清单登记仍是 unresolved。文件哈希不能把它变成 ready。",
                    )
                )
    git_info = git_snapshot(root)
    if git_info.get("dirty"):
        gaps.append(
            _problem("GIT_WORKTREE_DIRTY", "工作区相对 HEAD 有未提交差异。正式复现应记录这个偏差。")
        )
    uv_info = probe_uv(root)
    gaps.append(_problem("UV_VERSION_NOT_IN_LOCK", str(uv_info["detail"])))
    if smoke is None:
        gaps.append(_problem("SMOKE_SKIPPED", "本次没有做启动检查。"))
    elif not smoke.get("ok"):
        problems.extend(item for item in smoke.get("problems", []) if isinstance(item, dict))
    if smoke and smoke.get("network_isolation", {}).get("status") == "not_applied":
        gaps.append(
            _problem(
                "NETWORK_ISOLATION_NOT_APPLIED",
                "没有网络命名空间权限。烟雾检查只访问 127.0.0.1，没有改系统配置。",
            )
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "task": "L02",
        "role": "preparation_check",
        "l02_executed": False,
        "l02_signed_off": False,
        "conclusion": "preparation_check_only",
        "installs_dependencies": False,
        "modifies_manifests": False,
        "grants_service_readiness": False,
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "git": git_info,
        "locks": locks,
        "python": python_info,
        "python_constraint": python_constraint,
        "node": node_info,
        "node_constraint": node_constraint,
        "uv": uv_info,
        "python_groups": {name: sorted(group) for name, group in groups.items()},
        "python_packages": distribution_report,
        "npm_packages": npm_report,
        "models": models,
        "smoke": smoke,
        "problems": problems,
        "gaps": gaps,
        "detail": "这是 L02 准备检查，不是另一成员的干净环境复现，也不能填写为通过。",
    }
    return report


def launcher_argv(
    root: Path,
    state_dir: Path,
    command: str,
    *,
    mode: str,
    python_executable: Path,
    node_executable: str,
    detector_manifest: Path | None,
    reconstructor_manifest: Path | None,
) -> list[str]:
    argv = [
        sys.executable,
        "-B",
        str(root / "tools" / "local_run.py"),
        command,
        "--root",
        str(root),
        "--state-dir",
        str(state_dir),
        "--python",
        str(python_executable),
        "--node",
        node_executable,
    ]
    if mode == "production":
        argv.append("--production")
    if command == "start":
        if detector_manifest is not None:
            argv.extend(["--detector-manifest", str(detector_manifest)])
        if reconstructor_manifest is not None:
            argv.extend(["--reconstructor-manifest", str(reconstructor_manifest)])
    stem = Path(argv[0]).stem.lower()
    if stem in INSTALLER_STEMS or any(
        Path(str(item)).stem.lower() in INSTALLER_STEMS for item in argv[2:]
    ):
        raise ReproCheckError("INSTALL_FORBIDDEN", "烟雾检查只调用现有启动器。", 2)
    return argv


def _read_json_stdout(completed: subprocess.CompletedProcess[str]) -> dict[str, object] | None:
    try:
        loaded = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def fetch_health(
    port: int = BACKEND_PORT, timeout: float = 2.0
) -> tuple[int | None, dict[str, object] | None]:
    if port <= 0 or port > 65535:
        raise ReproCheckError("HOST_NOT_LOOPBACK", "健康检查只访问 127.0.0.1。", 6)
    url = f"http://{HOST}:{port}/api/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(64 * 1024)
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read(64 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, None
    try:
        loaded = json.loads(body)
    except json.JSONDecodeError:
        return status, None
    return status, loaded if isinstance(loaded, dict) else None


def classify_health(payload: Mapping[str, object] | None) -> str:
    if not isinstance(payload, dict):
        return "unparsed"
    models = payload.get("models")
    if not isinstance(models, dict):
        return "unparsed"
    states = []
    for name in ("detector", "reconstructor"):
        item = models.get(name)
        if isinstance(item, dict) and isinstance(item.get("state"), str):
            states.append(item["state"])
    if not states:
        return "unparsed"
    if any(state == "loading" for state in states):
        return "loading"
    if any(state == "error" for state in states):
        return "error"
    if all(state == "missing" for state in states):
        return "missing"
    if all(state == "ready" for state in states):
        return "ready"
    return "other"


def _proc_ip(hexaddr: str) -> str:
    if len(hexaddr) == 8:
        return socket.inet_ntoa(bytes.fromhex(hexaddr)[::-1])
    words = [bytes.fromhex(hexaddr[index : index + 8])[::-1] for index in range(0, 32, 8)]
    return socket.inet_ntop(socket.AF_INET6, b"".join(words))


def _loopback(ip: str) -> bool:
    return (
        ip == "0.0.0.0"
        or ip.startswith("127.")
        or ip in {"::", "::1"}
        or ip.startswith("::ffff:127.")
    )


def non_loopback_sockets(pid: int) -> list[str]:
    """Return remote addresses for sockets owned by this process tree."""
    if os.name != "posix":
        return []
    inodes: set[str] = set()

    def collect(process: int, depth: int) -> None:
        if depth > 8:
            return
        fd_dir = Path(f"/proc/{process}/fd")
        if fd_dir.is_dir():
            for entry in fd_dir.iterdir():
                try:
                    target = os.readlink(entry)
                except OSError:
                    continue
                if target.startswith("socket:[") and target.endswith("]"):
                    inodes.add(target[8:-1])
        children = Path(f"/proc/{process}/task/{process}/children")
        try:
            text = children.read_text(encoding="utf-8")
        except OSError:
            return
        for child in text.split():
            if child.isdigit():
                collect(int(child), depth + 1)

    collect(pid, 0)
    found = []
    for name in ("tcp", "tcp6"):
        table = Path(f"/proc/{pid}/net/{name}")
        try:
            lines = table.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[9] not in inodes:
                continue
            remote, _port = fields[2].split(":")
            if remote in {"00000000", "00000000000000000000000000000000"}:
                continue
            try:
                ip = _proc_ip(remote)
            except (OSError, ValueError):
                found.append(remote)
                continue
            if not _loopback(ip):
                found.append(ip)
    return found


def attempt_network_isolation() -> dict[str, object]:
    if os.name != "posix":
        return {
            "status": "not_applicable",
            "errno": None,
            "detail": "Windows 上不创建网络命名空间。烟雾检查只请求 127.0.0.1。",
        }
    import ctypes

    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
    except OSError:
        return {"status": "not_applicable", "errno": None, "detail": "没有可用的 libc.unshare。"}
    if libc.unshare(0x40000000) != 0:
        return {
            "status": "not_applied",
            "errno": ctypes.get_errno(),
            "detail": "unshare(CLONE_NEWNET) 被拒绝。没有使用 sudo，也没有改系统配置。",
        }
    try:
        _bring_up_loopback()
    except OSError as error:
        return {
            "status": "applied_loopback_failed",
            "errno": error.errno,
            "detail": "网络命名空间已建立，但回环接口没有起来。",
        }
    return {
        "status": "applied",
        "errno": 0,
        "detail": "烟雾进程在独立网络命名空间中，只把回环接口打开。",
    }


def _bring_up_loopback() -> None:
    import fcntl
    import struct

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    flags = struct.unpack("16sH14x", fcntl.ioctl(sock, 0x8913, struct.pack("16sH14x", b"lo", 0)))[1]
    fcntl.ioctl(sock, 0x8914, struct.pack("16sH14x", b"lo", flags | 0x1))


def _offline_env(base: Mapping[str, str]) -> dict[str, str]:
    env = {key: value for key, value in base.items() if "\0" not in key and "\0" not in value}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env.update(
        {
            "UV_OFFLINE": "1",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "npm_config_offline": "true",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    return env


def _service_pids(state_dir: Path) -> list[int]:
    path = state_dir / "state.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    services = loaded.get("services") if isinstance(loaded, dict) else None
    if not isinstance(services, dict):
        return []
    pids = []
    for record in services.values():
        if isinstance(record, dict) and type(record.get("pid")) is int:
            pids.append(record["pid"])
    return pids


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        try:
            sock.connect((HOST, port))
        except OSError:
            return False
    return True


def run_smoke(
    root: Path,
    state_dir: Path,
    *,
    mode: str,
    python_executable: Path,
    node_executable: str,
    detector_manifest: Path | None,
    reconstructor_manifest: Path | None,
    isolate: bool,
    launch,
    health,
) -> dict[str, object]:
    problems = []
    isolation = (
        attempt_network_isolation()
        if isolate
        else {
            "status": "not_requested",
            "errno": None,
            "detail": "调用方没有要求在本进程内隔离网络。",
        }
    )
    if isolation["status"] == "applied_loopback_failed":
        problems.append(_problem("NETWORK_ISOLATION_FAILED", str(isolation["detail"])))
        return {"ok": False, "mode": mode, "network_isolation": isolation, "problems": problems}
    os.environ.update(_offline_env(os.environ))
    frontend_port = PRODUCTION_FRONTEND_PORT if mode == "production" else DEV_FRONTEND_PORT
    steps = []

    def invoke(command: str, timeout: float) -> tuple[int, dict[str, object] | None]:
        argv = launcher_argv(
            root,
            state_dir,
            command,
            mode=mode,
            python_executable=python_executable,
            node_executable=node_executable,
            detector_manifest=detector_manifest,
            reconstructor_manifest=reconstructor_manifest,
        )
        code, payload = launch(argv, timeout)
        steps.append({"command": command, "returncode": code})
        return code, payload

    start_code, start_payload = invoke("start", 300 if mode == "production" else 90)
    if start_code != 0:
        launcher_code = start_payload.get("code") if isinstance(start_payload, dict) else None
        if launcher_code == "PORT_IN_USE" or start_code == 3:
            problems.append(
                _problem("PORT_IN_USE", "8000 或前端端口已有监听。检查不会结束未知进程。")
            )
        else:
            problems.append(
                _problem(
                    "SMOKE_FAILED",
                    "启动器 start 没有成功。没有安装依赖，也没有结束未知监听。",
                )
            )
    health_status = None
    health_body = None
    picture = "not_checked"
    if start_code == 0:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            health_status, health_body = health()
            picture = classify_health(health_body)
            if health_status == 200 and picture != "loading":
                break
            time.sleep(0.2)
        if health_status != 200:
            problems.append(_problem("SMOKE_FAILED", "启动后的 /api/health 不是 HTTP 200。"))
        capabilities = health_body.get("capabilities") if isinstance(health_body, dict) else None
        if isinstance(capabilities, dict) and (
            capabilities.get("age_morph") is True or capabilities.get("age_texture") is True
        ):
            problems.append(
                _problem("AGE_CAPABILITY_REPORTED", "健康检查报告了年龄能力。当前服务不应如此。")
            )
        if detector_manifest and reconstructor_manifest and picture == "missing":
            problems.append(
                _problem("HEALTH_IGNORED_MANIFEST", "已经传入清单，健康检查仍是未配置。")
            )
        remotes = []
        for pid in _service_pids(state_dir):
            remotes.extend(non_loopback_sockets(pid))
        if remotes:
            problems.append(_problem("NON_LOOPBACK_CONNECTION", "服务进程持有回环以外的连接。"))
    else:
        remotes = []
    stop_code, stop_payload = invoke("stop", 40)
    if stop_code != 0:
        problems.append(_problem("SMOKE_FAILED", "启动器 stop 没有完成。"))
    ports = {
        "backend": {"port": BACKEND_PORT, "accepting": _port_open(BACKEND_PORT)},
        "frontend": {"port": frontend_port, "accepting": _port_open(frontend_port)},
    }
    if start_code == 0 and any(item["accepting"] for item in ports.values()):
        problems.append(
            _problem("PORT_STILL_OPEN", "停止后 8000 或前端端口仍接受连接。检查不会结束未知进程。")
        )
    return {
        "ok": not problems,
        "mode": mode,
        "network_isolation": isolation,
        "steps": steps,
        "health_status": health_status,
        "health_picture": picture,
        "health": health_body,
        "non_loopback_remotes": remotes,
        "stop_returncode": stop_code,
        "stop": stop_payload,
        "ports_after_stop": ports,
        "problems": problems,
        "frontend_port": frontend_port,
    }


def _launch(argv: Sequence[str], timeout: float) -> tuple[int, dict[str, object] | None]:
    completed = subprocess.run(
        list(argv),
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=_offline_env(os.environ),
    )
    return completed.returncode, _read_json_stdout(completed)


def _manifest_argument(root: Path, value: Path | None, env_name: str) -> Path | None:
    if value is None:
        raw = os.environ.get(env_name)
        if raw is None or not raw.strip() or "\x00" in raw:
            return None
        value = Path(raw)
    raw_path = value.expanduser()
    return raw_path.resolve() if raw_path.is_absolute() else (root / raw_path).resolve()


def _write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def exit_code_for(report: Mapping[str, object]) -> int:
    problems = report.get("problems")
    if not isinstance(problems, list):
        return 1
    codes = {item.get("code") for item in problems if isinstance(item, dict)}
    if {"OUTPUT_OUTSIDE_PROJECT", "OUTPUT_NOT_IGNORED"} & codes:
        return 6
    if {"MISSING_BACKEND_RUNTIME", "MISSING_FRONTEND_RUNTIME", "MISSING_NODE"} & codes:
        return 2
    if "PORT_IN_USE" in codes:
        return 3
    if "PORT_STILL_OPEN" in codes:
        return 5
    if problems:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repro_check.py",
        description="只读核对锁文件、模型和启动器健康检查。不安装依赖，不签署 L02。",
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--python", type=Path, default=None, dest="python_executable")
    parser.add_argument("--node", default=None, dest="node_executable")
    parser.add_argument("--detector-manifest", type=Path, default=None)
    parser.add_argument("--reconstructor-manifest", type=Path, default=None)
    parser.add_argument("--smoke-mode", choices=("dev", "production", "both"), default="dev")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--smoke-worker", action="store_true")
    return parser


def _run_smoke_modes(args: argparse.Namespace, root: Path, state_root: Path) -> dict[str, object]:
    modes = ["dev", "production"] if args.smoke_mode == "both" else [args.smoke_mode]
    python_executable = args.python_executable or default_python(root)
    node_executable = args.node_executable or default_node()
    detector = _manifest_argument(root, args.detector_manifest, "AGEMORPH_DETECTOR_MANIFEST")
    reconstructor = _manifest_argument(
        root, args.reconstructor_manifest, "AGEMORPH_RECONSTRUCTOR_MANIFEST"
    )
    results = []
    for mode in modes:
        state_dir = state_root / mode
        result = run_smoke(
            root,
            state_dir,
            mode=mode,
            python_executable=python_executable,
            node_executable=node_executable,
            detector_manifest=detector,
            reconstructor_manifest=reconstructor,
            isolate=True,
            launch=_launch,
            health=fetch_health,
        )
        results.append(result)
        if not result["ok"]:
            break
    ok = all(item["ok"] for item in results)
    problems = [problem for item in results for problem in item["problems"]]
    return {"ok": ok, "modes": results, "problems": problems}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = (project_root() if args.root is None else args.root).expanduser().resolve()
    if not root.is_dir():
        raise ReproCheckError("ROOT_MISSING", "项目根目录不存在。", 6)
    output = resolve_inside_project(
        root, args.output, root / "output" / "repro-check" / "report.json"
    )
    state_root = resolve_inside_project(
        root, args.state_dir, root / "output" / "repro-check" / "state"
    )
    if args.smoke_worker:
        payload = _run_smoke_modes(args, root, state_root)
        _write(output, payload)
        return 0 if payload["ok"] else 1
    smoke: dict[str, object] | None
    if args.skip_smoke:
        smoke = None
    else:
        worker = [
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "--smoke-worker",
            "--root",
            str(root),
            "--output",
            str(output.with_name("smoke.json")),
            "--state-dir",
            str(state_root),
            "--smoke-mode",
            args.smoke_mode,
        ]
        if args.python_executable is not None:
            worker.extend(["--python", str(args.python_executable)])
        if args.node_executable is not None:
            worker.extend(["--node", args.node_executable])
        if args.detector_manifest is not None:
            worker.extend(["--detector-manifest", str(args.detector_manifest)])
        if args.reconstructor_manifest is not None:
            worker.extend(["--reconstructor-manifest", str(args.reconstructor_manifest)])
        timeout = (
            700 if args.smoke_mode == "both" else (360 if args.smoke_mode == "production" else 180)
        )
        completed = subprocess.Popen(
            worker,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=_offline_env(os.environ),
        )
        try:
            completed.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(completed.pid, signal.SIGKILL)
            completed.wait(timeout=10)
            smoke = {
                "ok": False,
                "problems": [
                    _problem("SMOKE_FAILED", "启动检查超时。已尝试停止本次启动器记录的进程。")
                ],
            }
            modes = ["dev", "production"] if args.smoke_mode == "both" else [args.smoke_mode]
            for mode in modes:
                subprocess.run(
                    launcher_argv(
                        root,
                        state_root / mode,
                        "stop",
                        mode=mode,
                        python_executable=args.python_executable or default_python(root),
                        node_executable=args.node_executable or default_node(),
                        detector_manifest=None,
                        reconstructor_manifest=None,
                    ),
                    shell=False,
                    check=False,
                    timeout=40,
                )
        else:
            try:
                smoke = json.loads(output.with_name("smoke.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                smoke = {
                    "ok": False,
                    "worker_returncode": completed.returncode,
                    "problems": [_problem("SMOKE_FAILED", "启动检查没有写出结果。")],
                }
            if not isinstance(smoke, dict):
                smoke = {
                    "ok": False,
                    "problems": [_problem("SMOKE_FAILED", "启动检查结果无法读取。")],
                }
    report = build_report(
        root,
        python_executable=args.python_executable or default_python(root),
        node_executable=args.node_executable or default_node(),
        detector_manifest=_manifest_argument(
            root, args.detector_manifest, "AGEMORPH_DETECTOR_MANIFEST"
        ),
        reconstructor_manifest=_manifest_argument(
            root, args.reconstructor_manifest, "AGEMORPH_RECONSTRUCTOR_MANIFEST"
        ),
        smoke=smoke,
    )
    _write(output, report)
    sys.stdout.write(
        json.dumps(
            {
                "report": str(output),
                "conclusion": report["conclusion"],
                "exit": exit_code_for(report),
            },
            ensure_ascii=False,
        )
    )
    sys.stdout.write("\n")
    return exit_code_for(report)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReproCheckError as error:
        sys.stdout.write(
            json.dumps(
                {"code": error.code, "detail": error.detail, "l02_executed": False},
                ensure_ascii=False,
            )
        )
        sys.stdout.write("\n")
        raise SystemExit(error.exit_code) from None
