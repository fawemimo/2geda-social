from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.utils import timezone

from accounts.models import User, UserDevice

from .exceptions import (
    AccountInactiveError,
    AccountLockedError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
)
from .interfaces import IRateLimiter
from .otp import OTPService
from .rate_limiter import RedisRateLimiter
from .tokens import TokenService


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LoginResult:
    user_id: str
    access: str
    access_expires_at: int
    refresh: str
    refresh_expires_at: int
    device_id: str | None


class AuthenticationService:
    def __init__(
        self,
        *,
        token_service: TokenService | None = None,
        otp_service: OTPService | None = None,
        rate_limiter: IRateLimiter | None = None,
    ) -> None:
        self._tokens = token_service or TokenService()
        self._otp = otp_service or OTPService()
        self._rate_limiter = rate_limiter or RedisRateLimiter(namespace="auth")

        self._max_failed = getattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 10)
        self._lockout_seconds = getattr(settings, "LOGIN_LOCKOUT_SECONDS", 900)

    #  login

    def login(
        self,
        *,
        email: str,
        password: str,
        device_payload: dict | None = None,
        ip_address: str | None = None,
    ) -> LoginResult:
        email = email.strip().lower() if email else ""
        if not email or not password:
            raise ValidationError("Email and password are required.", code="credentials_required")

        lockout_key = f"login:{email}"
        if self._rate_limiter.cooldown(lockout_key, ttl=timedelta(seconds=self._lockout_seconds)):
            raise AccountLockedError()

        user = authenticate(email=email, password=password)
        if user is None:
            allowed, count = self._rate_limiter.hit(
                lockout_key,
                limit=self._max_failed,
                window=timedelta(seconds=self._lockout_seconds),
            )
            logger.info("Failed login email=%s attempt=%s", email, count)
            if not allowed:
                self._rate_limiter.start_cooldown(
                    lockout_key, ttl=timedelta(seconds=self._lockout_seconds)
                )
                raise AccountLockedError()
            raise AuthenticationError("Invalid email or password.")

        if not user.is_active:
            raise AccountInactiveError()
        if user.is_deleted:
            raise AuthenticationError("This account has been deactivated.")

        self._rate_limiter.reset(lockout_key)

        device = self._register_or_update_device(user=user, payload=device_payload, ip_address=ip_address)
        tokens = self._tokens.issue(user, device_id=device.pk if device else None)

        return LoginResult(
            user_id=str(user.pk),
            access=tokens["access"],
            access_expires_at=tokens["access_expires_at"],
            refresh=tokens["refresh"],
            refresh_expires_at=tokens["refresh_expires_at"],
            device_id=str(device.pk) if device else None,
        )

    #  logout

    def logout(self, *, refresh_token: str) -> None:
        if not refresh_token:
            raise ValidationError("Refresh token is required.", code="refresh_required")
        self._tokens.revoke(refresh_token)

    def logout_everywhere(self, *, user: User) -> int:
        count = self._tokens.revoke_all_for_user(user)
        UserDevice.objects.filter(user=user, is_deleted=False).update(
            push_token="", is_trusted=False, is_deleted=True, deleted_at=timezone.now()
        )
        return count

    #  helpers

    @staticmethod
    def _get_user_by_email(email: str) -> User:
        try:
            return User.objects.get(email=email.strip().lower())
        except User.DoesNotExist as exc:
            raise NotFoundError("No account found for this email.", code="user_not_found") from exc

    def _register_or_update_device(
        self,
        *,
        user: User,
        payload: dict | None,
        ip_address: str | None = None,
    ) -> UserDevice | None:
        if not payload:
            return None
        fingerprint = payload.get("device_fingerprint")
        platform = payload.get("platform")
        if not fingerprint or not platform:
            return None

        defaults = {
            "name": payload.get("name", "") or "",
            "platform": platform,
            "os_version": payload.get("os_version", "") or "",
            "app_version": payload.get("app_version", "") or "",
            "push_token": payload.get("push_token", "") or "",
            "push_token_updated_at": timezone.now() if payload.get("push_token") else None,
            "last_seen_at": timezone.now(),
            "last_ip": ip_address,
            "is_deleted": False,
            "deleted_at": None,
        }
        device, _ = UserDevice.objects.update_or_create(
            user=user, device_fingerprint=fingerprint, defaults=defaults
        )
        return device

