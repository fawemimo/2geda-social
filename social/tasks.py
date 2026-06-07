from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)


@shared_task(
    name="social.tasks.process_post_media",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def process_post_media(post_id: str, media_ids: list[str]) -> None:
    from medias.models import Media, ProcessingStatus

    logger.info("Processing media for post %s: %s", post_id, media_ids)

    for media_id in media_ids:
        try:
            media = Media.objects.get(pk=media_id)
        except Media.DoesNotExist:
            logger.warning("Media %s not found, skipping", media_id)
            continue

        if media.processing_status == ProcessingStatus.READY.value:
            logger.info("Media %s already processed", media_id)
            continue

        try:
            from clients.aws.storage import upload_file

            if hasattr(media, "file") and media.file:
                result = upload_file(media.file)
                media.storage_key = result["key"]
                media.cdn_url = result["url"]
                media.mime_type = result["content_type"]
                media.file_size_bytes = result["file_size_bytes"]
                media.media_type = result["media_type"]
                media.width_px = result.get("width")
                media.height_px = result.get("height")
                media.processing_status = ProcessingStatus.READY.value
                media.save(update_fields=[
                    "storage_key", "cdn_url", "mime_type", "file_size_bytes",
                    "media_type", "width_px", "height_px", "processing_status",
                ])
                logger.info("Media %s uploaded and set to ready", media_id)
            else:
                media.processing_status = ProcessingStatus.READY.value
                media.save(update_fields=["processing_status"])
                logger.info("Media %s marked as ready (no local file)", media_id)
        except Exception as exc:
            logger.exception("Failed to upload media %s: %s", media_id, exc)
            media.processing_status = ProcessingStatus.FAILED.value
            media.processing_error = str(exc)[:500]
            media.save(update_fields=["processing_status", "processing_error"])


@shared_task(
    name="social.tasks.delete_media_files",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def delete_media_files(storage_keys: list[str]) -> None:
    from clients.aws.storage import delete_file

    logger.info("Deleting %d media files from S3", len(storage_keys))
    for key in storage_keys:
        if key:
            try:
                success = delete_file(key)
                if success:
                    logger.info("Deleted S3 object: %s", key)
                else:
                    logger.warning("Failed to delete S3 object: %s", key)
            except Exception:
                logger.exception("Error deleting S3 object: %s", key)


@shared_task(
    name="social.tasks.notify_followers",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def notify_followers(
    actor_id: str,
    notification_type: str,
    title: str,
    body: str,
    source_model: str,
    source_id: str,
) -> None:
    from accounts.models import Follow, FollowStatus
    from notifications.services.dto import CreateNotificationDTO
    from notifications.services.notification_services import NotificationService as NotificationCreator
    from notifications.tasks import dispatch_notification

    logger.info(
        "Notifying followers of %s about %s (%s)",
        actor_id, notification_type, source_id,
    )

    follower_ids = (
        Follow.objects
        .filter(following_id=actor_id, status=FollowStatus.ACCEPTED.value)
        .values_list("follower_id", flat=True)
    )

    source_ct = None
    try:
        from django.apps import apps
        try:
            model = apps.get_model("social", source_model)
            source_ct = ContentType.objects.get_for_model(model)
        except LookupError:
            logger.warning("Could not resolve content type for %s", source_model)
    except Exception:
        logger.warning("Failed to resolve content type for %s", source_model)

    for follower_id in follower_ids:
        try:
            dto = CreateNotificationDTO(
                recipient_id=str(follower_id),
                notification_type=notification_type,
                title=title,
                body=body,
                actor_id=actor_id,
                source_model=None if source_ct is None else source_ct.model_class(),
                source_id=source_id if source_ct else "",
                priority="normal",
            )
            notification = NotificationCreator.create(dto)
            dispatch_notification.delay(str(notification.id))
        except Exception:
            logger.exception("Failed to notify follower %s", follower_id)


@shared_task(
    name="social.tasks.broadcast_post_to_followers",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def broadcast_post_to_followers(post_id: str, author_id: str, event: dict) -> None:
    from accounts.models import Follow, FollowStatus
    from social.event_broadcaster import sync_broadcast_to_group

    logger.info("Broadcasting post %s to followers of %s", post_id, author_id)

    follower_ids = (
        Follow.objects
        .filter(following_id=author_id, status=FollowStatus.ACCEPTED.value)
        .values_list("follower_id", flat=True)
    )

    payload = {"type": "feed_event", **event}

    for follower_id in follower_ids:
        try:
            sync_broadcast_to_group(f"user_{follower_id}", payload)
        except Exception:
            logger.exception("Failed to broadcast to follower %s", follower_id)
