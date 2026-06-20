from __future__ import annotations

import logging
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from polls.models import Poll
from polls.services.broadcaster import async_broadcast_poll_event
from polls.services.exceptions import ServiceError
from polls.services.rate_limiter import WebSocketRateLimiter

logger = logging.getLogger(__name__)

User = get_user_model()

VOTE_RATE_LIMIT = 30
VOTE_RATE_WINDOW = timedelta(minutes=1)

rate_limiter = WebSocketRateLimiter()


class PollConsumer(AsyncJsonWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.poll_id: str | None = None
        self._group_name: str | None = None

    @property
    def group_name(self) -> str:
        if self._group_name is None:
            self._group_name = f"poll_{self.poll_id}"
        return self._group_name

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close()
            return

        self.poll_id = self.scope["url_route"]["kwargs"]["poll_id"]
        poll_exists = await self._poll_exists()
        if not poll_exists:
            await self.close()
            return

        await self.accept()
        logger.info("Poll WS connected user=%s poll=%s", self.user.id, self.poll_id)

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        options_data = await self._get_options_data()
        await self.send_json({
            "type": "connected",
            "poll_id": self.poll_id,
            "user_id": str(self.user.id),
            "options": options_data,
        })

    async def disconnect(self, close_code):
        if self.poll_id and self.user:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )
            logger.info(
                "Poll WS disconnected user=%s poll=%s code=%s",
                self.user.id, self.poll_id, close_code,
            )

    async def receive_json(self, content: dict):
        msg_type = content.get("type")
        handler = {
            "vote": self._handle_vote,
            "unvote": self._handle_unvote,
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

    async def _handle_vote(self, content: dict):
        if not await self._check_rate_limit():
            return

        option_id = content.get("option_id")
        if not option_id:
            return await self._error("missing_option_id")

        try:
            result = await self._cast_vote(option_id=str(option_id))
            payload = {
                "event": "vote.update",
                "poll_id": self.poll_id,
                "option_id": option_id,
                "voter_id": str(self.user.id),
                "options": result["options"],
                "total_votes": result["total_votes"],
            }
            await async_broadcast_poll_event(self.poll_id, payload)
            await self.send_json({"type": "vote.ack", **payload})
        except ServiceError as e:
            await self._error(e.code, e.message)

    async def _handle_unvote(self, content: dict):
        if not await self._check_rate_limit():
            return

        option_id = content.get("option_id")

        try:
            result = await self._remove_vote(
                option_id=str(option_id) if option_id else None,
            )
            if result:
                payload = {
                    "event": "vote.removed",
                    "poll_id": self.poll_id,
                    "option_id": option_id,
                    "voter_id": str(self.user.id),
                    "options": result["options"],
                    "total_votes": result["total_votes"],
                }
                await async_broadcast_poll_event(self.poll_id, payload)
            await self.send_json({"type": "unvote.ack"})
        except ServiceError as e:
            await self._error(e.code, e.message)

    async def _handle_ping(self, content: dict):
        await self.send_json({"type": "pong"})

    async def _check_rate_limit(self) -> bool:
        key = f"{self.user.id}:{self.poll_id}"
        allowed, _ = rate_limiter.hit(
            key, limit=VOTE_RATE_LIMIT, window=VOTE_RATE_WINDOW,
        )
        if not allowed:
            await self.send_json({
                "type": "error",
                "code": "rate_limited",
                "message": "Too many requests. Please slow down.",
            })
        return allowed

    async def poll_event(self, event: dict):
        await self.send_json(event)

    async def _error(self, code: str, message: str | None = None) -> None:
        await self.send_json({"type": "error", "code": code, "message": message or code})

    @database_sync_to_async
    def _poll_exists(self) -> bool:
        return Poll.objects.filter(pk=self.poll_id, is_deleted=False).exists()

    @database_sync_to_async
    def _get_options_data(self) -> list[dict]:
        from polls.services.poll_service import PollService
        try:
            poll = Poll.objects.get(pk=self.poll_id, is_deleted=False)
            return PollService.get_options_data(poll)
        except Poll.DoesNotExist:
            return []

    @database_sync_to_async
    def _cast_vote(self, option_id: str) -> dict:
        from polls.services.poll_service import PollService

        poll = Poll.objects.get(pk=self.poll_id, is_deleted=False)
        PollService.cast_vote(poll=poll, option_id=option_id, voter=self.user)

        poll.refresh_from_db()
        return {
            "options": PollService.get_options_data(poll),
            "total_votes": poll.total_votes,
        }

    @database_sync_to_async
    def _remove_vote(self, option_id: str | None) -> dict | None:
        from polls.services.poll_service import PollService

        poll = Poll.objects.get(pk=self.poll_id, is_deleted=False)

        if option_id:
            PollService.remove_option_vote(poll=poll, option_id=option_id, voter=self.user)
        else:
            PollService.remove_vote(poll=poll, voter=self.user)

        poll.refresh_from_db()
        return {
            "options": PollService.get_options_data(poll),
            "total_votes": poll.total_votes,
        }

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
