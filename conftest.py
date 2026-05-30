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

