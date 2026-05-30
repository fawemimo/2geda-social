from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from .cache import hashed_key, make_key


logger = logging.getLogger(__name__)


def _payload_key(email: str) -> str:
    return make_key("pending_registration", hashed_key(email.lower()))


def _resend_cooldown_key(email: str) -> str:
    return make_key("pending_registration", "cooldown", hashed_key(email.lower()))


def _daily_quota_key(email: str) -> str:
    return make_key("pending_registration", "quota", hashed_key(email.lower()))


@dataclass(frozen=True, slots=True)
class PendingRegistration:
    email: str
    username: str
    phone_number: str | None
    password_hash: str
    referral_code: str | None
    code_hash: str
    attempts: int
    issued_at: datetime
    ip_address: str | None

    def to_json(self) -> str:
        return json.dumps(
            {
                "email": self.email,
                "username": self.username,
                "phone_number": self.phone_number,
                "password_hash": self.password_hash,
                "referral_code": self.referral_code,
                "code_hash": self.code_hash,
                "attempts": self.attempts,
                "issued_at": self.issued_at.isoformat(),
                "ip_address": self.ip_address,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "PendingRegistration":
        data = json.loads(raw)
        return cls(
            email=data["email"],
            username=data["username"],
            phone_number=data.get("phone_number"),
            password_hash=data["password_hash"],
            referral_code=data.get("referral_code"),
            code_hash=data["code_hash"],
            attempts=data.get("attempts", 0),
            issued_at=datetime.fromisoformat(data["issued_at"]),
            ip_address=data.get("ip_address"),
        )

# Encapsulates Redis IO for pending registrations.

class PendingRegistrationStore:

    def save(self, payload: PendingRegistration, *, ttl: timedelta) -> None:
        cache.set(_payload_key(payload.email), payload.to_json(), timeout=ttl.total_seconds())

    def get(self, email: str) -> PendingRegistration | None:
        raw = cache.get(_payload_key(email))
        if raw is None:
            return None
        try:
            return PendingRegistration.from_json(raw)
        except (ValueError, KeyError, json.JSONDecodeError):
            cache.delete(_payload_key(email))
            return None

    def replace(self, payload: PendingRegistration, *, ttl: timedelta) -> None:
        self.save(payload, ttl=ttl)

    def delete(self, email: str) -> None:
        cache.delete(_payload_key(email))

    # ---- cooldown / quota helpers ----

    def is_on_cooldown(self, email: str) -> bool:
        return cache.get(_resend_cooldown_key(email)) is not None

    def start_cooldown(self, email: str, *, ttl: timedelta) -> None:
        cache.set(_resend_cooldown_key(email), 1, timeout=ttl.total_seconds())

    def hit_quota(self, email: str, *, limit: int) -> tuple[bool, int]:
        key = _daily_quota_key(email)
        try:
            value = cache.incr(key)
        except ValueError:
            value = None

        if value is None:
            value = 1
            cache.set(key, value, timeout=timedelta(days=1).total_seconds())

        return (value <= limit, value)


def now() -> datetime:
    return timezone.now()

