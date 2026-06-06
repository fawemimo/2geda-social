from __future__ import annotations

import asyncio
import logging

from channels.layers import get_channel_layer

from accounts.tasks import send_user_push_notification
from notifications.models import Notification

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """
    Delivers a Notification to the recipient via:
      1. WebSocket (real-time via channel layer group notify_{id})
      2. Push notification (Firebase via Celery task)
    """

    @staticmethod
    def dispatch(notification: Notification) -> None:
        NotificationDispatcher._broadcast_ws(notification)
        NotificationDispatcher._dispatch_push(notification)

    @staticmethod
    def _broadcast_ws(notification: Notification) -> None:
        group_name = f"notify_{notification.recipient_id}"
        payload = NotificationDispatcher._to_ws_payload(notification)
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        try:
            coro = channel_layer.group_send(group_name, payload)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(coro)
                else:
                    loop.run_until_complete(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception:
            logger.exception("Failed to broadcast WS notification %s", notification.id)

    @staticmethod
    def _dispatch_push(notification: Notification) -> None:
        if not notification.title:
            return
        try:
            send_user_push_notification.delay(
                user_id=str(notification.recipient_id),
                title=notification.title,
                body=notification.body or "",
                data={
                    "type": "notification",
                    "notification_type": notification.notification_type,
                    "notification_id": str(notification.id),
                },
            )
        except Exception:
            logger.exception("Failed to dispatch push notification %s", notification.id)

    @staticmethod
    def _to_ws_payload(notification: Notification) -> dict:
        payload: dict = {
            "type": "notification",
            "id": str(notification.id),
            "notification_type": notification.notification_type,
            "category": notification.category,
            "title": notification.title,
            "body": notification.body or "",
            "is_read": notification.is_read,
            "is_sent_push": notification.is_sent_push,
            "created_at": notification.created_at.isoformat(),
        }
        if notification.actor_id:
            payload["actor"] = {
                "id": str(notification.actor_id),
                "username": notification.actor.username if notification.actor_id else None,
            }
        if notification.object_id:
            source: dict = {"object_id": str(notification.object_id)}
            if notification.content_type:
                source["content_type"] = notification.content_type.model
            payload["source"] = source
        return payload
