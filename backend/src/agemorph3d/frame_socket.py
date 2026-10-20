"""One outstanding frame, bounded replies and prompt disconnect observation."""

import asyncio
import json
from time import time_ns

from fastapi import WebSocket, WebSocketDisconnect

from .config import Settings
from .errors import ApiError

_RECOVERABLE = {"NO_FACE", "MULTI_FACE", "BUSY"}


def _number(value: float) -> float:
    # Significant digits preserve small nonzero box dimensions; rotation error <1e-7.
    return float(format(value, ".8g"))


def face_message(result: dict, seq: int) -> dict:
    """No coefficients, images or asset identifiers belong in a frame reply."""
    return {
        "type": "face_state",
        "seq": seq,
        "ts": time_ns() // 1_000_000,
        "bbox": [_number(value) for value in result["bbox"]],
        "landmarks": [[_number(value) for value in point] for point in result["landmarks"]],
        "pose": {
            "R": [_number(value) for value in result["pose"]["R"]],
            "t": [_number(value) for value in result["pose"]["t"]],
        },
        "conf": _number(result["conf"]),
    }


def error_message(seq: int, error: ApiError) -> dict:
    return {"type": "error", "seq": seq, "code": error.code, "msg": error.detail}


async def _send(socket: WebSocket, payload: dict, *, deadline: float | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > 1024:
        raise ValueError("Realtime reply exceeds the protocol limit.")
    remaining = 1 if deadline is None else min(1, deadline - asyncio.get_running_loop().time())
    if remaining <= 0:
        raise ApiError(504, "TIMEOUT", "实时处理超时，请稍后重新连接。")

    async def write() -> None:
        # wait_for schedules this coroutine: check again after event-loop dispatch.
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            raise ApiError(504, "TIMEOUT", "实时处理超时，请稍后重新连接。")
        await socket.send_text(text)

    # Successful sends share the frame deadline. A send timeout has unknown delivery
    # status, so its caller must never send a second terminal message for that frame.
    await asyncio.wait_for(write(), timeout=remaining)


async def _close(socket: WebSocket, code: int) -> None:
    await asyncio.wait_for(socket.close(code=code), timeout=1)


async def handle_frames(socket: WebSocket, settings: Settings) -> None:
    await socket.accept()
    receiver = None
    worker = None
    seq = 0
    active_seq = 0
    deadline = 0.0
    try:
        await _send(socket, {"type": "status", "device": "cpu"})
        receiver = asyncio.create_task(socket.receive())
        while True:
            if worker is not None:
                await asyncio.wait({receiver, worker}, return_when=asyncio.FIRST_COMPLETED)
            else:
                await asyncio.wait({receiver})

            # A disconnect or an unsolicited next input wins over a late CPU result.
            if receiver.done():
                message = receiver.result()
                if message["type"] == "websocket.disconnect":
                    return
                seq += 1
                if worker is not None:
                    error = ApiError(429, "BUSY", "请等待当前帧回复后再发送下一帧。")
                    # Both consumed inputs get one terminal error; no queued work.
                    worker.cancel()
                    await _send(socket, error_message(active_seq, error))
                    await _send(socket, error_message(seq, error))
                    await _close(socket, 1013)
                    return
                data = message.get("bytes")
                if data is None:
                    await _send(
                        socket,
                        error_message(
                            seq, ApiError(400, "BAD_INPUT", "实时帧必须为 JPEG 二进制数据。")
                        ),
                    )
                    await _close(socket, 1003)
                    return
                active_seq = seq
                deadline = asyncio.get_running_loop().time() + settings.frame_timeout_seconds
                worker = asyncio.create_task(
                    socket.app.state.runtime.process_frame(data, settings.frame_timeout_seconds)
                )
                receiver = asyncio.create_task(socket.receive())
                continue

            error = None
            try:
                result = worker.result()
                if asyncio.get_running_loop().time() >= deadline:
                    raise ApiError(504, "TIMEOUT", "实时处理超时，请稍后重新连接。")
                payload = face_message(result, active_seq)
                # Validate serialization before entering the send path.
                encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode("utf-8")) > 1024:
                    raise ValueError("Invalid realtime result.")
            except ApiError as exc:
                error = exc
                payload = error_message(active_seq, error)
            except Exception:
                error = ApiError(500, "INTERNAL_ERROR", "实时处理失败，请检查模型后重新连接。")
                payload = error_message(active_seq, error)
            worker = None
            try:
                await _send(socket, payload, deadline=deadline if error is None else None)
            except ApiError as exc:
                error = exc  # Expired before starting the actual send: safe to reply once.
                await _send(socket, error_message(active_seq, error))
            if error is not None and error.code not in _RECOVERABLE:
                await _close(
                    socket,
                    1013
                    if error.status_code in {429, 503, 504}
                    else 1011
                    if error.status_code >= 500
                    else 1003,
                )
                return
    except (WebSocketDisconnect, OSError, RuntimeError, TimeoutError):
        # A disappeared peer has no channel on which to acknowledge a frame.
        return
    finally:
        tasks = [task for task in (receiver, worker) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
