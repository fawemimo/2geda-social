from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .cache import hashed_key, make_key

_redis_client: object | None = None


def _get_redis() -> object | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = cache.client.get_client()
        except Exception:
            return None
    return _redis_client


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
    raw_password: str | None = None
    referral_code: str | None = None
    code_hash: str = ""
    attempts: int = 0
    issued_at: datetime | None = None
    ip_address: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "email": self.email,
                "username": self.username,
                "phone_number": self.phone_number,
                "password_hash": self.password_hash,
                "raw_password": self.raw_password,
                "referral_code": self.referral_code,
                "code_hash": self.code_hash,
                "attempts": self.attempts,
                "issued_at": self.issued_at.isoformat() if self.issued_at else None,
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
            raw_password=data.get("raw_password"),
            referral_code=data.get("referral_code"),
            code_hash=data.get("code_hash", ""),
            attempts=data.get("attempts", 0),
            issued_at=datetime.fromisoformat(data["issued_at"]) if data.get("issued_at") else None,
            ip_address=data.get("ip_address"),
        )

# Encapsulates Redis IO for pending registrations.

class PendingRegistrationStore:

    def save(self, identifier: str, payload: PendingRegistration, *, ttl: timedelta) -> None:
        cache.set(_payload_key(identifier), payload.to_json(), timeout=ttl.total_seconds())

    def save_bulk(
        self,
        items: list[tuple[str, PendingRegistration, timedelta]],
    ) -> None:
        client = _get_redis()
        if client is not None and hasattr(client, "pipeline"):
            pipe = client.pipeline()
            for identifier, payload, ttl in items:
                pipe.set(
                    _payload_key(identifier),
                    payload.to_json(),
                    ex=int(ttl.total_seconds()),
                )
            pipe.execute()
        else:
            for identifier, payload, ttl in items:
                self.save(identifier, payload, ttl=ttl)

    def get(self, identifier: str) -> PendingRegistration | None:
        raw = cache.get(_payload_key(identifier))
        if raw is None:
            return None
        try:
            return PendingRegistration.from_json(raw)
        except (ValueError, KeyError, json.JSONDecodeError):
            cache.delete(_payload_key(identifier))
            return None

    def replace(self, identifier: str, payload: PendingRegistration, *, ttl: timedelta) -> None:
        self.save(identifier, payload, ttl=ttl)

    def delete(self, identifier: str) -> None:
        cache.delete(_payload_key(identifier))

    # ---- cooldown / quota helpers ----

    def is_on_cooldown(self, identifier: str) -> bool:
        return cache.get(_resend_cooldown_key(identifier)) is not None

    def start_cooldown(self, identifier: str, *, ttl: timedelta) -> None:
        cache.set(_resend_cooldown_key(identifier), 1, timeout=ttl.total_seconds())

    def hit_quota(self, identifier: str, *, limit: int) -> tuple[bool, int]:
        key = _daily_quota_key(identifier)
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

