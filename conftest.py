from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest


# Cache reset between tests — LocMem persists for the whole process.


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


# Outbound mail block. CELERY_TASK_ALWAYS_EAGER runs send_otp_email/
# send_welcome_email inline, and the Resend client talks HTTP directly rather
# than going through EMAIL_BACKEND — so locmem does not contain it. Without
# this, the suite posts to the live Resend API using the real key in the
# environment. Request `resend_outbox` to assert on what would have been sent.


class _FakeResendResponse:
    status_code = 200
    text = '{"id": "test-message-id"}'

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, str]:
        return {"id": "test-message-id"}


@pytest.fixture(autouse=True)
def resend_outbox(monkeypatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def _blocked_post(url, json=None, headers=None, timeout=None, **kwargs):
        sent.append(json or {})
        return _FakeResendResponse()

    monkeypatch.setattr("clients.resend.emails.requests.post", _blocked_post)
    return sent


# Fakes for service-layer interfaces.


# In-memory IRateLimiter for tests — no Redis, fully deterministic.
class FakeRateLimiter:

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.cooldowns: set[str] = set()

    def hit(self, key: str, *, limit: int, window: timedelta) -> tuple[bool, int]:
        self.counts[key] = self.counts.get(key, 0) + 1
        value = self.counts[key]
        return (value <= limit, value)

    def reset(self, key: str) -> None:
        self.counts.pop(key, None)

    def cooldown(self, key: str, *, ttl: timedelta) -> bool:
        return key in self.cooldowns

    def start_cooldown(self, key: str, *, ttl: timedelta) -> None:
        self.cooldowns.add(key)


# Always-acquire IDistributedLock — single-threaded tests don't race.
class FakeLock:

    def __init__(self, *, can_acquire: bool = True) -> None:
        self._can_acquire = can_acquire
        self.released: list[str] = []

    def acquire(self, key: str, *, ttl: timedelta) -> bool:
        return self._can_acquire

    def release(self, key: str) -> None:
        self.released.append(key)


# Captures notifications instead of sending them.
class FakeNotificationSender:

    def __init__(self) -> None:
        self.sent: list[Any] = []

    def send(self, payload) -> None:
        self.sent.append(payload)


@pytest.fixture
def fake_rate_limiter() -> FakeRateLimiter:
    return FakeRateLimiter()


@pytest.fixture
def fake_lock() -> FakeLock:
    return FakeLock()


@pytest.fixture
def fake_notifier() -> FakeNotificationSender:
    return FakeNotificationSender()


# DRF APIClient — convenience.


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()

