"""
Test the DirectChatConsumer WebSocket layer.

Database operations inside the consumer are mocked to avoid SQLite
threading issues with database_sync_to_async.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from channels.testing import WebsocketCommunicator

from accounts.models import User
from chats.consumers import DirectChatConsumer
from chats.models import Conversation, ConversationMember
from utils.enum import MemberRole

pytestmark = pytest.mark.django_db

asynctest = pytest.mark.asyncio


def _path(user: User | None = None) -> str:
    if user is None:
        return "/ws/chat/"
    from rest_framework_simplejwt.tokens import AccessToken

    return f"/ws/chat/?token={AccessToken.for_user(user)}"


@pytest.fixture
def user(db):
    u = User.objects.create_user(email="wst@t.com", username="wst", password="p")
    u.is_active = True
    u.save(update_fields=["is_active"])
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create_user(
        email="wsother@t.com", username="wsother", password="p",
    )
    u.is_active = True
    u.save(update_fields=["is_active"])
    return u


@pytest.fixture
def conversation(db, user, other_user):
    conv = Conversation.objects.create(created_by=user)
    ConversationMember.objects.create(
        conversation=conv, user=user, role=MemberRole.MEMBER.value,
    )
    ConversationMember.objects.create(conversation=conv, user=other_user)
    return conv


def _patch_consumer(monkeypatch, user, conv_ids=frozenset({"conv-1"})):
    """Replace all database-bound methods and channel layer with mocks."""

    async def fake_auth(_self):
        return user

    monkeypatch.setattr(DirectChatConsumer, "_authenticate", fake_auth)
    monkeypatch.setattr(DirectChatConsumer, "_get_user_conversations", AsyncMock(return_value=list(conv_ids)))
    monkeypatch.setattr(DirectChatConsumer, "_set_online", AsyncMock())
    monkeypatch.setattr(DirectChatConsumer, "_set_offline", AsyncMock())
    monkeypatch.setattr(DirectChatConsumer, "_touch_online", AsyncMock())
    monkeypatch.setattr(DirectChatConsumer, "_update_last_seen", AsyncMock())
    monkeypatch.setattr(DirectChatConsumer, "_get_online_members", AsyncMock(return_value=[]))
    monkeypatch.setattr(DirectChatConsumer, "_get_conversation_peer_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(DirectChatConsumer, "_can_initiate_call", AsyncMock(return_value=True))
    monkeypatch.setattr(DirectChatConsumer, "_broadcast_presence", AsyncMock())
    monkeypatch.setattr(
        DirectChatConsumer, "_send_message",
        AsyncMock(return_value={
            "id": "m1",
            "conversation_id": "conv-1",
            "sender_id": str(user.id),
            "sender_username": user.username,
            "message_type": "text",
            "body": "hello",
            "reply_to_id": None,
            "media_url": None,
            "is_edited": False,
            "delivery_status": "sent",
            "created_at": "2026-06-03T12:00:00",
        }),
    )
    monkeypatch.setattr(DirectChatConsumer, "_mark_as_read", AsyncMock())
    monkeypatch.setattr(DirectChatConsumer, "_is_member", AsyncMock(return_value=True))



class TestConnect:
    @asynctest
    async def test_connect_sends_connected_event(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user, conv_ids={"conv-a", "conv-b"})
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        connected, _ = await comm.connect()
        assert connected is True

        resp = await comm.receive_json_from()
        assert resp["type"] == "connected"
        assert resp["user_id"] == str(user.id)
        assert "conv-a" in resp["conversations"]
        assert "conv-b" in resp["conversations"]
        assert "online_users" in resp

        await comm.disconnect()

    @asynctest
    async def test_connect_sets_online(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        monkeypatch.setattr(DirectChatConsumer, "_set_online", AsyncMock(wraps=DirectChatConsumer._set_online))
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()
        set_online = getattr(DirectChatConsumer, "_set_online")
        set_online.assert_awaited_once()
        await comm.disconnect()

    @asynctest
    async def test_connect_rejects_when_auth_fails(self, monkeypatch):
        async def fake_auth(_self):
            return None

        monkeypatch.setattr(DirectChatConsumer, "_authenticate", fake_auth)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        connected, _ = await comm.connect()
        assert connected is False


# ─────────────────────────────────────────────────────────────────────────────
#  Send Message
# ─────────────────────────────────────────────────────────────────────────────


class TestSendMessage:
    @asynctest
    async def test_broadcasts_new_message(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "send_message",
            "conversation_id": "conv-1",
            "body": "hello",
        })

        resp = await comm.receive_json_from()
        assert resp["type"] == "new_message"
        assert resp["body"] == "hello"
        assert resp["sender_id"] == str(user.id)

        await comm.disconnect()

    @asynctest
    async def test_returns_error_when_not_member(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        monkeypatch.setattr(
            DirectChatConsumer, "_is_member", AsyncMock(return_value=False),
        )
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "send_message",
            "conversation_id": "conv-1",
            "body": "fail",
        })

        resp = await comm.receive_json_from()
        assert resp["type"] == "error"
        assert resp["code"] == "not_a_member"

        await comm.disconnect()

    @asynctest
    async def test_returns_error_when_missing_conv_id(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "send_message", "body": "no conv"})

        resp = await comm.receive_json_from()
        assert resp["type"] == "error"
        assert resp["code"] == "missing_conversation_id"

        await comm.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Mark Read
# ─────────────────────────────────────────────────────────────────────────────


class TestMarkRead:
    @asynctest
    async def test_broadcasts_read_receipt(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "mark_read",
            "conversation_id": "conv-1",
        })

        resp = await comm.receive_json_from()
        assert resp["type"] == "read_receipt"
        assert resp["conversation_id"] == "conv-1"
        assert resp["user_id"] == str(user.id)

        await comm.disconnect()

    @asynctest
    async def test_no_conv_id_is_silent(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "mark_read"})
        await comm.send_json_to({"type": "send_message", "conversation_id": "conv-1", "body": "p"})
        resp = await comm.receive_json_from()
        assert resp["type"] == "new_message"

        await comm.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Typing
# ─────────────────────────────────────────────────────────────────────────────


class TestTyping:
    @asynctest
    async def test_typing_start_broadcasts(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "typing.start",
            "conversation_id": "conv-1",
        })

        resp = await comm.receive_json_from()
        assert resp["type"] == "typing_indicator"
        assert resp["status"] == "start"
        assert resp["user_id"] == str(user.id)

        await comm.disconnect()

    @asynctest
    async def test_typing_stop_broadcasts(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "typing.stop",
            "conversation_id": "conv-1",
        })

        resp = await comm.receive_json_from()
        assert resp["type"] == "typing_indicator"
        assert resp["status"] == "stop"

        await comm.disconnect()

    @asynctest
    async def test_no_conv_id_is_silent(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "typing.start"})
        await comm.send_json_to({"type": "send_message", "conversation_id": "conv-1", "body": "p"})
        resp = await comm.receive_json_from()
        assert resp["type"] == "new_message"

        await comm.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Conversation Join
# ─────────────────────────────────────────────────────────────────────────────


class TestConversationJoin:
    @asynctest
    async def test_join_success(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()
        await comm.send_json_to({
            "type": "conversation.join",
            "conversation_id": "conv-new",
        })
        await comm.disconnect()

    @asynctest
    async def test_join_not_member(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        monkeypatch.setattr(
            DirectChatConsumer, "_is_member", AsyncMock(return_value=False),
        )
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "conversation.join",
            "conversation_id": "conv-x",
        })

        resp = await comm.receive_json_from()
        assert resp["type"] == "error"
        assert resp["code"] == "not_a_member"

        await comm.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Unknown message type
# ─────────────────────────────────────────────────────────────────────────────


class TestUnknownType:
    @asynctest
    async def test_unknown_type_returns_error(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "bogus_command"})

        resp = await comm.receive_json_from()
        assert resp["type"] == "error"
        assert "bogus_command" in resp["message"]

        await comm.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Heartbeat
# ─────────────────────────────────────────────────────────────────────────────


class TestHeartbeat:
    @asynctest
    async def test_ping_returns_pong(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "ping"})
        resp = await comm.receive_json_from()
        assert resp["type"] == "pong"

        await comm.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Call signalling
# ─────────────────────────────────────────────────────────────────────────────


class TestCallSignalling:
    @asynctest
    async def test_audio_call_offer_relays_to_peer(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.offer",
            "peer_id": "peer-1",
            "conversation_id": "conv-1",
            "call_type": "audio",
            "sdp": "v=0\r\ns=-",
        })
        await comm.disconnect()

    @asynctest
    async def test_video_call_offer_relays_to_peer(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.offer",
            "peer_id": "peer-1",
            "conversation_id": "conv-1",
            "call_type": "video",
            "sdp": "v=0\r\ns=-",
        })
        await comm.disconnect()

    @asynctest
    async def test_call_offer_defaults_to_audio(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.offer",
            "peer_id": "peer-1",
            "conversation_id": "conv-1",
            "sdp": "v=0",
        })
        await comm.disconnect()

    @asynctest
    async def test_call_offer_invalid_call_type_defaults_to_audio(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.offer",
            "peer_id": "peer-1",
            "conversation_id": "conv-1",
            "call_type": "invalid",
            "sdp": "v=0",
        })
        await comm.disconnect()

    @asynctest
    async def test_call_offer_missing_params_returns_error(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "call.offer", "peer_id": "peer-1"})
        resp = await comm.receive_json_from()
        assert resp["type"] == "error"
        assert resp["code"] == "missing_call_params"

        await comm.disconnect()

    @asynctest
    async def test_call_answer_relays_to_peer(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.answer",
            "peer_id": "peer-1",
            "sdp": "v=0\r\ns=-",
        })
        await comm.disconnect()

    @asynctest
    async def test_call_answer_with_call_type(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.answer",
            "peer_id": "peer-1",
            "call_type": "video",
            "sdp": "v=0\r\ns=-",
        })
        await comm.disconnect()

    @asynctest
    async def test_call_ice_candidate_relays_to_peer(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.ice_candidate",
            "peer_id": "peer-1",
            "candidate": "candidate:1 1 UDP",
        })
        await comm.disconnect()

    @asynctest
    async def test_call_end_relays_to_peer(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.end",
            "peer_id": "peer-1",
            "reason": "user_hangup",
        })
        await comm.disconnect()

    @asynctest
    async def test_call_offer_not_allowed(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        monkeypatch.setattr(DirectChatConsumer, "_can_initiate_call", AsyncMock(return_value=False))
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.offer",
            "peer_id": "peer-1",
            "conversation_id": "conv-1",
            "sdp": "v=0",
        })
        resp = await comm.receive_json_from()
        assert resp["type"] == "error"
        assert resp["code"] == "call_not_allowed"

        await comm.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Video toggle during a call
# ─────────────────────────────────────────────────────────────────────────────


class TestVideoToggle:
    @asynctest
    async def test_video_toggle_enable(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.video_toggle",
            "peer_id": "peer-1",
            "enabled": True,
        })
        await comm.disconnect()

    @asynctest
    async def test_video_toggle_disable(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.video_toggle",
            "peer_id": "peer-1",
            "enabled": False,
        })
        await comm.disconnect()

    @asynctest
    async def test_video_toggle_missing_params(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "call.video_toggle", "peer_id": "peer-1"})
        resp = await comm.receive_json_from()
        assert resp["type"] == "error"
        assert resp["code"] == "missing_call_params"

        await comm.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Screen share during a call
# ─────────────────────────────────────────────────────────────────────────────


class TestScreenShare:
    @asynctest
    async def test_screen_share_start(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.screen_share",
            "peer_id": "peer-1",
            "sdp": "v=0\r\ns=-",
            "sharing": True,
        })
        await comm.disconnect()

    @asynctest
    async def test_screen_share_stop(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({
            "type": "call.screen_share",
            "peer_id": "peer-1",
            "sdp": "v=0\r\ns=-",
            "sharing": False,
        })
        await comm.disconnect()

    @asynctest
    async def test_screen_share_missing_params(self, user, monkeypatch):
        _patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(DirectChatConsumer.as_asgi(), "/ws/chat/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "call.screen_share", "peer_id": "peer-1"})
        resp = await comm.receive_json_from()
        assert resp["type"] == "error"
        assert resp["code"] == "missing_call_params"

        await comm.disconnect()
