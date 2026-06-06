from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)

User = get_user_model()


class NotificationConsumer(AsyncJsonWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self._group_name: str | None = None

    @property
    def group_name(self) -> str:
        if self._group_name is None:
            self._group_name = f"notify_{self.user.id}"
        return self._group_name

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close()
            return

        await self.accept()
        logger.info("Notif WS connected user=%s", self.user.id)

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        unread_count = await self._get_unread_count()
        await self.send_json({
            "type": "connected",
            "user_id": str(self.user.id),
            "unread_count": unread_count,
        })

    async def disconnect(self, close_code):
        if self.user:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )
            logger.info("Notif WS disconnected user=%s code=%s", self.user.id, close_code)

    async def receive_json(self, content: dict):
        msg_type = content.get("type")
        handler = {
            "mark_read": self._handle_mark_read,
            "mark_all_read": self._handle_mark_all_read,
            "ping": self._handle_ping,
        }.get(msg_type)

        if handler is None:
            await self.send_json({
                "type": "error",
                "code": "unknown_type",
                "message": f"Unknown type: {msg_type}",
            })
            return

        await handler(content)

    async def _handle_mark_read(self, content: dict):
        notification_id = content.get("notification_id")
        if not notification_id:
            return
        await self._mark_notification_read(notification_id)
        unread_count = await self._get_unread_count()
        await self.send_json({
            "type": "marked_read",
            "notification_id": notification_id,
            "unread_count": unread_count,
        })

    async def _handle_mark_all_read(self, content: dict):
        count = await self._mark_all_notifications_read()
        await self.send_json({
            "type": "marked_all_read",
            "marked_count": count,
            "unread_count": 0,
        })

    async def _handle_ping(self, content: dict):
        await self.send_json({"type": "pong"})

    async def notification(self, event: dict):
        await self.send_json(event)

    async def unread_count(self, event: dict):
        await self.send_json(event)

    async def _authenticate(self):
        token_str = None
        query_string = self.scope.get("query_string", b"").decode()
        for param in query_string.split("&"):
            if param.startswith("token="):
                token_str = param[6:]
                break

        if not token_str:
            return None

        try:
            access = AccessToken(token_str)
            user = await database_sync_to_async(User.objects.get)(pk=access["user_id"])
            return user if user.is_active else None
        except (TokenError, User.DoesNotExist, KeyError):
            return None

    @database_sync_to_async
    def _get_unread_count(self) -> int:
        from notifications.models import Notification
        return Notification.objects.filter(
            recipient=self.user, is_read=False, is_deleted=False,
        ).count()

    @database_sync_to_async
    def _mark_notification_read(self, notification_id: str):
        from notifications.models import Notification
        try:
            notif = Notification.objects.get(
                id=notification_id, recipient=self.user, is_deleted=False,
            )
            notif.mark_as_read()
        except Notification.DoesNotExist:
            pass

    @database_sync_to_async
    def _mark_all_notifications_read(self) -> int:
        from django.utils import timezone
        from notifications.models import Notification
        count = Notification.objects.filter(
            recipient=self.user, is_read=False, is_deleted=False,
        ).update(is_read=True, read_at=timezone.now())
        return count
