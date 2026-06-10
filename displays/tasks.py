from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    name="displays.tasks.hard_delete_expired_displays",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def hard_delete_expired_displays() -> dict:
    now = timezone.now()

    from displays.models import Display

    expired_qs = Display.objects.filter(
        expires_at__lte=now,
        is_deleted=False,
    ).select_related("media").only("pk", "media_id")

    display_ids = list(expired_qs.values_list("pk", flat=True))
    total = len(display_ids)

    if total == 0:
        logger.info("No expired displays to delete.")
        return {"deleted_count": 0}

    logger.info(
        "Hard-deleting %d expired display(s) older than %s.",
        total, now.isoformat(),
    )

    with transaction.atomic():
        from displays.models import DisplayComment, DisplayLike, DisplayView

        DisplayComment.objects.filter(display_id__in=display_ids).delete()
        DisplayLike.objects.filter(display_id__in=display_ids).delete()
        DisplayView.objects.filter(display_id__in=display_ids).delete()

        deleted, _ = expired_qs.delete()

    logger.info("Successfully hard-deleted %d expired displays.", deleted)
    return {"deleted_count": deleted}


@shared_task(
    name="displays.tasks.notify_display_followers",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def notify_display_followers(
    actor_id: str,
    display_id: str,
    title: str,
    body: str,
) -> None:
    from accounts.models import Follow, FollowStatus
    from displays.models import Display
    from notifications.services.dto import CreateNotificationDTO
    from notifications.services.notification_services import NotificationService as NotificationCreator
    from notifications.tasks import dispatch_notification

    logger.info(
        "Notifying followers of %s about display %s", actor_id, display_id,
    )

    follower_ids = (
        Follow.objects
        .filter(following_id=actor_id, status=FollowStatus.ACCEPTED.value)
        .values_list("follower_id", flat=True)
    )

    from django.contrib.contenttypes.models import ContentType
    source_ct = ContentType.objects.get_for_model(Display)

    for follower_id in follower_ids:
        try:
            dto = CreateNotificationDTO(
                recipient_id=str(follower_id),
                notification_type="display_created",
                title=title,
                body=body,
                actor_id=actor_id,
                source_model=Display,
                source_id=display_id,
                priority="normal",
            )
            notification = NotificationCreator.create(dto)
            dispatch_notification.delay(str(notification.id))
        except Exception:
            logger.exception("Failed to notify follower %s about display %s", follower_id, display_id)
