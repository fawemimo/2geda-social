from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from polls.enums import PollStatus, PollType
from polls.models import Poll, PollOption


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(
        email="pollowner@test.com",
        username="pollowner",
        password="pass123",
        is_active=True,
    )


@pytest.fixture
def other_user(db) -> User:
    return User.objects.create_user(
        email="other@test.com",
        username="otheruser",
        password="pass123",
        is_active=True,
    )


@pytest.fixture
def voter(db) -> User:
    return User.objects.create_user(
        email="voter@test.com",
        username="votertest",
        password="pass123",
        is_active=True,
    )


@pytest.fixture
def auth_client(api_client, user) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def other_auth_client(api_client, other_user) -> APIClient:
    api_client.force_authenticate(user=other_user)
    return api_client


@pytest.fixture
def voter_auth_client(api_client, voter) -> APIClient:
    api_client.force_authenticate(user=voter)
    return api_client


@pytest.fixture
def poll(user) -> Poll:
    p = Poll.objects.create(
        author=user,
        question="Favorite color?",
        poll_type=PollType.SINGLE_CHOICE.value,
        ends_at=timezone.now() + timezone.timedelta(hours=24),
    )
    PollOption.objects.create(poll=p, text="Red", position=0)
    PollOption.objects.create(poll=p, text="Blue", position=1)
    PollOption.objects.create(poll=p, text="Green", position=2)
    Poll.objects.filter(pk=p.pk).update(options_count=3)
    return p


@pytest.fixture
def multi_choice_poll(user) -> Poll:
    p = Poll.objects.create(
        author=user,
        question="Pick toppings?",
        poll_type=PollType.MULTIPLE_CHOICE.value,
        ends_at=timezone.now() + timezone.timedelta(hours=24),
    )
    PollOption.objects.create(poll=p, text="Cheese", position=0)
    PollOption.objects.create(poll=p, text="Pepperoni", position=1)
    PollOption.objects.create(poll=p, text="Mushrooms", position=2)
    Poll.objects.filter(pk=p.pk).update(options_count=3)
    return p


@pytest.fixture
def expired_poll(user) -> Poll:
    p = Poll.objects.create(
        author=user,
        question="Expired?",
        poll_type=PollType.SINGLE_CHOICE.value,
        ends_at=timezone.now() - timezone.timedelta(hours=1),
    )
    PollOption.objects.create(poll=p, text="Yes", position=0)
    PollOption.objects.create(poll=p, text="No", position=1)
    Poll.objects.filter(pk=p.pk).update(options_count=2)
    return p


@pytest.fixture
def closed_poll(user) -> Poll:
    p = Poll.objects.create(
        author=user,
        question="Closed?",
        poll_type=PollType.SINGLE_CHOICE.value,
        status=PollStatus.CLOSED.value,
        ends_at=timezone.now() - timezone.timedelta(hours=1),
    )
    PollOption.objects.create(poll=p, text="A", position=0)
    PollOption.objects.create(poll=p, text="B", position=1)
    Poll.objects.filter(pk=p.pk).update(options_count=2)
    return p


#
#  WebSocket test helpers
#

def make_patch_consumer(monkeypatch, user_val, poll_id="poll-1"):
    """Monkeypatch PollConsumer DB methods so WS tests don't touch real DB."""
    from polls.consumers import PollConsumer

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
