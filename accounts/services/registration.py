from __future__ import annotations

from asyncio import tasks
import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User, UserProfile
from utils.enum import OTPPurpose, PointRewardingMaps

from .exceptions import (
    ConflictError,
    NotFoundError,
    OTPCooldownError,
    OTPExpiredError,
    OTPInvalidError,
    OTPMaxAttemptsError,
    OTPQuotaExceededError,
    ValidationError,
)
from .otp_generator import DjangoOTPHasher, SecureOTPGenerator
from .pending_registration import (
    PendingRegistration,
    PendingRegistrationStore,
)
from .tokens import TokenService


logger = logging.getLogger(__name__)


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,40}$")


# Returned from `start_registration()` — no User created yet.
@dataclass(frozen=True, slots=True)
class RegistrationDraftResult:

    email: str
    otp_expires_at: object
    cooldown_until: object


@dataclass(frozen=True, slots=True)
class RegistrationCompleteResult:
    user_id: str
    email: str
    access: str
    refresh: str
    expires_at: int

# Two-phase registration:

class RegistrationService:

    def __init__(
        self,
        *,
        store: PendingRegistrationStore | None = None,
        generator: SecureOTPGenerator | None = None,
        hasher: DjangoOTPHasher | None = None,
        token_service: TokenService | None = None,
    ) -> None:
        self._store = store or PendingRegistrationStore()
        self._generator = generator or SecureOTPGenerator()
        self._hasher = hasher or DjangoOTPHasher()
        self._tokens = token_service or TokenService()

        self._ttl = timedelta(seconds=getattr(settings, "OTP_TTL_SECONDS", 600))
        self._cooldown = timedelta(seconds=getattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 60))
        self._max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
        self._code_length = getattr(settings, "OTP_CODE_LENGTH", 6)
        self._daily_quota = getattr(settings, "OTP_DAILY_QUOTA", 20)

    def start_registration(
        self,
        *,
        email: str,
        username: str,
        password: str,
        phone_number: str | None = None,
        referral_code: str | None = None,
        ip_address: str | None = None,
    ) -> RegistrationDraftResult:
        email = self._normalize_email(email)
        username = self._normalize_username(username)
        self._validate_password(password)

        # Reject obvious clashes early — without hitting Postgres twice for
        # the same column we have a unique constraint on.
        self._guard_existing_user(email=email, username=username, phone_number=phone_number)

        if referral_code:
            # Validate the referrer exists; we don't persist it on the
            # pending payload, just check up-front so registration can fail fast.
            self._resolve_referrer(referral_code)

        if self._store.is_on_cooldown(email):
            raise OTPCooldownError()
        allowed, _ = self._store.hit_quota(email, limit=self._daily_quota)
        if not allowed:
            raise OTPQuotaExceededError()

        code = self._generator.generate(self._code_length)
        code_hash = self._hasher.hash(code)

        payload = PendingRegistration(
            email=email,
            username=username,
            phone_number=phone_number or None,
            password_hash=make_password(password),
            referral_code=(referral_code or None) and referral_code.upper(),
            code_hash=code_hash,
            attempts=0,
            issued_at=timezone.now(),
            ip_address=ip_address,
        )
        self._store.save(payload, ttl=self._ttl)
        self._store.start_cooldown(email, ttl=self._cooldown)

        from accounts.tasks import send_otp_email as _send_otp_email
        _send_otp_email.delay(
            to=email,
            code=code,
            purpose=OTPPurpose.REGISTRATION.value,
            username=username,
        )

        expires_at = payload.issued_at + self._ttl
        logger.info("Pending registration staged email=%s expires_at=%s", email, expires_at)
        return RegistrationDraftResult(
            email=email,
            otp_expires_at=expires_at,
            cooldown_until=payload.issued_at + self._cooldown,
        )

    def resend_registration_otp(self, *, email: str) -> RegistrationDraftResult:
        email = self._normalize_email(email)
        existing = self._store.get(email)
        if existing is None:
            raise NotFoundError(
                "No pending registration found for this email. Start over.",
                code="pending_registration_missing",
            )
        if self._store.is_on_cooldown(email):
            raise OTPCooldownError()
        allowed, _ = self._store.hit_quota(email, limit=self._daily_quota)
        if not allowed:
            raise OTPQuotaExceededError()

        code = self._generator.generate(self._code_length)
        refreshed = PendingRegistration(
            email=existing.email,
            username=existing.username,
            phone_number=existing.phone_number,
            password_hash=existing.password_hash,
            referral_code=existing.referral_code,
            code_hash=self._hasher.hash(code),
            attempts=0,
            issued_at=timezone.now(),
            ip_address=existing.ip_address,
        )
        self._store.replace(refreshed, ttl=self._ttl)
        self._store.start_cooldown(email, ttl=self._cooldown)

        tasks.send_otp_email.delay(
            to=email,
            code=code,
            purpose=OTPPurpose.REGISTRATION.value,
            username=existing.username,
        )
        expires_at = refreshed.issued_at + self._ttl
        return RegistrationDraftResult(
            email=email,
            otp_expires_at=expires_at,
            cooldown_until=refreshed.issued_at + self._cooldown,
        )

    def complete_registration(
        self,
        *,
        email: str,
        code: str,
        device_id: str | None = None,
    ) -> RegistrationCompleteResult:
        email = self._normalize_email(email)
        if not code or not code.isdigit():
            raise ValidationError("OTP code must be numeric.", code="otp_invalid_format")

        pending = self._store.get(email)
        if pending is None:
            raise OTPExpiredError(
                "Your registration session has expired. Start over.",
                code="pending_registration_missing",
            )

        if pending.attempts >= self._max_attempts:
            self._store.delete(email)
            raise OTPMaxAttemptsError()

        if not self._hasher.verify(code, pending.code_hash):
            bumped = PendingRegistration(
                email=pending.email,
                username=pending.username,
                phone_number=pending.phone_number,
                password_hash=pending.password_hash,
                referral_code=pending.referral_code,
                code_hash=pending.code_hash,
                attempts=pending.attempts + 1,
                issued_at=pending.issued_at,
                ip_address=pending.ip_address,
            )
            remaining_ttl = self._remaining_ttl(pending.issued_at)
            if remaining_ttl <= timedelta(0):
                self._store.delete(email)
                raise OTPExpiredError()
            self._store.replace(bumped, ttl=remaining_ttl)
            raise OTPInvalidError()

        user = self._persist_user(pending)
        self._store.delete(email)

        tokens = self._tokens.issue(user, device_id=device_id)
        logger.info("Registration completed user=%s email=%s", user.pk, email)

        return RegistrationCompleteResult(
            user_id=str(user.pk),
            email=user.email,
            access=tokens["access"],
            expires_at=tokens["access_expires_at"],
            refresh=tokens["refresh"],
        )

    @transaction.atomic
    def _persist_user(self, pending: PendingRegistration) -> User:
        referrer = self._resolve_referrer(pending.referral_code) if pending.referral_code else None

        try:
            user = User(
                email=pending.email,
                username=pending.username,
                phone_number=pending.phone_number,
                is_active=True,
                is_email_verified=True,
                referred_by=referrer,
            )
            user.password = pending.password_hash
            user.save()
        except IntegrityError as exc:
            raise ConflictError(
                "An account already exists with the provided email, username, or phone.",
                code="account_exists",
            ) from exc

        UserProfile.objects.get_or_create(user=user)

        if referrer:
            from accounts.models import Referral
            Referral.objects.get_or_create(referrer=referrer, referred_user=user)

            from accounts.services.rewards import reward_user
            reward_user(
                user=referrer,
                points=PointRewardingMaps.REFFERAL.value,
                action="referral",
                source=user,
                auto_claim=True
            )

        return user

    def _remaining_ttl(self, issued_at) -> timedelta:
        return (issued_at + self._ttl) - timezone.now()

    @staticmethod
    def _guard_existing_user(*, email: str, username: str, phone_number: str | None) -> None:
        qs = User.objects.filter(email=email) | User.objects.filter(username=username)
        if phone_number:
            qs = qs | User.objects.filter(phone_number=phone_number)
        if qs.only("id").exists():
            raise ConflictError(
                "An account already exists with the provided email, username, or phone.",
                code="account_exists",
            )

    @staticmethod
    def _normalize_email(email: str) -> str:
        if not email or "@" not in email:
            raise ValidationError("A valid email address is required.", code="email_required")
        return email.strip().lower()

    @staticmethod
    def _normalize_username(username: str) -> str:
        if not username or not USERNAME_RE.match(username):
            raise ValidationError(
                "Username must be 3-40 chars, alphanumeric + underscores only.",
                code="username_invalid",
            )
        return username.strip()

    @staticmethod
    def _validate_password(password: str) -> None:
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise ValidationError("; ".join(exc.messages), code="password_weak") from exc

    @staticmethod
    def _resolve_referrer(referral_code: str):
        try:
            return User.objects.only("id").get(referral_code=referral_code.upper())
        except User.DoesNotExist as exc:
            raise NotFoundError(
                "Referral code does not match any user.", code="referrer_not_found"
            ) from exc

