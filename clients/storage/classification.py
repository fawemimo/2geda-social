from __future__ import annotations

import os
import uuid
from io import BytesIO
from typing import Any

from PIL import Image

from utils.enum import MediaType

IMAGE_MAX_SIZE = 10 * 1024 * 1024
VIDEO_MAX_SIZE = 500 * 1024 * 1024
AUDIO_MAX_SIZE = 50 * 1024 * 1024
DOCUMENT_MAX_SIZE = 20 * 1024 * 1024

EXTENSION_MAP: dict[str, dict[str, Any]] = {
    ".jpg": {"media_type": MediaType.IMAGE.value, "mime": "image/jpeg"},
    ".jpeg": {"media_type": MediaType.IMAGE.value, "mime": "image/jpeg"},
    ".png": {"media_type": MediaType.IMAGE.value, "mime": "image/png"},
    ".gif": {"media_type": MediaType.IMAGE.value, "mime": "image/gif"},
    ".webp": {"media_type": MediaType.IMAGE.value, "mime": "image/webp"},
    ".bmp": {"media_type": MediaType.IMAGE.value, "mime": "image/bmp"},
    ".svg": {"media_type": MediaType.IMAGE.value, "mime": "image/svg+xml"},
    ".heic": {"media_type": MediaType.IMAGE.value, "mime": "image/heic"},
    ".heif": {"media_type": MediaType.IMAGE.value, "mime": "image/heif"},
    ".tiff": {"media_type": MediaType.IMAGE.value, "mime": "image/tiff"},
    ".tif": {"media_type": MediaType.IMAGE.value, "mime": "image/tiff"},
    ".ico": {"media_type": MediaType.IMAGE.value, "mime": "image/x-icon"},
    ".mp4": {"media_type": MediaType.VIDEO.value, "mime": "video/mp4"},
    ".mov": {"media_type": MediaType.VIDEO.value, "mime": "video/quicktime"},
    ".avi": {"media_type": MediaType.VIDEO.value, "mime": "video/x-msvideo"},
    ".mkv": {"media_type": MediaType.VIDEO.value, "mime": "video/x-matroska"},
    ".webm": {"media_type": MediaType.VIDEO.value, "mime": "video/webm"},
    ".wmv": {"media_type": MediaType.VIDEO.value, "mime": "video/x-ms-wmv"},
    ".flv": {"media_type": MediaType.VIDEO.value, "mime": "video/x-flv"},
    ".m4v": {"media_type": MediaType.VIDEO.value, "mime": "video/x-m4v"},
    ".3gp": {"media_type": MediaType.VIDEO.value, "mime": "video/3gpp"},
    ".mp3": {"media_type": MediaType.AUDIO.value, "mime": "audio/mpeg"},
    ".wav": {"media_type": MediaType.AUDIO.value, "mime": "audio/wav"},
    ".ogg": {"media_type": MediaType.AUDIO.value, "mime": "audio/ogg"},
    ".aac": {"media_type": MediaType.AUDIO.value, "mime": "audio/aac"},
    ".flac": {"media_type": MediaType.AUDIO.value, "mime": "audio/flac"},
    ".wma": {"media_type": MediaType.AUDIO.value, "mime": "audio/x-ms-wma"},
    ".m4a": {"media_type": MediaType.AUDIO.value, "mime": "audio/mp4"},
    ".opus": {"media_type": MediaType.AUDIO.value, "mime": "audio/opus"},
    ".aiff": {"media_type": MediaType.AUDIO.value, "mime": "audio/aiff"},
    ".pdf": {"media_type": MediaType.DOCUMENT.value, "mime": "application/pdf"},
    ".doc": {"media_type": MediaType.DOCUMENT.value, "mime": "application/msword"},
    ".docx": {"media_type": MediaType.DOCUMENT.value, "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xls": {"media_type": MediaType.DOCUMENT.value, "mime": "application/vnd.ms-excel"},
    ".xlsx": {"media_type": MediaType.DOCUMENT.value, "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".ppt": {"media_type": MediaType.DOCUMENT.value, "mime": "application/vnd.ms-powerpoint"},
    ".pptx": {"media_type": MediaType.DOCUMENT.value, "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".txt": {"media_type": MediaType.DOCUMENT.value, "mime": "text/plain"},
    ".csv": {"media_type": MediaType.DOCUMENT.value, "mime": "text/csv"},
    ".rtf": {"media_type": MediaType.DOCUMENT.value, "mime": "application/rtf"},
    ".epub": {"media_type": MediaType.DOCUMENT.value, "mime": "application/epub+zip"},
}

MEDIA_TYPE_FOLDERS: dict[str, str] = {
    MediaType.IMAGE.value: "images",
    MediaType.VIDEO.value: "videos",
    MediaType.AUDIO.value: "audio",
    MediaType.DOCUMENT.value: "documents",
    MediaType.GIF.value: "images",
}

MEDIA_TYPE_SIZE_LIMITS: dict[str, int] = {
    MediaType.IMAGE.value: IMAGE_MAX_SIZE,
    MediaType.VIDEO.value: VIDEO_MAX_SIZE,
    MediaType.AUDIO.value: AUDIO_MAX_SIZE,
    MediaType.DOCUMENT.value: DOCUMENT_MAX_SIZE,
    MediaType.GIF.value: IMAGE_MAX_SIZE,
}


def classify(file_name: str) -> dict[str, Any]:
    ext = os.path.splitext(file_name)[1].lower()
    info = EXTENSION_MAP.get(ext)
    if not info:
        raise ValueError(f"Unsupported file format: {ext}")
    return info


def build_key(media_type: str, ext: str) -> str:
    folder = MEDIA_TYPE_FOLDERS.get(media_type, "misc")
    return f"{folder}/{uuid.uuid4()}{ext}"


def validate_file_size(file, media_type: str) -> None:
    limit = MEDIA_TYPE_SIZE_LIMITS.get(media_type)
    if limit and file.size > limit:
        raise ValueError(
            f"File exceeds {limit // (1024 * 1024)} MB limit for {media_type} files"
        )


def normalize_image(file, ext: str) -> tuple[BytesIO, str, str]:
    with Image.open(file) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buffer = BytesIO()
        save_format = "JPEG"
        save_ext = ".jpg"
        if ext == ".png":
            img.save(buffer, format="PNG")
            save_format = "PNG"
            save_ext = ".png"
        else:
            img.save(buffer, format="JPEG", quality=92)
        buffer.seek(0)
    return buffer, save_format.lower(), save_ext
