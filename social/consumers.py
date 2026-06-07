from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)

User = get_user_model()


class PostConsumer(AsyncJsonWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.post_id: str | None = None
        self._group_name: str | None = None

    @property
    def group_name(self) -> str:
        if self._group_name is None:
            self._group_name = f"post_{self.post_id}"
        return self._group_name

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close()
            return

        self.post_id = self.scope["url_route"]["kwargs"]["post_id"]
        await self.accept()
        logger.info("Post WS connected user=%s post=%s", self.user.id, self.post_id)

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.send_json({
            "type": "connected",
            "post_id": self.post_id,
        })

    async def disconnect(self, close_code):
        if self.post_id and self.user:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )
            logger.info("Post WS disconnected user=%s post=%s code=%s", self.user.id, self.post_id, close_code)

    async def receive_json(self, content: dict):
        msg_type = content.get("type")
        handler = {
            "ping": self._handle_ping,
            "typing.start": self._handle_typing_start,
            "typing.stop": self._handle_typing_stop,
        }.get(msg_type)

        if handler is None:
            await self.send_json({
                "type": "error",
                "code": "unknown_type",
                "message": f"Unknown type: {msg_type}",
            })
            return

        await handler(content)

    async def _handle_ping(self, content: dict):
        await self.send_json({"type": "pong"})

    async def _handle_typing_start(self, content: dict):
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "post_event",
                "event": "typing.start",
                "user_id": str(self.user.id),
                "username": self.user.username,
            },
        )

    async def _handle_typing_stop(self, content: dict):
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "post_event",
                "event": "typing.stop",
                "user_id": str(self.user.id),
                "username": self.user.username,
            },
        )

    async def post_event(self, event: dict):
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


class FeedConsumer(AsyncJsonWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self._group_name: str | None = None

    @property
    def group_name(self) -> str:
        if self._group_name is None:
            self._group_name = f"user_{self.user.id}"
        return self._group_name

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close()
            return

        await self.accept()
        logger.info("Feed WS connected user=%s", self.user.id)

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.send_json({
            "type": "connected",
            "user_id": str(self.user.id),
        })

    async def disconnect(self, close_code):
        if self.user:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )
            logger.info("Feed WS disconnected user=%s code=%s", self.user.id, close_code)

    async def receive_json(self, content: dict):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def feed_event(self, event: dict):
        await self.send_json(event)

    async def presence_event(self, event: dict):
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
