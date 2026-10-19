"""Synthetic-only tests for configuration, contracts, and image boundaries."""

import math
from dataclasses import FrozenInstanceError
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from agemorph3d.config import DEFAULT_ALLOWED_ORIGINS, Settings
from agemorph3d.errors import ApiError
from agemorph3d.images import decode_image
from agemorph3d.schemas import AgingRequest, Capabilities, Health, ModelStatus, Pose, Reconstruction

IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1]


def image_bytes(format: str = "PNG", size: tuple[int, int] = (12, 8), **options: object) -> bytes:
    with Image.new("RGB", size, "red") as image:
        output = BytesIO()
        image.save(output, format=format, **options)
        return output.getvalue()


@pytest.mark.parametrize(
    "format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_decodes_supported_formats_to_owned_rgb(format: str, mime: str) -> None:
    with decode_image(image_bytes(format), mime, Settings()) as result:
        assert result.mode == "RGB"
        assert result.size == (12, 8)
        assert result.getpixel((0, 0))[0] > 200


def test_accepts_mime_parameters_and_valid_frame() -> None:
    with decode_image(
        image_bytes("JPEG", (640, 360)), "image/jpeg; charset=binary", Settings(), frame=True
    ) as result:
        assert result.size == (640, 360)


@pytest.mark.parametrize(
    "data,mime,status",
    [
        (b"", "image/png", 400),
        (b"not an image", "image/png", 400),
        (image_bytes(), "image/jpeg", 415),
        (image_bytes(), "application/octet-stream", 415),
        (image_bytes("GIF"), "image/png", 415),
        (image_bytes()[:40], "image/png", 400),
    ],
)
def test_bad_images_are_explicit_errors(data: bytes, mime: str, status: int) -> None:
    with pytest.raises(ApiError) as caught:
        decode_image(data, mime, Settings())
    assert caught.value.status_code == status
    assert isinstance(caught.value.detail, str)


def test_byte_limit_is_checked_before_decode() -> None:
    with pytest.raises(ApiError) as caught:
        decode_image(b"broken but oversized", "image/png", Settings(max_image_bytes=5))
    assert caught.value.status_code == 413


def test_pixel_limit_and_exact_boundary() -> None:
    data = image_bytes(size=(12, 8))
    with decode_image(data, "image/png", Settings(max_image_pixels=96)) as result:
        assert result.size == (12, 8)
    with pytest.raises(ApiError) as caught:
        decode_image(data, "image/png", Settings(max_image_pixels=95))
    assert caught.value.status_code == 413


def test_pixel_limit_precedes_full_pixel_load(monkeypatch: pytest.MonkeyPatch) -> None:
    data = image_bytes(size=(12, 8))

    def unexpected_load(*args: object, **kwargs: object) -> None:
        raise AssertionError("Pixel loading must not run for an oversized image.")

    monkeypatch.setattr("PIL.PngImagePlugin.PngImageFile.load", unexpected_load)
    with pytest.raises(ApiError) as caught:
        decode_image(data, "image/png", Settings(max_image_pixels=95))
    assert caught.value.status_code == 413


@pytest.mark.parametrize(
    "mime,format,size,settings,status",
    [
        ("image/png", "PNG", (12, 8), Settings(), 415),
        ("image/jpeg", "PNG", (12, 8), Settings(), 415),
        ("image/jpeg", "JPEG", (641, 1), Settings(), 413),
        ("image/jpeg", "JPEG", (12, 8), Settings(max_frame_bytes=10), 413),
    ],
)
def test_frames_have_independent_limits(
    mime: str, format: str, size: tuple[int, int], settings: Settings, status: int
) -> None:
    with pytest.raises(ApiError) as caught:
        decode_image(image_bytes(format, size), mime, settings, frame=True)
    assert caught.value.status_code == status


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("WEBP", "image/webp")])
def test_animation_is_rejected(format: str, mime: str) -> None:
    output = BytesIO()
    with Image.new("RGB", (12, 8), "red") as first, Image.new("RGB", (12, 8), "blue") as second:
        first.save(
            output, format=format, save_all=True, append_images=[second], duration=100, loop=0
        )
    with pytest.raises(ApiError) as caught:
        decode_image(output.getvalue(), mime, Settings())
    assert caught.value.status_code == 400


