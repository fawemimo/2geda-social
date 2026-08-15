from __future__ import annotations

import logging

from channels.layers import get_channel_layer
from django.contrib.contenttypes.models import ContentType

from accounts.models import User
from social.models import Notification as NotificationRecord

logger = logging.getLogger(__name__)


class NotificationService:

    def __init__(self, channel_layer=None):
        self.channel_layer = channel_layer or get_channel_layer()

    @classmethod
    def create_and_broadcast(
        cls,
        *,
        recipient: User,
        actor: User | None = None,
        notification_type: str,
        source_object=None,
        text_preview: str = "",
    ) -> NotificationRecord | None:
        service = cls()

        from notifications.models import NotificationPreference

        pref = NotificationPreference.objects.filter(user=recipient).first()
        if pref:
            if not pref.in_app_enabled:
                return None
            if pref.is_type_muted(notification_type):
                return None

        notif = service._create_record(
            recipient=recipient,
            actor=actor,
            notification_type=notification_type,
            source_object=source_object,
            text_preview=text_preview,
        )

        service._broadcast(notif)

        return notif

    def _create_record(
        self,
        *,
        recipient: User,
        actor: User | None,
        notification_type: str,
        source_object,
        text_preview: str,
    ) -> NotificationRecord:
        kwargs = {
            "recipient": recipient,
            "actor": actor,
            "notification_type": notification_type,
            "text_preview": text_preview,
        }

        if source_object is not None:
            ct = ContentType.objects.get_for_model(source_object)
            kwargs["content_type"] = ct
            kwargs["object_id"] = source_object.pk

        return NotificationRecord.objects.create(**kwargs)

    def _broadcast(self, notif: NotificationRecord) -> None:
        from notifications.models import NotificationPreference

        pref = NotificationPreference.objects.filter(user=notif.recipient).first()
        if pref and not pref.in_app_enabled:
            return

        group_name = f"notify_{notif.recipient_id}"
        payload = notif_to_payload(notif)

        try:
            from channels.db import database_sync_to_async
            import asyncio

            coro = self.channel_layer.group_send(group_name, payload)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(coro)
                else:
                    loop.run_until_complete(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception as exc:
            logger.exception("Failed to broadcast notification %s: %s", notif.id, exc)

    @classmethod
    def broadcast_unread_count(cls, user_id: str) -> None:
        group_name = f"notify_{user_id}"
        from social.models import Notification

        count = Notification.objects.filter(
            recipient_id=user_id,
            is_read=False,
        ).count()

        channel_layer = get_channel_layer()
        try:
            import asyncio

            coro = channel_layer.group_send(
                group_name,
                {"type": "unread_count", "unread_count": count},
            )
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(coro)
                else:
                    loop.run_until_complete(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception as exc:
            logger.exception(
                "Failed to broadcast unread count for %s: %s", user_id, exc
            )


def notif_to_payload(notif: NotificationRecord) -> dict:
    payload = {
        "type": "notification",
        "id": str(notif.id),
        "notification_type": notif.notification_type,
        "text_preview": notif.text_preview,
        "is_read": notif.is_read,
        "created_at": notif.created_at.isoformat(),
    }

    if notif.actor_id:
        payload["actor"] = {
            "id": str(notif.actor_id),
            "username": notif.actor.username,
        }

    if notif.content_type and notif.object_id:
        payload["source"] = {
            "content_type": notif.content_type.model,
            "object_id": str(notif.object_id),
        }

    return payload
