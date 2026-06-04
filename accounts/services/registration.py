from __future__ import annotations

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


def _domain_has_mx(domain: str) -> bool:
    import dns.exception
    import dns.resolver
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        return False
    except (dns.exception.Timeout, dns.resolver.LifetimeTimeout):
        return True


# Returned from `start_registration()` — no User created yet.
@dataclass(frozen=True, slots=True)
class RegistrationDraftResult:

    email: str | None
    phone_number: str | None
    otp_expires_at: object
    cooldown_until: object


@dataclass(frozen=True, slots=True)
class RegistrationCompleteResult:
    user_id: str
    email: str | None
    phone_number: str | None
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

    def _primary_identifier(self, *, email: str | None, phone_number: str | None) -> str:
        if email:
            return email.strip().lower()
        return phone_number.strip()  # type: ignore[return-value]

    def start_registration(
        self,
        *,
        email: str | None,
        username: str,
        password: str,
        phone_number: str | None = None,
        referral_code: str | None = None,
        ip_address: str | None = None,
    ) -> RegistrationDraftResult:
        email = self._normalize_email(email) if email else None
        username = self._normalize_username(username)
        self._validate_password(password)

        self._guard_existing_user(email=email, username=username, phone_number=phone_number)

        if referral_code:
            self._resolve_referrer(referral_code)

        identifier = self._primary_identifier(email=email, phone_number=phone_number)

        if self._store.is_on_cooldown(identifier):
            raise OTPCooldownError()
        allowed, _ = self._store.hit_quota(identifier, limit=self._daily_quota)
        if not allowed:
            raise OTPQuotaExceededError()

        code = self._generator.generate(self._code_length)
        code_hash = self._hasher.hash(code)

        payload = PendingRegistration(
            email=email or "",
            username=username,
            phone_number=phone_number or None,
            password_hash=make_password(password),
            referral_code=(referral_code or None) and referral_code.upper(),
            code_hash=code_hash,
            attempts=0,
            issued_at=timezone.now(),
            ip_address=ip_address,
        )
        self._store.save(identifier, payload, ttl=self._ttl)
        self._store.start_cooldown(identifier, ttl=self._cooldown)

        if email:
            logger.info(f"EMAIL OTP CODE IS {code} for email={email}")
            from accounts.tasks import send_otp_email as _send_otp_email
            _send_otp_email.delay(
                to=email,
                code=code,
                purpose=OTPPurpose.REGISTRATION.value,
                username=username,
            )
        else:
            logger.info(f"WHATSAPP OTP CODE IS {code} for phone={phone_number}")
            from accounts.tasks import send_otp_whatsapp as _send_otp_whatsapp
            _send_otp_whatsapp.delay(
                to=phone_number,
                code=code,
                purpose=OTPPurpose.REGISTRATION.value,
            )

        expires_at = payload.issued_at + self._ttl
        logger.info("Pending registration staged identifier=%s expires_at=%s", identifier, expires_at)
        return RegistrationDraftResult(
            email=email,
            phone_number=phone_number,
            otp_expires_at=expires_at,
            cooldown_until=payload.issued_at + self._cooldown,
        )

    def resend_registration_otp(self, *, email: str | None = None, phone_number: str | None = None) -> RegistrationDraftResult:
        identifier = self._primary_identifier(email=email, phone_number=phone_number)
        existing = self._store.get(identifier)
        if existing is None:
            raise NotFoundError(
                f"No pending registration found for {identifier}. Start over.",
                code="pending_registration_missing",
            )
        if self._store.is_on_cooldown(identifier):
            raise OTPCooldownError()
        allowed, _ = self._store.hit_quota(identifier, limit=self._daily_quota)
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
        self._store.replace(identifier, refreshed, ttl=self._ttl)
        self._store.start_cooldown(identifier, ttl=self._cooldown)

        if existing.email:
            from accounts.tasks import send_otp_email as _send_otp_email
            _send_otp_email.delay(
                to=existing.email,
                code=code,
                purpose=OTPPurpose.REGISTRATION.value,
                username=existing.username,
            )
        else:
            from accounts.tasks import send_otp_whatsapp as _send_otp_whatsapp
            _send_otp_whatsapp.delay(
                to=existing.phone_number,
                code=code,
                purpose=OTPPurpose.REGISTRATION.value,
            )

        expires_at = refreshed.issued_at + self._ttl
        return RegistrationDraftResult(
            email=existing.email or None,
            phone_number=existing.phone_number,
            otp_expires_at=expires_at,
            cooldown_until=refreshed.issued_at + self._cooldown,
        )

    def complete_registration(
        self,
        *,
        email: str | None = None,
        phone_number: str | None = None,
        code: str,
        device_id: str | None = None,
    ) -> RegistrationCompleteResult:
        identifier = self._primary_identifier(email=email, phone_number=phone_number)
        if not code or not code.isdigit():
            raise ValidationError("OTP code must be numeric.", code="otp_invalid_format")

        pending = self._store.get(identifier)
        if pending is None:
            raise OTPExpiredError(
                "Your registration session has expired. Start over.",
                code="pending_registration_missing",
            )

        if pending.attempts >= self._max_attempts:
            self._store.delete(identifier)
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
                self._store.delete(identifier)
                raise OTPExpiredError()
            self._store.replace(identifier, bumped, ttl=remaining_ttl)
            raise OTPInvalidError()

        user = self._persist_user(pending)
        self._store.delete(identifier)

        tokens = self._tokens.issue(user, device_id=device_id)
        logger.info("Registration completed user=%s identifier=%s", user.pk, identifier)

        return RegistrationCompleteResult(
            user_id=str(user.pk),
            email=user.email or None,
            phone_number=user.phone_number or None,
            access=tokens["access"],
            expires_at=tokens["access_expires_at"],
            refresh=tokens["refresh"],
        )

    @transaction.atomic
    def _persist_user(self, pending: PendingRegistration) -> User:
        referrer = self._resolve_referrer(pending.referral_code) if pending.referral_code else None

        try:
            user = User(
                email=pending.email or None,
                username=pending.username,
                phone_number=pending.phone_number or None,
                is_active=True,
                is_email_verified=bool(pending.email),
                is_phone_verified=bool(pending.phone_number and not pending.email),
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
    def _guard_existing_user(*, email: str | None, username: str, phone_number: str | None) -> None:
        qs = User.objects.filter(username=username)
        if email:
            qs = qs | User.objects.filter(email=email)
        if phone_number:
            qs = qs | User.objects.filter(phone_number=phone_number)
        if qs.only("id").exists():
            raise ConflictError(
                "An account already exists with the provided email, username, or phone.",
                code="account_exists",
            )

    @staticmethod
    def _normalize_email(email: str | None) -> str | None:
        if email is None:
            return None
        if "@" not in email:
            raise ValidationError("A valid email address is required.", code="email_required")
        normalized = email.strip().lower()
        domain = normalized.split("@")[1]
        if not _domain_has_mx(domain):
            raise ValidationError(
                f"The email domain '{domain}' does not accept email.",
                code="email_domain_invalid",
            )
        return normalized

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

