"""Bounded local research SAM subprocess; this module never imports torch.

Cancellation ends a caller's wait, not native inference. The single flight stays
owned until its framed reply arrives or the owned subprocess has actually exited.
"""

from __future__ import annotations

import asyncio
import base64
import errno
import hashlib
import json
import math
import os
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_FRAME_BYTES = 8 * 1024**2
MAX_INPUT_BYTES = 1024**2
MAX_STDERR_BYTES = 64 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_DEVICE_LOCK_PATH = _WORKSPACE_ROOT / "output/cache/sam-cuda-0.lock"


class SamWorkerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SamGeneration:
    png: bytes
    sha256: str
    input_sha256: str
    target_age: int
    pid: int
    load_count: int
    seconds: float
    peak_vram_bytes: int
    provenance: dict[str, Any]


class _DeviceLease:
    """A placeholder-only OS lock shared by clients/processes in this workspace."""

    def __init__(self) -> None:
        path = _DEVICE_LOCK_PATH.resolve()
        if not path.is_relative_to(_WORKSPACE_ROOT.resolve()):
            raise SamWorkerError("WORKER_FAILED", "SAM device lock escaped the workspace.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("a+b")
        try:
            if path.stat().st_size == 0:
                self._stream.write(b"\0")
                self._stream.flush()
            self._stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._stream.close()
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise SamWorkerError(
                    "BUSY", "This workspace already owns a CUDA SAM worker."
                ) from error
            raise

    def close(self) -> None:
        if self._stream.closed:
            return
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()


class _WindowsProcessHandle:
    """Wait/terminate the actual venv child, beyond its Windows redirector PID."""

    def __init__(self, pid: int) -> None:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self._kernel = kernel
        self._handle = kernel.OpenProcess(0x00100000 | 0x0001 | 0x1000, False, pid)
        if not self._handle:
            raise SamWorkerError("WORKER_PROTOCOL", "Cannot bind the owned Windows worker process.")

    def terminate(self) -> None:
        import ctypes

        if self._handle and self._kernel.WaitForSingleObject(self._handle, 0) == 0x102:
            # An already exiting process may race this call with ACCESS_DENIED.
            if not self._kernel.TerminateProcess(self._handle, 1) and ctypes.get_last_error() != 5:
                raise SamWorkerError("WORKER_FAILED", "Cannot terminate the owned SAM process.")

    def wait(self) -> int:
        import ctypes
        from ctypes import wintypes

        if self._kernel.WaitForSingleObject(self._handle, 0xFFFFFFFF) != 0:
            raise SamWorkerError("WORKER_FAILED", "Cannot wait for the owned SAM process.")
        code = wintypes.DWORD()
        if not self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            raise SamWorkerError("WORKER_FAILED", "Cannot read the SAM process exit status.")
        return code.value

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def _frame(value: dict) -> bytes:
    body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if not 2 <= len(body) <= MAX_FRAME_BYTES:
        raise SamWorkerError("WORKER_PROTOCOL", "SAM frame exceeds the size budget.")
    return struct.pack(">I", len(body)) + body


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


async def _read_frame(reader: asyncio.StreamReader) -> dict:
    length = struct.unpack(">I", await reader.readexactly(4))[0]
    if not 2 <= length <= MAX_FRAME_BYTES:
        raise SamWorkerError("WORKER_PROTOCOL", "Invalid SAM frame length.")
    result = json.loads(await reader.readexactly(length), parse_constant=_reject_constant)
    if not isinstance(result, dict):
        raise SamWorkerError("WORKER_PROTOCOL", "SAM frame must contain an object.")
    return result


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 33 or data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise SamWorkerError("INVALID_REQUEST", "An aligned PNG image is required.")
    return struct.unpack(">II", data[16:24])


def _budget(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError("Worker time budgets must be finite and positive.")
    return value


class SamWorkerClient:
    """One explicitly configured, owned worker; research loading never means ready."""

    def __init__(
        self,
        *,
        python_executable: str | Path,
        worker_script: str | Path,
        manifest_path: str | Path,
        sam_root: str | Path,
        device: str = "cuda",
        research_allow_unresolved: bool = False,
        startup_timeout_s: float = 120,
        request_timeout_s: float = 30,
        shutdown_timeout_s: float = 10,
    ) -> None:
        if device not in {"cuda", "cpu"}:
            raise ValueError("SAM device must be cuda or cpu.")
        self._command = [
            str(Path(python_executable).resolve()),
            "-B",
            str(Path(worker_script).resolve()),
            "--manifest",
            str(Path(manifest_path).resolve()),
            "--sam-root",
            str(Path(sam_root).resolve()),
            "--device",
            device,
        ]
        if research_allow_unresolved:
            self._command.append("--research-allow-unresolved")
        self._startup_timeout = _budget(startup_timeout_s)
        self._request_timeout = _budget(request_timeout_s)
        self._shutdown_timeout = _budget(shutdown_timeout_s)
        self._process: asyncio.subprocess.Process | None = None
        self._worker_pid: int | None = None
        self._worker_exitcode: int | None = None
        self._worker_handle: _WindowsProcessHandle | None = None
        self._identity_bound = asyncio.Event()
        self._uses_cuda = device == "cuda"
        self._lease: _DeviceLease | None = None
        self._exit_task: asyncio.Task | None = None
        self._startup: asyncio.Task | None = None
        self._pending: asyncio.Task | None = None
        self._shutdown: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr = bytearray()
        self._identity: dict = {}
        self._counter = 0
        self._closed = False
        self._broken = False
        self._forced = False

    @property
    def busy(self) -> bool:
        return self._pending is not None and not self._pending.done()

    def snapshot(self) -> dict:
        process = self._process
        return {
            **self._identity,
            "research_only": True,
            "service_ready": False,
            "busy": self.busy,
            "closed": self._closed,
            "broken": self._broken,
            "pid": self._worker_pid,
            "launcher_pid": process.pid if process else None,
            "returncode": process.returncode if process else None,
            "worker_exitcode": self._worker_exitcode,
            "forced_termination": self._forced,
            "stderr_tail": self._stderr.decode("utf-8", errors="replace"),
        }

    @staticmethod
    def _consume(task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()

    async def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while chunk := await self._process.stderr.read(4096):
            self._stderr.extend(chunk)
            del self._stderr[:-MAX_STDERR_BYTES]

    async def _terminate(self) -> None:
        process = self._process
        if process is None:
            return
        actual_live = self._worker_handle is not None and self._worker_exitcode is None
        if process.returncode is None or actual_live:
            self._forced = True
        if actual_live:
            self._worker_handle.terminate()
        elif process.returncode is None and os.name == "nt":
            # Before hello, the Windows venv redirector may already own a child.
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await killer.wait()
        elif process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        if self._exit_task is not None:
            # The exit watcher owns the sole handle wait and releases the lease.
            await asyncio.shield(self._exit_task)

    async def _watch_exit(self) -> None:
        assert self._process is not None
        try:
            await self._identity_bound.wait()
            if self._worker_handle is not None:
                self._worker_exitcode = await asyncio.to_thread(self._worker_handle.wait)
            await self._process.wait()
        finally:
            if self._worker_handle is not None:
                self._worker_handle.close()
                self._worker_handle = None
            if self._lease is not None:
                self._lease.close()
                self._lease = None

    def _validate_identity(self, message: dict) -> None:
        process = self._process
        if (
            process is None
            or type(message.get("pid")) is not int
            or message.get("pid") != self._worker_pid
            or type(message.get("load_count")) is not int
            or message.get("load_count") != 1
            or message.get("research_only") is not True
            or message.get("service_ready") is not False
        ):
            raise SamWorkerError("WORKER_PROTOCOL", "SAM worker identity is inconsistent.")

    async def _start(self) -> dict:
        try:
            if self._closed:
                raise SamWorkerError("WORKER_CLOSED", "SAM worker closed before startup.")
            if self._uses_cuda:
                self._lease = _DeviceLease()
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                limit=64 * 1024,
            )
            self._exit_task = asyncio.create_task(self._watch_exit())
            self._exit_task.add_done_callback(self._consume)
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            assert self._process.stdout is not None
            hello = await _read_frame(self._process.stdout)
            pid = hello.get("pid")
            if (
                hello.get("type") != "hello"
                or type(pid) is not int
                or pid <= 0
                or not (
                    pid == self._process.pid
                    or (os.name == "nt" and hello.get("parent_pid") == self._process.pid)
                )
            ):
                raise SamWorkerError("WORKER_PROTOCOL", "SAM hello is not from the owned process.")
            self._worker_pid = pid
            if os.name == "nt":
                self._worker_handle = _WindowsProcessHandle(pid)
            self._identity_bound.set()
            message = await _read_frame(self._process.stdout)
            if message.get("type") == "startup_error":
                raise SamWorkerError(
                    str(message.get("code", "MODEL_NOT_READY")),
                    "SAM research worker failed to load or self-test.",
                )
            self._validate_identity(message)
            if (
                message.get("type") != "ready"
                or message.get("protocol_version") != 1
                or message.get("state") != "research_loaded"
                or message.get("selftest", {}).get("passed") is not True
            ):
                raise SamWorkerError("WORKER_PROTOCOL", "Invalid SAM startup/self-test reply.")
            self._identity = message
            return dict(message)
        except Exception as error:
            self._broken = True
            self._identity_bound.set()
            await self._terminate()
            if self._exit_task is not None:
                await self._exit_task
            elif self._lease is not None:
                self._lease.close()
                self._lease = None
            if isinstance(error, SamWorkerError):
                raise
            raise SamWorkerError("WORKER_FAILED", "SAM subprocess startup failed.") from error

    async def start(self) -> dict:
        if self._closed or self._broken:
            raise SamWorkerError("WORKER_CLOSED", "SAM worker is closed or unavailable.")
        if self._startup is None:
            self._startup = asyncio.create_task(self._start())
            self._startup.add_done_callback(self._consume)
        try:
            return await asyncio.wait_for(asyncio.shield(self._startup), self._startup_timeout)
        except TimeoutError as error:
            await self.close()
            raise SamWorkerError("TIMEOUT", "SAM worker startup timed out.") from error

    async def _exchange(self, request: dict) -> dict:
        process = self._process
        assert process is not None and process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(_frame(request))
            await process.stdin.drain()
            response = await _read_frame(process.stdout)
            if response.get("id") != request["id"]:
                raise SamWorkerError("WORKER_PROTOCOL", "SAM response request ID changed.")
            self._validate_identity(response)
            if response.get("type") == "error":
                if response.get("fatal") is True:
                    self._broken = True
                    await self._terminate()
                raise SamWorkerError(
                    str(response.get("code", "WORKER_FAILED")), "SAM request failed."
                )
            if response.get("type") != request["type"] + "_result":
                raise SamWorkerError("WORKER_PROTOCOL", "Unexpected SAM response type.")
            return response
        except SamWorkerError as error:
            if error.code == "WORKER_PROTOCOL":
                self._broken = True
                await self._terminate()
            raise
        except Exception as error:
            self._broken = True
            await self._terminate()
            raise SamWorkerError("WORKER_FAILED", "SAM subprocess communication failed.") from error

    async def _request(self, kind: str, values: dict, timeout_s: float | None) -> dict:
        if self._closed or self._broken:
            raise SamWorkerError("WORKER_CLOSED", "SAM worker is closed or unavailable.")
        if self.busy:
            raise SamWorkerError("BUSY", "SAM is still processing its previous request.")
        timeout = self._request_timeout if timeout_s is None else _budget(timeout_s)
        self._counter += 1
        request = {"type": kind, "id": str(self._counter), **values}
        self._pending = task = asyncio.create_task(self._exchange(request))
        task.add_done_callback(self._consume)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout)
        except TimeoutError as error:
            raise SamWorkerError(
                "TIMEOUT", "SAM request timed out; native work still owns the slot."
            ) from error

    async def health(self, *, timeout_s: float | None = None) -> dict:
        await self.start()
        return await self._request("health", {}, timeout_s)

    async def wait_idle(self) -> None:
        """Drain underlying work even after a request waiter timed out/cancelled.

        A coordinator retaining source/cache leases must await this in its
        processor's finally block before releasing those leases or its own slot.
        Cancelling this waiter cannot cancel startup, native work or GPU cleanup.
        """
        tasks = [self._startup, self._pending]
        draining = asyncio.gather(
            *(asyncio.shield(task) for task in tasks if task is not None), return_exceptions=True
        )
        cancelled = False
        while not draining.done():
            try:
                await asyncio.shield(draining)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def generate(
        self, aligned_png: bytes, target_age: int, *, timeout_s: float | None = None
    ) -> SamGeneration:
        if type(target_age) is not int or not 20 <= target_age <= 70:
            raise SamWorkerError("INVALID_REQUEST", "SAM requires an integer age from 20 to 70.")
        if (
            not isinstance(aligned_png, bytes)
            or not 0 < len(aligned_png) <= MAX_INPUT_BYTES
            or _png_dimensions(aligned_png) != (256, 256)
        ):
            raise SamWorkerError("INVALID_REQUEST", "SAM requires a bounded 256x256 aligned PNG.")
        await self.start()
        input_hash = hashlib.sha256(aligned_png).hexdigest()
        reply = await self._request(
            "generate",
            {
                "png_b64": base64.b64encode(aligned_png).decode("ascii"),
                "input_sha256": input_hash,
                "target_age": target_age,
            },
            timeout_s,
        )
        try:
            image = base64.b64decode(reply["png_b64"], validate=True)
            digest = hashlib.sha256(image).hexdigest()
            if (
                not 0 < len(image) <= 4 * 1024**2
                or _png_dimensions(image) != (1024, 1024)
                or reply["sha256"] != digest
                or reply["input_sha256"] != input_hash
                or type(reply["target_age"]) is not int
                or reply["target_age"] != target_age
                or type(reply["seconds"]) not in {int, float}
                or not math.isfinite(reply["seconds"])
                or reply["seconds"] < 0
                or type(reply["peak_vram_bytes"]) is not int
                or reply["peak_vram_bytes"] < 0
            ):
                raise ValueError("Invalid SAM output evidence.")
        except (KeyError, TypeError, ValueError, OverflowError, SamWorkerError) as error:
            self._broken = True
            await self._terminate()
            raise SamWorkerError(
                "WORKER_PROTOCOL", "SAM output failed integrity checks."
            ) from error
        return SamGeneration(
            image,
            digest,
            input_hash,
            target_age,
            reply["pid"],
            reply["load_count"],
            reply["seconds"],
            reply["peak_vram_bytes"],
            dict(self._identity),
        )

    async def _close(self) -> None:
        try:
            async with asyncio.timeout(self._shutdown_timeout):
                if self._startup is not None:
                    await asyncio.gather(asyncio.shield(self._startup), return_exceptions=True)
                if self._pending is not None:
                    await asyncio.gather(asyncio.shield(self._pending), return_exceptions=True)
                process = self._process
                if process is not None and process.returncode is None:
                    if not self._broken:
                        await self._exchange({"type": "shutdown", "id": "shutdown"})
                    assert process.stdin is not None
                    process.stdin.close()
                    await process.wait()
        except (TimeoutError, SamWorkerError):
            await self._terminate()
        finally:
            await self._terminate()
            tasks = [self._startup, self._pending, self._stderr_task, self._exit_task]
            await asyncio.gather(
                *(task for task in tasks if task is not None), return_exceptions=True
            )

    async def close(self) -> dict:
        if self._shutdown is None:
            self._closed = True
            self._shutdown = asyncio.create_task(self._close())
            self._shutdown.add_done_callback(self._consume)
        await asyncio.shield(self._shutdown)
        return self.snapshot()