def test_exif_orientation_is_applied_and_removed() -> None:
    exif = Image.Exif()
    exif[274] = 6
    with decode_image(image_bytes("JPEG", (12, 8), exif=exif), "image/jpeg", Settings()) as result:
        assert result.size == (8, 12)
        assert result.getexif().get(274) is None


@pytest.mark.parametrize("pillow_pixel_limit", [50, 20])
def test_pillow_bomb_warning_and_error_become_413(
    monkeypatch: pytest.MonkeyPatch, pillow_pixel_limit: int
) -> None:
    data = image_bytes(size=(10, 10))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", pillow_pixel_limit)
    with pytest.raises(ApiError) as caught:
        decode_image(data, "image/png", Settings())
    assert caught.value.status_code == 413


@pytest.mark.parametrize("age", [20, 45.5, 70])
def test_valid_ages(age: float) -> None:
    assert AgingRequest(mesh_id="subject-1_a", age=age).age == age


@pytest.mark.parametrize(
    "age", [True, False, "45", None, 19.9, 70.1, math.inf, -math.inf, math.nan]
)
def test_age_is_strict_finite_and_bounded(age: object) -> None:
    with pytest.raises(ValidationError):
        AgingRequest(mesh_id="subject", age=age)


@pytest.mark.parametrize(
    "mesh_id", ["", "../a", "a/b", "_a", "-a", "a" * 101, "中文", "a?b", "a\n"]
)
def test_mesh_ids_are_opaque_safe_identifiers(mesh_id: str) -> None:
    with pytest.raises(ValidationError):
        AgingRequest(mesh_id=mesh_id, age=45)


def test_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AgingRequest(mesh_id="a", age=45, source_age=30)


def test_pose_accepts_identity_and_real_rotation() -> None:
    angle = math.pi / 6
    c, s = math.cos(angle), math.sin(angle)
    assert Pose(R=IDENTITY, t=[0, 0, 0]).R == IDENTITY
    assert Pose(R=[c, -s, 0, s, c, 0, 0, 0, 1], t=[1, 2, 3]).t == [1, 2, 3]


@pytest.mark.parametrize(
    "rotation,translation",
    [
        (IDENTITY[:8], [0, 0, 0]),
        (IDENTITY, [0, 0]),
        ([2, 0, 0, 0, 1, 0, 0, 0, 1], [0, 0, 0]),
        ([1, 0, 0, 0, 1, 0, 0, 0, -1], [0, 0, 0]),
        ([1, 0, 0, 1, 0, 0, 0, 0, 1], [0, 0, 0]),
        ([math.nan] + IDENTITY[1:], [0, 0, 0]),
        (IDENTITY, [0, math.inf, 0]),
        ([True] + IDENTITY[1:], [0, 0, 0]),
        (["1"] + IDENTITY[1:], [0, 0, 0]),
        ([1e308] + IDENTITY[1:], [0, 0, 0]),
    ],
)
def test_invalid_pose_rejected(rotation: list[object], translation: list[object]) -> None:
    with pytest.raises(ValidationError):
        Pose(R=rotation, t=translation)


def reconstruction(**changes: object) -> Reconstruction:
    values = {
        "mesh_id": "subject",
        "shape": [0],
        "expr": [0],
        "pose": {"R": IDENTITY, "t": [0, 0, 0]},
    }
    values.update(changes)
    return Reconstruction(**values)


@pytest.mark.parametrize(
    "coefficients",
    [[], [0] * 301, [math.nan], [math.inf], [1_000_001], [-1_000_001], [True], ["0"]],
)
@pytest.mark.parametrize("field", ["shape", "expr"])
def test_coefficients_are_bounded_finite_arrays(field: str, coefficients: list[object]) -> None:
    with pytest.raises(ValidationError):
        reconstruction(**{field: coefficients})


