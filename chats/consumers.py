from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from chats.services import ChatService

logger = logging.getLogger(__name__)

User = get_user_model()

# Handles WebSocket connections for authenticated users in direct chats.

class DirectChatConsumer(AsyncJsonWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.conversation_ids: set[str] = set()

    #  Connection lifecycle

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close()
            return

        await self.accept()
        logger.info("WS connected user=%s", self.user.id)

        convs = await self._get_user_conversations()
        for cid in convs:
            await self.channel_layer.group_add(
                f"chat_{cid}",
                self.channel_name,
            )
            self.conversation_ids.add(cid)

        await self.send_json({
            "type": "connected",
            "user_id": str(self.user.id),
            "conversations": list(self.conversation_ids),
        })

    async def disconnect(self, close_code):
        for cid in self.conversation_ids:
            await self.channel_layer.group_discard(
                f"chat_{cid}",
                self.channel_name,
            )
        logger.info("WS disconnected user=%s code=%s", self.user, close_code)

    #  Inbound message routing

    async def receive_json(self, content: dict):
        msg_type = content.get("type")
        handler = {
            "send_message": self._handle_send_message,
            "mark_read": self._handle_mark_read,
            "typing.start": self._handle_typing_start,
            "typing.stop": self._handle_typing_stop,
            "conversation.join": self._handle_conversation_join,
        }.get(msg_type)

        if handler is None:
            await self.send_json({"type": "error", "code": "unknown_type", "message": f"Unknown type: {msg_type}"})
            return

        await handler(content)

    #  Message handlers ─

    async def _handle_send_message(self, content: dict):
        conversation_id = content.get("conversation_id")
        body = content.get("body", "")
        reply_to_id = content.get("reply_to_id")

        if not conversation_id:
            return await self._error("missing_conversation_id")

        can_send = await self._is_member(conversation_id)
        if not can_send:
            return await self._error("not_a_member")

        payload = await self._send_message(
            conversation_id=conversation_id,
            body=body,
            reply_to_id=reply_to_id,
        )
        payload["type"] = "new_message"

        await self.channel_layer.group_send(
            f"chat_{conversation_id}",
            payload,
        )

    async def _handle_mark_read(self, content: dict):
        conversation_id = content.get("conversation_id")
        if not conversation_id:
            return

        await self._mark_as_read(conversation_id)
        await self.channel_layer.group_send(
            f"chat_{conversation_id}",
            {
                "type": "read_receipt",
                "conversation_id": conversation_id,
                "user_id": str(self.user.id),
                "read_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            },
        )

    async def _handle_typing_start(self, content: dict):
        await self._broadcast_typing(content.get("conversation_id"), "start")

    async def _handle_typing_stop(self, content: dict):
        await self._broadcast_typing(content.get("conversation_id"), "stop")

    async def _handle_conversation_join(self, content: dict):
        conversation_id = content.get("conversation_id")
        if not conversation_id:
            return
        is_member = await self._is_member(conversation_id)
        if not is_member:
            return await self._error("not_a_member")
        if conversation_id not in self.conversation_ids:
            await self.channel_layer.group_add(
                f"chat_{conversation_id}",
                self.channel_name,
            )
            self.conversation_ids.add(conversation_id)

    #  Broadcast helpers

    async def _broadcast_typing(self, conversation_id: str | None, status: str):
        if not conversation_id:
            return
        await self.channel_layer.group_send(
            f"chat_{conversation_id}",
            {
                "type": "typing_indicator",
                "conversation_id": conversation_id,
                "user_id": str(self.user.id),
                "username": self.user.username,
                "status": status,
            },
        )

    async def _error(self, code: str, message: str | None = None) -> None:
        await self.send_json({"type": "error", "code": code, "message": message or code})

    #  Outbound event handlers (called by group_send)

    async def new_message(self, event: dict):
        await self.send_json(event)

    async def read_receipt(self, event: dict):
        await self.send_json(event)

    async def typing_indicator(self, event: dict):
        await self.send_json(event)

    #  Authentication

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

    #  Database helpers (async wrappers)

    @database_sync_to_async
    def _get_user_conversations(self):
        service = ChatService()
        return [
            str(c.id) for c in service.get_user_conversations(str(self.user.id))
        ]

    @database_sync_to_async
    def _send_message(self, conversation_id: str, body: str, reply_to_id: str | None):
        service = ChatService()
        result = service.send_message(
            conversation_id=conversation_id,
            sender_id=str(self.user.id),
            body=body,
            reply_to_id=reply_to_id,
        )
        return result.message.to_event_payload()

    @database_sync_to_async
    def _mark_as_read(self, conversation_id: str):
        ChatService.mark_as_read(
            user_id=str(self.user.id),
            conversation_id=conversation_id,
        )

    @database_sync_to_async
    def _is_member(self, conversation_id: str) -> bool:
        return ChatService.is_member(
            conversation_id=conversation_id,
            user_id=str(self.user.id),
        )

