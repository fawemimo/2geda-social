from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from polls.consumers import PollConsumer, rate_limiter, VOTE_RATE_LIMIT
from polls.routing import websocket_urlpatterns

pytestmark = pytest.mark.django_db
asynctest = pytest.mark.asyncio

WS_APP = URLRouter(websocket_urlpatterns)
POLL_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def make_patch_consumer(monkeypatch, user_val, poll_id=POLL_ID):
    """Monkeypatch PollConsumer DB methods so WS tests don't touch real DB."""
    async def fake_auth(_self):
        return user_val

    async def fake_poll_exists(_self):
        return True

    monkeypatch.setattr(PollConsumer, "_authenticate", fake_auth)
    monkeypatch.setattr(PollConsumer, "_poll_exists", fake_poll_exists)
    monkeypatch.setattr(
        PollConsumer, "_get_options_data",
        AsyncMock(return_value=[{"id": "opt-1", "text": "A", "vote_count": 0, "position": 0}]),
    )
    monkeypatch.setattr(
        PollConsumer, "_cast_vote",
        AsyncMock(return_value={"options": [], "total_votes": 1}),
    )
    monkeypatch.setattr(
        PollConsumer, "_remove_vote",
        AsyncMock(return_value={"options": [], "total_votes": 0}),
    )


class TestPollConsumerConnect:
    @asynctest
    async def test_connect_sends_connected_event(self, user, monkeypatch):
        make_patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        connected, _ = await comm.connect()
        assert connected is True

        resp = await comm.receive_json_from()
        assert resp["type"] == "connected"
        assert resp["poll_id"] == POLL_ID
        assert resp["user_id"] == str(user.id)
        assert "options" in resp
        assert len(resp["options"]) == 1

        await comm.disconnect()

    @asynctest
    async def test_connect_no_auth_closes(self, monkeypatch):
        async def fake_auth(_self):
            return None

        monkeypatch.setattr(PollConsumer, "_authenticate", fake_auth)

        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        connected, _ = await comm.connect()
        assert connected is False

    @asynctest
    async def test_connect_poll_not_found_closes(self, user, monkeypatch):
        async def fake_auth(_self):
            return user

        async def fake_exists(_self):
            return False

        monkeypatch.setattr(PollConsumer, "_authenticate", fake_auth)
        monkeypatch.setattr(PollConsumer, "_poll_exists", fake_exists)

        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        connected, _ = await comm.connect()
        assert connected is False


class TestPollConsumerVote:
    @asynctest
    async def test_vote_sends_ack_and_broadcasts(self, user, monkeypatch):
        make_patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "vote", "option_id": "opt-1"})

        msgs = []
        for _ in range(2):
            msgs.append(await comm.receive_json_from())
        types = {m["type"] for m in msgs}
        assert "poll_event" in types
        assert "vote.ack" in types

        await comm.disconnect()

    @asynctest
    async def test_vote_rate_limited(self, user, monkeypatch):
        make_patch_consumer(monkeypatch, user)
        monkeypatch.setattr("polls.consumers.VOTE_RATE_LIMIT", 1)
        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        await comm.connect()
        await comm.receive_json_from()

        key = f"{user.id}:{POLL_ID}"
        rate_limiter.reset(key)

        await comm.send_json_to({"type": "vote", "option_id": "opt-1"})
        for _ in range(2):
            await comm.receive_json_from()

        await comm.send_json_to({"type": "vote", "option_id": "opt-1"})
        err = await comm.receive_json_from()
        assert err["type"] == "error"
        assert err["code"] == "rate_limited"

        await comm.disconnect()

    @asynctest
    async def test_vote_missing_option_id_returns_error(self, user, monkeypatch):
        make_patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "vote"})
        err = await comm.receive_json_from()
        assert err["type"] == "error"
        assert err["code"] == "missing_option_id"

        await comm.disconnect()


class TestPollConsumerUnvote:
    @asynctest
    async def test_unvote_rate_limited(self, user, monkeypatch):
        make_patch_consumer(monkeypatch, user)
        monkeypatch.setattr("polls.consumers.VOTE_RATE_LIMIT", 1)
        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        await comm.connect()
        await comm.receive_json_from()

        key = f"{user.id}:{POLL_ID}"
        rate_limiter.reset(key)

        await comm.send_json_to({"type": "unvote"})
        for _ in range(2):
            await comm.receive_json_from()

        await comm.send_json_to({"type": "unvote"})
        err = await comm.receive_json_from()
        assert err["type"] == "error"
        assert err["code"] == "rate_limited"

        await comm.disconnect()

    @asynctest
    async def test_unvote_sends_ack_and_broadcasts(self, user, monkeypatch):
        make_patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "unvote", "option_id": "opt-1"})

        ack = await comm.receive_json_from()
        assert ack["type"] == "unvote.ack"

        broadcast = await comm.receive_json_from()
        assert broadcast["type"] == "poll_event"
        assert broadcast["event"] == "vote.removed"

        await comm.disconnect()


class TestPollConsumerPing:
    @asynctest
    async def test_ping_pong(self, user, monkeypatch):
        make_patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "ping"})
        resp = await comm.receive_json_from()
        assert resp["type"] == "pong"

        await comm.disconnect()


class TestPollConsumerErrors:
    @asynctest
    async def test_unknown_type_returns_error(self, user, monkeypatch):
        make_patch_consumer(monkeypatch, user)
        comm = WebsocketCommunicator(WS_APP, f"/ws/polls/{POLL_ID}/")
        await comm.connect()
        await comm.receive_json_from()

        await comm.send_json_to({"type": "invalid_command"})
        err = await comm.receive_json_from()
        assert err["type"] == "error"
        assert err["code"] == "unknown_type"

        await comm.disconnect()
