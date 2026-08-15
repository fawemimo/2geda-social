from __future__ import annotations

import base64
import logging

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(
    name="medias.tasks.process_media_upload",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def process_media_upload(media_id: str, file_bytes_base64: str, filename: str) -> dict:

    from clients.storage import StorageService
    from medias.models import Media, ProcessingStatus

    logger.info("Processing media upload | id=%s filename=%s", media_id, filename)

    try:
        media = Media.objects.get(pk=media_id)
    except Media.DoesNotExist:
        logger.exception("Media %s not found", media_id)
        return {"success": False, "error": "not_found"}

    try:
        raw = base64.b64decode(file_bytes_base64)
    except Exception as exc:
        logger.exception("Failed to decode file bytes for media %s: %s", media_id, exc)
        return {"success": False, "error": "decode_failed"}

    django_file = ContentFile(raw, name=filename)

    try:
        result = StorageService().upload(django_file)
    except Exception as exc:
        logger.exception("Storage upload failed for media %s: %s", media_id, exc)
        with transaction.atomic():
            media.refresh_from_db()
            media.processing_status = ProcessingStatus.FAILED.value
            media.processing_error = str(exc)[:500]
            media.save(update_fields=["processing_status", "processing_error"])
        return {"success": False, "error": str(exc)}

    with transaction.atomic():
        media.refresh_from_db()
        media.storage_key = result.key
        media.cdn_url = result.url
        media.mime_type = result.content_type
        media.file_size_bytes = result.size_bytes
        media.media_type = result.media_type or media.media_type
        media.width_px = result.width
        media.height_px = result.height
        media.processing_status = ProcessingStatus.READY.value
        media.processing_error = ""
        media.save()

    logger.info(
        "Media upload complete | id=%s key=%s",
        media_id,
        result.key,
    )
    return {"success": True, "key": result.key}


@shared_task(
    name="medias.tasks.generate_presigned_url",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def generate_presigned_url(file_name: str, *, expires_in: int = 3600) -> dict:
    """Wrapper around the storage presigned-upload flow for async/batch use."""
    from clients.storage import StorageService

    logger.info("Generating presigned URL for %s", file_name)
    try:
        signed = StorageService().presigned_upload(file_name, expires_in=expires_in)
        return {
            "url": signed.url,
            "key": signed.key,
            "media_type": signed.media_type,
            "content_type": signed.content_type,
            "headers": signed.headers,
        }
    except Exception as exc:
        logger.exception("Failed to generate presigned URL for %s: %s", file_name, exc)
        return {"error": str(exc)}


@shared_task(
    name="medias.tasks.delete_media_file",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def delete_media_file(storage_key: str) -> bool:
    """Delete a file from object storage by its storage key."""
    from clients.storage import StorageService

    logger.info("Deleting S3 file | key=%s", storage_key)
    try:
        result = StorageService().delete(storage_key)
        if result:
            logger.info("S3 file deleted | key=%s", storage_key)
        else:
            logger.warning("S3 deletion returned False | key=%s", storage_key)
        return result
    except Exception as exc:
        logger.exception("Failed to delete S3 file %s: %s", storage_key, exc)
        return False
