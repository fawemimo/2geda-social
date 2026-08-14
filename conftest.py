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
# send_welcome_email inline, and the email providers talk HTTP/boto directly
# rather than going through EMAIL_BACKEND — so locmem does not contain them.
# Without this the suite would post to the live provider using the real key in
# the environment.
#
# Rather than patching a specific provider's HTTP client, this substitutes the
# in-memory provider for every registered one: the swap the abstraction exists
# to make safe. Request `email_outbox` to assert on what would have been sent.


@pytest.fixture(autouse=True)
def email_outbox(monkeypatch):
    """Returns the MemoryProvider whose `.outbox` holds every EmailMessage."""
    from clients.email import registry
    from clients.email.providers.local import MemoryProvider

    provider = MemoryProvider()
    monkeypatch.setattr(registry, "get_provider", lambda name=None: provider)
    # The service imports get_provider by name, so patch that binding too.
    monkeypatch.setattr(
        "clients.email.service.get_provider", lambda name=None: provider
    )
    return provider


@pytest.fixture(autouse=True)
def sms_outbox(monkeypatch):
    """Blocks outbound SMS/WhatsApp for every provider.

    Same reasoning as `email_outbox`: eager Celery runs send_otp_sms and
    send_otp_whatsapp inline, and the providers talk HTTP directly. Substituting
    the in-memory provider keeps the suite off Twilio/Termii/EBulkSMS entirely.
    Returns the provider, so `sms_outbox.outbox` holds every Message.
    """
    from clients.messaging import registry
    from clients.messaging.providers.local import MemoryProvider

    provider = MemoryProvider()
    monkeypatch.setattr(registry, "get_messaging_provider", lambda channel=None: provider)
    monkeypatch.setattr(
        "clients.messaging.service.get_messaging_provider",
        lambda channel=None: provider,
    )
    return provider


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

