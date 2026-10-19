"""Small, explicit configuration surface for the local API."""

import math
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
)


def _local_origin(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Allowed origins must be nonempty HTTP(S) loopback origins.")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("Allowed origins cannot contain whitespace or control characters.")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ValueError("Invalid allowed origin.") from error
    if (
        parts.scheme not in {"http", "https"}
        or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parts.username is not None
        or parts.password is not None
        or parts.path
        or parts.query
        or parts.fragment
        or "?" in value
        or "#" in value
        or parts.netloc.endswith(":")
        or not re.fullmatch(
            r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", parts.netloc, re.I
        )
        or (port is not None and port < 1)
    ):
        raise ValueError(
            "Allowed origins must be HTTP(S) loopback origins without paths or credentials."
        )
    host = "[::1]" if parts.hostname == "::1" else parts.hostname
    return f"{parts.scheme}://{host}" + (f":{port}" if port is not None else "")


@dataclass(frozen=True)
class Settings:
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    max_image_bytes: int = 10 * 1024**2
    max_image_pixels: int = 16_000_000
    max_frame_bytes: int = 2 * 1024**2
    max_frame_side: int = 640
    max_json_bytes: int = 128 * 1024
    http_timeout_seconds: float = 25
    frame_timeout_seconds: float = 6

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_origins, tuple) or not self.allowed_origins:
            raise ValueError("allowed_origins must be a nonempty tuple.")
        origins = tuple(_local_origin(origin) for origin in self.allowed_origins)
        if len(set(origins)) != len(origins):
            raise ValueError("Allowed origins must be unique.")
        object.__setattr__(self, "allowed_origins", origins)
        for name in (
            "max_image_bytes",
            "max_image_pixels",
            "max_frame_bytes",
            "max_frame_side",
            "max_json_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        for name in ("http_timeout_seconds", "frame_timeout_seconds"):
            value = getattr(self, name)
            if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number.")

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.environ.get("AGEMORPH_ALLOWED_ORIGINS")
        if origins is None:
            return cls()
        return cls(allowed_origins=tuple(value.strip() for value in origins.split(",")))
