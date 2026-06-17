from __future__ import annotations

import logging
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from utils.enum import CallType
from chats.models import Conversation, ConversationMember, Message
from chats.services import ChatService

logger = logging.getLogger(__name__)

User = get_user_model()

PRESENCE_CACHE_TTL = 300        # 5 min — refreshed by heartbeat
HEARTBEAT_INTERVAL = 30         # seconds
PRESENCE_CACHE_PREFIX = "online_user:"


class DirectChatConsumer(AsyncJsonWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.conversation_ids: set[str] = set()

    # ──────────────────────────────────────────────────────────────────────────
    #  Connection lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close()
            return

        await self.accept()

        try:
            user_id = str(self.user.id)
            logger.info("WS connected user=%s", user_id)

            await self.channel_layer.group_add(f"user_{user_id}", self.channel_name)

            convs = await self._get_user_conversations()
            for cid in convs:
                await self.channel_layer.group_add(f"chat_{cid}", self.channel_name)
                self.conversation_ids.add(cid)

            await self._set_online()
            await self._broadcast_presence("presence.online")

            online_members = await self._get_online_members()
            await self.send_json({
                "type": "connected",
                "user_id": user_id,
                "conversations": list(self.conversation_ids),
                "online_users": online_members,
            })
        except Exception:
            logger.exception("WS connect error user=%s", getattr(self.user, "id", "?"))
            await self.close()

    async def disconnect(self, close_code):
        try:
            if self.user:
                user_id = str(self.user.id)
                await self.channel_layer.group_discard(f"user_{user_id}", self.channel_name)
                for cid in self.conversation_ids:
                    await self.channel_layer.group_discard(f"chat_{cid}", self.channel_name)
                await self._set_offline()
                await self._broadcast_presence("presence.offline")
        except Exception:
            logger.exception("WS disconnect error")

        logger.info("WS disconnected user=%s code=%s", getattr(self.user, "id", "?"), close_code)

    # ──────────────────────────────────────────────────────────────────────────
    #  Inbound message routing
    # ──────────────────────────────────────────────────────────────────────────

    async def receive_json(self, content: dict):
        msg_type = content.get("type")
        handler = {
            "send_message": self._handle_send_message,
            "delete_message": self._handle_delete_message,
            "mark_read": self._handle_mark_read,
            "typing.start": self._handle_typing_start,
            "typing.stop": self._handle_typing_stop,
            "conversation.join": self._handle_conversation_join,
            "ping": self._handle_ping,
            "call.offer": self._handle_call_offer,
            "call.answer": self._handle_call_answer,
            "call.ice_candidate": self._handle_call_ice_candidate,
            "call.end": self._handle_call_end,
            "call.video_toggle": self._handle_video_toggle,
            "call.screen_share": self._handle_screen_share,
        }.get(msg_type)

        if handler is None:
            await self.send_json({
                "type": "error", "code": "unknown_type",
                "message": f"Unknown type: {msg_type}",
            })
            return

        await handler(content)

    # ──────────────────────────────────────────────────────────────────────────
    #  Message handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_send_message(self, content: dict):
        conversation_id = content.get("conversation_id")
        body = content.get("body", "")
        reply_to_id = content.get("reply_to_id")

        if not conversation_id:
            return await self._error("missing_conversation_id")

        can_send = await self._is_member(conversation_id)
        if not can_send:
            return await self._error("not_a_member")

        is_locked = await self._is_conversation_locked(conversation_id)
        if is_locked:
            is_admin = await self._is_admin_or_owner(conversation_id)
            if not is_admin:
                return await self._error("group_locked", "This group is locked. Only admins can send messages.")

        payload = await self._send_message(
            conversation_id=conversation_id,
            body=body,
            reply_to_id=reply_to_id,
        )
        payload["type"] = "new_message"

        await self.channel_layer.group_send(f"chat_{conversation_id}", payload)

    async def _handle_delete_message(self, content: dict):
        message_id = content.get("message_id")
        if not message_id:
            return await self._error("missing_message_id")

        try:
            result = await self._delete_message(message_id=message_id)
        except PermissionError:
            return await self._error("not_allowed", "You can only delete your own messages.")
        except Message.DoesNotExist:
            return await self._error("message_not_found")

        await self.channel_layer.group_send(
            f"chat_{result['conversation_id']}",
            {
                "type": "message_deleted",
                "message_id": result["message_id"],
                "conversation_id": result["conversation_id"],
                "deleted_by_id": str(self.user.id),
            },
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
                "read_at": timezone.now().isoformat(),
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
                f"chat_{conversation_id}", self.channel_name,
            )
            self.conversation_ids.add(conversation_id)

    # ──────────────────────────────────────────────────────────────────────────
    #  Heartbeat
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_ping(self, content: dict):
        await self._touch_online()
        await self.send_json({"type": "pong"})

    # ──────────────────────────────────────────────────────────────────────────
    #  Call signalling (WebRTC relay)
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_call_offer(self, content: dict):
        peer_id = content.get("peer_id")
        conversation_id = content.get("conversation_id")
        sdp = content.get("sdp")
        call_type = content.get("call_type", CallType.AUDIO.value)

        if not peer_id or not conversation_id or not sdp:
            return await self._error("missing_call_params")

        call_type = call_type if call_type in (CallType.AUDIO.value, CallType.VIDEO.value) else CallType.AUDIO.value

        can_call = await self._can_initiate_call(conversation_id, peer_id)
        if not can_call:
            return await self._error("call_not_allowed")

        await self.channel_layer.group_send(
            f"user_{peer_id}",
            {
                "type": "call_offer",
                "caller_id": str(self.user.id),
                "caller_username": self.user.username,
                "conversation_id": conversation_id,
                "call_type": call_type,
                "sdp": sdp,
            },
        )

    async def _handle_call_answer(self, content: dict):
        peer_id = content.get("peer_id")
        sdp = content.get("sdp")
        call_type = content.get("call_type")
        if not peer_id or not sdp:
            return await self._error("missing_call_params")

        relay = {
            "type": "call_answer",
            "callee_id": str(self.user.id),
            "sdp": sdp,
        }
        if call_type:
            relay["call_type"] = call_type
        await self.channel_layer.group_send(f"user_{peer_id}", relay)

    async def _handle_call_ice_candidate(self, content: dict):
        peer_id = content.get("peer_id")
        candidate = content.get("candidate")
        if not peer_id or not candidate:
            return await self._error("missing_call_params")

        await self.channel_layer.group_send(
            f"user_{peer_id}",
            {
                "type": "call_ice_candidate",
                "from_id": str(self.user.id),
                "candidate": candidate,
            },
        )

    async def _handle_call_end(self, content: dict):
        peer_id = content.get("peer_id")
        if not peer_id:
            return await self._error("missing_call_params")

        await self.channel_layer.group_send(
            f"user_{peer_id}",
            {
                "type": "call_ended",
                "ended_by": str(self.user.id),
                "reason": content.get("reason", "ended"),
            },
        )

    async def _handle_video_toggle(self, content: dict):
        peer_id = content.get("peer_id")
        enabled = content.get("enabled")
        if not peer_id or enabled is None:
            return await self._error("missing_call_params")

        await self.channel_layer.group_send(
            f"user_{peer_id}",
            {
                "type": "video_toggle",
                "user_id": str(self.user.id),
                "enabled": bool(enabled),
            },
        )

    async def _handle_screen_share(self, content: dict):
        peer_id = content.get("peer_id")
        sdp = content.get("sdp")
        sharing = content.get("sharing", True)
        if not peer_id or sdp is None:
            return await self._error("missing_call_params")

        await self.channel_layer.group_send(
            f"user_{peer_id}",
            {
                "type": "screen_share",
                "from_id": str(self.user.id),
                "sdp": sdp,
                "sharing": bool(sharing),
            },
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  Outbound event handlers (called by group_send)
    # ──────────────────────────────────────────────────────────────────────────

    async def new_message(self, event: dict):
        await self.send_json(event)

    async def read_receipt(self, event: dict):
        await self.send_json(event)

    async def typing_indicator(self, event: dict):
        await self.send_json(event)

    async def presence_online(self, event: dict):
        await self.send_json(event)

    async def presence_offline(self, event: dict):
        await self.send_json(event)

    async def call_offer(self, event: dict):
        await self.send_json(event)

    async def call_answer(self, event: dict):
        await self.send_json(event)

    async def call_ice_candidate(self, event: dict):
        await self.send_json(event)

    async def call_ended(self, event: dict):
        await self.send_json(event)

    async def video_toggle(self, event: dict):
        await self.send_json(event)

    async def screen_share(self, event: dict):
        await self.send_json(event)

    async def message_deleted(self, event: dict):
        await self.send_json(event)

    async def member_removed(self, event: dict):
        await self.send_json(event)

    async def group_locked(self, event: dict):
        await self.send_json(event)

    async def group_unlocked(self, event: dict):
        await self.send_json(event)

    async def group_members_updated(self, event: dict):
        await self.send_json(event)

    async def join_request_created(self, event: dict):
        await self.send_json(event)

    async def join_request_approved(self, event: dict):
        await self.send_json(event)

    async def join_request_rejected(self, event: dict):
        await self.send_json(event)

    async def member_promoted(self, event: dict):
        await self.send_json(event)

    # ──────────────────────────────────────────────────────────────────────────
    #  Broadcast helpers
    # ──────────────────────────────────────────────────────────────────────────

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

    async def _broadcast_presence(self, event_type: str):
        user_id = str(self.user.id)
        for cid in self.conversation_ids:
            await self.channel_layer.group_send(
                f"chat_{cid}",
                {
                    "type": event_type,
                    "user_id": user_id,
                    "username": self.user.username,
                },
            )

    async def _error(self, code: str, message: str | None = None) -> None:
        await self.send_json({"type": "error", "code": code, "message": message or code})

    # ──────────────────────────────────────────────────────────────────────────
    #  Presence helpers (cache-backed)
    # ──────────────────────────────────────────────────────────────────────────

    async def _set_online(self):
        user_id = str(self.user.id)
        cache.set(
            f"{PRESENCE_CACHE_PREFIX}{user_id}",
            timezone.now().isoformat(),
            timeout=PRESENCE_CACHE_TTL,
        )
        await self._update_last_seen()

    async def _touch_online(self):
        user_id = str(self.user.id)
        cache.touch(f"{PRESENCE_CACHE_PREFIX}{user_id}", timeout=PRESENCE_CACHE_TTL)

    async def _set_offline(self):
        user_id = str(self.user.id)
        cache.delete(f"{PRESENCE_CACHE_PREFIX}{user_id}")
        await self._update_last_seen()

    @database_sync_to_async
    def _update_last_seen(self):
        try:
            User.objects.filter(pk=self.user.pk).update(last_seen=timezone.now())
        except Exception:
            logger.warning("Failed to update last_seen for user=%s", self.user.pk)

    async def _get_online_members(self) -> list[dict]:
        peer_ids = await self._get_conversation_peer_ids()
        online = []
        for pid in peer_ids:
            val = await database_sync_to_async(cache.get)(f"{PRESENCE_CACHE_PREFIX}{pid}")
            if val:
                online.append({"user_id": pid})
        return online

    @database_sync_to_async
    def _get_conversation_peer_ids(self) -> list[str]:
        if not self.conversation_ids:
            return []
        members = ConversationMember.objects.filter(
            conversation_id__in=list(self.conversation_ids),
            left_at__isnull=True,
        ).exclude(user_id=self.user.pk).values_list("user_id", flat=True).distinct()
        return [str(uid) for uid in members]

    @database_sync_to_async
    def _can_initiate_call(self, conversation_id: str, peer_id: str) -> bool:
        return ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user_id__in=[self.user.pk, peer_id],
            left_at__isnull=True,
        ).values_list("user_id", flat=True).distinct().count() == 2

    # ──────────────────────────────────────────────────────────────────────────
    #  Authentication
    # ──────────────────────────────────────────────────────────────────────────

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

    # ──────────────────────────────────────────────────────────────────────────
    #  Database helpers (async wrappers)
    # ──────────────────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _get_user_conversations(self):
        service = ChatService()
        return [str(c.id) for c in service.get_user_conversations(str(self.user.id))]

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

    @database_sync_to_async
    def _is_conversation_locked(self, conversation_id: str) -> bool:
        try:
            conv = Conversation.objects.get(pk=conversation_id)
            return conv.is_locked
        except (Conversation.DoesNotExist, ValidationError):
            return False

    @database_sync_to_async
    def _is_admin_or_owner(self, conversation_id: str) -> bool:
        return ChatService._is_admin_or_owner(
            conversation_id=conversation_id,
            user_id=str(self.user.id),
        )

    @database_sync_to_async
    def _delete_message(self, message_id: str) -> dict:
        msg = ChatService.delete_message(
            message_id=message_id,
            actor_id=str(self.user.id),
        )
        return {
            "message_id": str(msg.id),
            "conversation_id": str(msg.conversation_id),
        }
