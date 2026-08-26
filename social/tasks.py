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
def process_post_media(post_id: str, media_ids: list[str]) -> dict:

    from django.db import transaction as db_transaction

    from medias.models import Media
    from social.models import Post, PostMedia

    if not media_ids:
        return {"attached": 0, "skipped": []}

    post = Post.objects.filter(pk=post_id).only("pk", "author_id").first()
    if post is None:
        logger.warning("Post %s not found; nothing to attach", post_id)
        return {"attached": 0, "skipped": [str(m) for m in media_ids]}

    # Only the author's own, non-deleted media may be attached — a post must not
    # be able to embed another user's asset by id.
    owned = {
        str(pk): pk
        for pk in Media.objects.filter(
            pk__in=media_ids, owner_id=post.author_id, is_deleted=False
        ).values_list("pk", flat=True)
    }

    rows, skipped = [], []
    for position, media_id in enumerate(media_ids):
        key = str(media_id)
        if key not in owned:
            skipped.append(key)
            continue
        rows.append(PostMedia(post_id=post.pk, media_id=owned[key], position=position))

    if skipped:
        logger.warning(
            "Post %s: %d media id(s) skipped (missing, deleted, or not owned by the author)",
            post_id, len(skipped),
        )

    if not rows:
        return {"attached": 0, "skipped": skipped}

    with db_transaction.atomic():
        PostMedia.objects.bulk_create(rows, ignore_conflicts=True)

    logger.info("Post %s: attached %d media", post_id, len(rows))
    return {"attached": len(rows), "skipped": skipped}


@shared_task(
    name="social.tasks.delete_media_files",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def delete_media_files(storage_keys: list[str]) -> None:
    # These are storage keys, not URLs — use the key-based delete.
    from clients.storage import StorageService

    storage = StorageService()

    logger.info("Deleting %d media files from S3", len(storage_keys))
    for key in storage_keys:
        if key:
            try:
                success = storage.delete(key)
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
