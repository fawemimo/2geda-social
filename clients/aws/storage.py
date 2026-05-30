from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from io import BytesIO
from typing import Any

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from PIL import Image

from utils.enum import MediaType

logger = logging.getLogger(__name__)


AWS_ACCESS_KEY_ID = getattr(settings, "AWS_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY_ID"))
AWS_SECRET_ACCESS_KEY = getattr(settings, "AWS_SECRET_ACCESS_KEY", os.getenv("AWS_SECRET_ACCESS_KEY"))
AWS_STORAGE_BUCKET_NAME = getattr(settings, "AWS_STORAGE_BUCKET_NAME", os.getenv("AWS_STORAGE_BUCKET_NAME"))
AWS_S3_REGION_NAME = getattr(settings, "AWS_S3_REGION_NAME", os.getenv("AWS_S3_REGION_NAME", "us-north-1"))
AWS_S3_CUSTOM_DOMAIN = getattr(
    settings, "AWS_S3_CUSTOM_DOMAIN",
    f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com",
)

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


def _get_client() -> Any:
    return boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_S3_REGION_NAME,
    )


def _ensure_credentials() -> None:
    if not all((AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME)):
        raise ValueError("AWS credentials or bucket name missing")


def _classify(file_name: str) -> dict[str, Any]:
    ext = os.path.splitext(file_name)[1].lower()
    info = EXTENSION_MAP.get(ext)
    if not info:
        raise ValueError(f"Unsupported file format: {ext}")
    return info


def _get_path(media_type: str, ext: str) -> str:
    folder = MEDIA_TYPE_FOLDERS.get(media_type, "misc")
    return f"{folder}/{uuid.uuid4()}{ext}"


def _normalize_image(file, ext: str) -> tuple[BytesIO, str]:
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


def validate_file_size(file, media_type: str) -> None:
    limit = MEDIA_TYPE_SIZE_LIMITS.get(media_type)
    if limit and file.size > limit:
        raise ValueError(
            f"File exceeds {limit // (1024 * 1024)} MB limit for {media_type} files"
        )


def upload_file(file, *, ext: str | None = None) -> dict[str, Any]:
    _ensure_credentials()

    source_name = getattr(file, "name", "") or ""
    info = _classify(ext if ext else source_name)
    media_type = info["media_type"]
    mime = info["mime"]

    validate_file_size(file, media_type)

    ext = os.path.splitext(source_name)[1].lower() or ext or ""
    upload_data = file
    content_type = mime
    key = _get_path(media_type, ext)
    metadata: dict[str, Any] = {
        "media_type": media_type,
        "width": None,
        "height": None,
    }

    if media_type == MediaType.IMAGE.value:
        normalized, fmt, norm_ext = _normalize_image(file, ext)
        upload_data = normalized
        key = _get_path(media_type, norm_ext)
        content_type = f"image/{fmt}"
        with Image.open(file) as img:
            metadata["width"], metadata["height"] = img.size
    elif media_type == MediaType.VIDEO.value:
        file.seek(0)
    elif media_type == MediaType.AUDIO.value:
        file.seek(0)
    elif media_type == MediaType.DOCUMENT.value:
        file.seek(0)

    s3 = _get_client()
    try:
        s3.upload_fileobj(
            upload_data,
            AWS_STORAGE_BUCKET_NAME,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "ContentDisposition": "inline",
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )
    except ClientError as e:
        logger.error("S3 upload failed: %s", e)
        raise ValueError(str(e)) from e

    metadata.update({
        "key": key,
        "url": f"{AWS_S3_CUSTOM_DOMAIN}/{key}",
        "content_type": content_type,
        "file_size_bytes": file.size,
    })
    return metadata


def generate_presigned_upload_url(
    file_name: str,
    *,
    expires_in: int = 3600,
) -> dict[str, Any]:
    _ensure_credentials()

    info = _classify(file_name)
    media_type = info["media_type"]
    mime = info["mime"]
    ext = os.path.splitext(file_name)[1].lower()
    key = _get_path(media_type, ext)

    s3 = _get_client()
    try:
        url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": AWS_STORAGE_BUCKET_NAME,
                "Key": key,
                "ContentType": mime,
            },
            ExpiresIn=expires_in,
        )
    except ClientError as e:
        logger.error("Failed to generate presigned URL: %s", e)
        raise ValueError("Failed to generate upload URL") from e

    return {
        "url": url,
        "key": key,
        "media_type": media_type,
        "content_type": mime,
    }


def delete_file(file_url: str) -> bool:
    if not file_url:
        return False

    prefix = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/"
    if not file_url.startswith(prefix):
        logger.warning("URL does not match expected prefix: %s", prefix)
        return False

    key = file_url[len(prefix):]
    logger.info("Deleting S3 object: bucket=%s key=%s", AWS_STORAGE_BUCKET_NAME, key)

    s3 = _get_client()
    try:
        s3.delete_object(Bucket=AWS_STORAGE_BUCKET_NAME, Key=key)
        logger.info("S3 delete success: %s", key)
        return True
    except Exception as e:
        logger.error("S3 delete failed for %s: %s", file_url, e)
        return False


__all__ = [
    "upload_file",
    "delete_file",
    "generate_presigned_upload_url",
    "validate_file_size",
]