def test_valid_reconstruction_and_relative_texture() -> None:
    result = reconstruction(
        shape=[-1_000_000, 1_000_000], texture_url="/api/assets/subject/texture.png"
    )
    assert result.texture_url == "/api/assets/subject/texture.png"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api/assets/a.png",
        "//localhost/api/assets/a.png",
        "/other/a.png",
        "/api/assets/../a.png",
        "/api/assets/%2e%2e/a.png",
        "/api/assets/a.png?token=x",
        "/api/assets/a.png#x",
        "/api/assets/a\\b.png",
        "/api/assets//a.png",
        "/api/assets/",
    ],
)
def test_texture_paths_cannot_escape_asset_routes(url: str) -> None:
    with pytest.raises(ValidationError):
        reconstruction(texture_url=url)


def test_health_is_explicitly_unready_without_capabilities() -> None:
    health = Health(
        models={"detector": ModelStatus(state="missing", detail="No configured weights.")},
        device="cpu",
        version="0.1.0",
    )
    assert health.api_version == "1.1"
    assert health.capabilities == Capabilities()
    assert not any(health.capabilities.model_dump().values())
    assert health.models["detector"].provider is None
    with pytest.raises(ValidationError):
        ModelStatus(state="available", detail="Not a protocol state.")


@pytest.mark.parametrize("value", ["false", "true", 0, 1])
def test_capabilities_require_real_booleans(value: object) -> None:
    with pytest.raises(ValidationError):
        Capabilities(reconstruction=value)


def test_default_settings_are_frozen() -> None:
    settings = Settings()
    assert settings.allowed_origins == DEFAULT_ALLOWED_ORIGINS
    assert settings.max_image_bytes == 10 * 1024**2
    assert settings.max_image_pixels == 16_000_000
    assert settings.max_frame_bytes == 2 * 1024**2
    assert settings.max_frame_side == 640
    assert settings.max_json_bytes == 128 * 1024
    with pytest.raises(FrozenInstanceError):
        settings.max_image_bytes = 1


def test_origins_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGEMORPH_ALLOWED_ORIGINS", raising=False)
    assert Settings.from_env().allowed_origins == DEFAULT_ALLOWED_ORIGINS
    monkeypatch.setenv("AGEMORPH_ALLOWED_ORIGINS", "http://localhost:5173, https://[::1]:8443")
    assert Settings.from_env().allowed_origins == ("http://localhost:5173", "https://[::1]:8443")
    monkeypatch.setenv("AGEMORPH_ALLOWED_ORIGINS", "")
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "null",
        "file://localhost",
        "http://example.com",
        "http://127.0.0.1.evil.test",
        "http://localhost/",
        "http://localhost/path",
        "http://user@localhost",
        "http://user:password@localhost",
        "http://localhost?",
        "http://localhost#",
        "http://localhost?x=1",
        "http://localhost#fragment",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:",
        "http://localhost\n",
        " http://localhost",
        "http://localhost\\evil.test",
        "http://[::2]:5173",
        "http://[::1]example.com",
        "http://[::1]:5173example.com",
    ],
)
def test_origins_are_local_bare_http_origins(origin: str) -> None:
    with pytest.raises(ValueError):
        Settings(allowed_origins=(origin,))


@pytest.mark.parametrize(
    "name",
    ["max_image_bytes", "max_image_pixels", "max_frame_bytes", "max_frame_side", "max_json_bytes"],
)
@pytest.mark.parametrize("value", [0, -1, True, "10", 1.5])
def test_integer_limits_are_positive_and_strict(name: str, value: object) -> None:
    with pytest.raises(ValueError):
        Settings(**{name: value})


@pytest.mark.parametrize("name", ["http_timeout_seconds", "frame_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, "10", math.inf, math.nan])
def test_timeouts_are_positive_finite_numbers(name: str, value: object) -> None:
    with pytest.raises(ValueError):
        Settings(**{name: value})


def test_origins_cannot_be_empty_mutable_or_duplicates() -> None:
    for origins in ((), ["http://localhost"], ("http://localhost", "http://LOCALHOST")):
        with pytest.raises(ValueError):
            Settings(allowed_origins=origins)
