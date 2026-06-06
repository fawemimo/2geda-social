from __future__ import annotations

from datetime import datetime, timezone as dt_tz
from unittest.mock import MagicMock

import pytest

from accounts.services.otp_generator import DjangoOTPHasher, SecureOTPGenerator
from accounts.services.pending_registration import (
    PendingRegistration,
    PendingRegistrationStore,
)


@pytest.fixture
def otp_generator() -> SecureOTPGenerator:
    return SecureOTPGenerator()


@pytest.fixture
def otp_hasher() -> DjangoOTPHasher:
    return DjangoOTPHasher()


# A real PendingRegistrationStore — backed by LocMem cache in tests.
@pytest.fixture
def pending_store() -> PendingRegistrationStore:
    return PendingRegistrationStore()


@pytest.fixture
def pending_payload(otp_hasher) -> PendingRegistration:
    return PendingRegistration(
        email="smithEze@example.com",
        username="smithEze",
        phone_number="+2348012345678",
        password_hash="hashed-password",
        referral_code=None,
        code_hash=otp_hasher.hash("123456"),
        attempts=0,
        issued_at=datetime(2026, 5, 23, 10, 0, tzinfo=dt_tz.utc),
        ip_address="203.0.113.42",
    )


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.pk = "0fb7a3a4-9b76-4f7c-a7c4-3f1d6b9c4e10"
    user.id = user.pk
    user.email = "smithEze@example.com"
    user.username = "smithEze"
    user.is_active = True
    user.is_deleted = False
    return user


# Replace `accounts.tasks.send_otp_email.delay` with a recorder.
@pytest.fixture
def mock_celery_send_otp_email(monkeypatch):
    from accounts import tasks

    calls: list[dict] = []

    def fake_delay(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(tasks.send_otp_email, "delay", fake_delay)
    return calls

