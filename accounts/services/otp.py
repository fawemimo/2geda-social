from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import OTP, User
from utils.enum import OTPChannel, OTPPurpose

from .cache import hashed_key, make_key
from .exceptions import (
    OTPCooldownError,
    OTPExpiredError,
    OTPInvalidError,
    OTPMaxAttemptsError,
    OTPQuotaExceededError,
    ValidationError,
)
from .interfaces import IDistributedLock, IOTPGenerator, IOTPHasher, IRateLimiter
from .otp_generator import DjangoOTPHasher, SecureOTPGenerator
from .rate_limiter import RedisDistributedLock, RedisRateLimiter


logger = logging.getLogger(__name__)


# Returned from `issue()` — never carries the plaintext code outside the service.
@dataclass(frozen=True, slots=True)
class IssuedOTP:

    otp_id: str
    code: str
    delivery_address: str
    purpose: str
    channel: str
    expires_at: object

# Owns the OTP lifecycle for any purpose (registration, login, password reset, ...).

class OTPService:

    def __init__(
        self,
        *,
        generator: IOTPGenerator | None = None,
        hasher: IOTPHasher | None = None,
        rate_limiter: IRateLimiter | None = None,
        lock: IDistributedLock | None = None,
    ) -> None:
        self._generator = generator or SecureOTPGenerator()
        self._hasher = hasher or DjangoOTPHasher()
        self._rate_limiter = rate_limiter or RedisRateLimiter(namespace="otp")
        self._lock = lock or RedisDistributedLock(namespace="otp")

        self._length: int = getattr(settings, "OTP_CODE_LENGTH", 6)
        self._ttl: int = getattr(settings, "OTP_TTL_SECONDS", 600)
        self._max_attempts: int = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
        self._cooldown: int = getattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 60)
        self._daily_quota: int = getattr(settings, "OTP_DAILY_QUOTA", 20)

    # public API 

# Generate a fresh OTP, invalidate older ones, persist hashed.
    @transaction.atomic
    def issue(
        self,
        *,
        user: User,
        purpose: str,
        delivery_address: str,
        channel: str = OTPChannel.EMAIL.value,
        ip_address: str | None = None,
    ) -> IssuedOTP:
        self._guard_quota(user_id=str(user.pk), purpose=purpose)
        self._guard_cooldown(user_id=str(user.pk), purpose=purpose)

        # Invalidate prior unused OTPs for same (user, purpose) so a stale
        # code in a forgotten email can't be used after a new one is sent.
        OTP.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)

        code = self._generator.generate(self._length)
        record = OTP.objects.create(
            user=user,
            code_hash=self._hasher.hash(code),
            purpose=purpose,
            channel=channel,
            delivery_address=delivery_address,
            expires_at=timezone.now() + timedelta(seconds=self._ttl),
            ip_address=ip_address,
        )
        self._start_cooldown(user_id=str(user.pk), purpose=purpose)
        self._reset_attempts(otp_id=str(record.pk))

        logger.info(
            "OTP issued user=%s purpose=%s channel=%s expires_at=%s",
            user.pk, purpose, channel, record.expires_at,
        )
        return IssuedOTP(
            otp_id=str(record.pk),
            code=code,
            delivery_address=delivery_address,
            purpose=purpose,
            channel=channel,
            expires_at=record.expires_at,
        )
# Locked, single-pass verification. Returns the OTP row on success

    def verify(self, *, user: User, purpose: str, code: str) -> OTP:
        if not code or not code.isdigit():
            raise ValidationError("OTP code must be numeric.", code="otp_invalid_format")

        lock_key = f"verify:{user.pk}:{purpose}"
        if not self._lock.acquire(lock_key, ttl=timedelta(seconds=10)):
            raise OTPCooldownError("Another verification is in progress.")
        try:
            return self._verify_locked(user=user, purpose=purpose, code=code)
        finally:
            self._lock.release(lock_key)

    # internals ----------

    def _verify_locked(self, *, user: User, purpose: str, code: str) -> OTP:
        record = (
            OTP.objects.select_for_update(skip_locked=False)
            .filter(user=user, purpose=purpose, is_used=False)
            .order_by("-created_at")
            .first()
        )
        if record is None:
            raise OTPInvalidError()
        if record.expires_at <= timezone.now():
            raise OTPExpiredError()

        attempts_key = make_key("otp", "attempts", str(record.pk))
        attempts = self._rate_limiter.hit(
            attempts_key, limit=self._max_attempts, window=timedelta(seconds=self._ttl)
        )
        if not attempts[0]:
            OTP.objects.filter(pk=record.pk).update(is_used=True, attempt_count=attempts[1])
            raise OTPMaxAttemptsError()

        if not self._hasher.verify(code, record.code_hash):
            OTP.objects.filter(pk=record.pk).update(attempt_count=attempts[1])
            raise OTPInvalidError()

        # Mark used in a single UPDATE so it's safe under concurrent verifies.
        updated = OTP.objects.filter(pk=record.pk, is_used=False).update(
            is_used=True, attempt_count=attempts[1]
        )
        if updated == 0:
            raise OTPInvalidError("OTP already consumed.")

        record.is_used = True
        record.attempt_count = attempts[1]
        return record

    def _guard_quota(self, *, user_id: str, purpose: str) -> None:
        key = f"quota:{user_id}:{purpose}"
        allowed, _ = self._rate_limiter.hit(key, limit=self._daily_quota, window=timedelta(days=1))
        if not allowed:
            raise OTPQuotaExceededError()

    def _guard_cooldown(self, *, user_id: str, purpose: str) -> None:
        key = f"cooldown:{user_id}:{purpose}"
        if self._rate_limiter.cooldown(key, ttl=timedelta(seconds=self._cooldown)):
            raise OTPCooldownError()

    def _start_cooldown(self, *, user_id: str, purpose: str) -> None:
        key = f"cooldown:{user_id}:{purpose}"
        self._rate_limiter.start_cooldown(key, ttl=timedelta(seconds=self._cooldown))

    def _reset_attempts(self, *, otp_id: str) -> None:
        self._rate_limiter.reset(make_key("otp", "attempts", otp_id))

