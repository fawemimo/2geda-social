from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="notifications.tasks.dispatch_notification",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def dispatch_notification(notification_id: str) -> None:
    from notifications.dispatcher import NotificationDispatcher
    from notifications.models import Notification

    try:
        notification = Notification.objects.get(pk=notification_id)
    except Notification.DoesNotExist:
        logger.exception("Notification %s not found for dispatch", notification_id)
        return

    NotificationDispatcher.dispatch(notification)
