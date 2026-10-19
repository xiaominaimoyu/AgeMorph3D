"""Bounded in-memory decoding for photos and realtime frames."""

import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .errors import ApiError

_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def decode_image(
    data: bytes,
    content_type: str,
    settings: Settings,
    *,
    frame: bool = False,
) -> Image.Image:
    """Return an owned RGB image; the caller closes it after inference."""
    if not isinstance(data, bytes) or not data:
        raise ApiError(400, "BAD_INPUT", "图片内容不能为空。")
    byte_limit = settings.max_frame_bytes if frame else settings.max_image_bytes
    if len(data) > byte_limit:
        raise ApiError(413, "INPUT_TOO_LARGE", "图片文件大小超过限制。")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in _FORMATS or (frame and media_type != "image/jpeg"):
        raise ApiError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "实时帧仅支持 JPEG。" if frame else "仅支持 JPEG、PNG 或 WebP 图片。",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in _FORMATS.values() or (frame and source.format != "JPEG"):
                    raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "不支持此图片格式。")
                if source.format != _FORMATS[media_type]:
                    raise ApiError(
                        415, "UNSUPPORTED_MEDIA_TYPE", "图片实际格式与声明的媒体类型不一致。"
                    )
                width, height = source.size
                if width <= 0 or height <= 0:
                    raise ApiError(400, "BAD_INPUT", "图片尺寸必须为正数。")
                if width * height > settings.max_image_pixels:
                    raise ApiError(413, "INPUT_TOO_LARGE", "图片像素总量超过限制。")
                if frame and max(width, height) > settings.max_frame_side:
                    raise ApiError(413, "INPUT_TOO_LARGE", "实时帧边长超过限制。")
                if getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                    raise ApiError(400, "BAD_INPUT", "不支持动画图片。")
                source.verify()
            with Image.open(BytesIO(data)) as source:
                source.load()
                with ImageOps.exif_transpose(source) as oriented:
                    return oriented.convert("RGB")
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ApiError(413, "INPUT_TOO_LARGE", "图片像素总量超过限制。") from error
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as error:
        raise ApiError(400, "BAD_INPUT", "图片已损坏或无法解码。") from error
