from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone

from polls.enums import PollStatus
from polls.models import Poll, PollOption

pytestmark = pytest.mark.django_db


class TestCloseExpiredPollsTask:
    def test_closes_expired_polls(self):
        now = timezone.now()
        poll = Poll.objects.create(
            author_id=self._create_user(),
            question="Expired?",
            status=PollStatus.ACTIVE.value,
            ends_at=now - timezone.timedelta(hours=1),
        )
        PollOption.objects.create(poll=poll, text="Yes", position=0)
        PollOption.objects.create(poll=poll, text="No", position=1)
        Poll.objects.filter(pk=poll.pk).update(options_count=2)

        with patch("polls.services.broadcaster.broadcast_poll_event"):
            from polls.tasks import close_expired_polls
            result = close_expired_polls()

        assert result["closed_count"] >= 1
        poll.refresh_from_db()
        assert poll.status == PollStatus.CLOSED.value

    def test_skips_active_polls(self):
        now = timezone.now()
        poll = Poll.objects.create(
            author_id=self._create_user(),
            question="Still active?",
            status=PollStatus.ACTIVE.value,
            ends_at=now + timezone.timedelta(hours=24),
        )
        PollOption.objects.create(poll=poll, text="Yes", position=0)
        PollOption.objects.create(poll=poll, text="No", position=1)
        Poll.objects.filter(pk=poll.pk).update(options_count=2)

        with patch("polls.services.broadcaster.broadcast_poll_event"):
            from polls.tasks import close_expired_polls
            result = close_expired_polls()

        assert result["closed_count"] == 0
        poll.refresh_from_db()
        assert poll.status == PollStatus.ACTIVE.value

    def test_skips_already_closed_polls(self):
        now = timezone.now()
        poll = Poll.objects.create(
            author_id=self._create_user(),
            question="Already closed?",
            status=PollStatus.CLOSED.value,
            ends_at=now - timezone.timedelta(hours=1),
        )
        PollOption.objects.create(poll=poll, text="Yes", position=0)
        PollOption.objects.create(poll=poll, text="No", position=1)
        Poll.objects.filter(pk=poll.pk).update(options_count=2)

        with patch("polls.services.broadcaster.broadcast_poll_event"):
            from polls.tasks import close_expired_polls
            result = close_expired_polls()

        assert result["closed_count"] == 0
        poll.refresh_from_db()
        assert poll.status == PollStatus.CLOSED.value

    def test_broadcasts_closed_event(self):
        now = timezone.now()
        poll = Poll.objects.create(
            author_id=self._create_user(),
            question="Broadcast?",
            status=PollStatus.ACTIVE.value,
            ends_at=now - timezone.timedelta(hours=1),
        )
        PollOption.objects.create(poll=poll, text="A", position=0)
        PollOption.objects.create(poll=poll, text="B", position=1)
        Poll.objects.filter(pk=poll.pk).update(options_count=2)

        with patch("polls.services.broadcaster.broadcast_poll_event") as mock_broadcast:
            from polls.tasks import close_expired_polls
            close_expired_polls()

        mock_broadcast.assert_called_once()
        args, kwargs = mock_broadcast.call_args
        assert args[1]["event"] == "poll.closed"
        assert args[1]["poll_id"] == str(poll.pk)

    def test_no_expired_returns_zero(self):
        with patch("polls.services.broadcaster.broadcast_poll_event"):
            from polls.tasks import close_expired_polls
            result = close_expired_polls()

        assert result == {"closed_count": 0}

    def _create_user(self):
        from accounts.models import User
        return User.objects.create_user(
            email=f"taskuser{timezone.now().timestamp()}@test.com",
            username=f"taskuser{timezone.now().timestamp()}",
            password="pass123",
            is_active=True,
        ).pk
