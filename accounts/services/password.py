from __future__ import annotations

import logging
from dataclasses import dataclass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from accounts.models import User
from utils.enum import OTPChannel, OTPPurpose

from .exceptions import AuthenticationError, NotFoundError, ValidationError
from .otp import OTPService
from .tokens import TokenService


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResetRequestResult:
    user_id: str
    expires_at: object


class PasswordService:
    def __init__(
        self,
        *,
        otp_service: OTPService | None = None,
        token_service: TokenService | None = None,
    ) -> None:
        self._otp = otp_service or OTPService()
        self._tokens = token_service or TokenService()

# Sends a reset OTP. Returns None when no user matches — callers
    @transaction.atomic
    def request_reset(self, *, email: str, ip_address: str | None = None) -> ResetRequestResult | None:
        normalized = email.strip().lower() if email else ""
        if not normalized:
            raise ValidationError("Email is required.", code="email_required")

        try:
            user = User.objects.get(email=normalized)
        except User.DoesNotExist:
            return None

        issued = self._otp.issue(
            user=user,
            purpose=OTPPurpose.PASSWORD_RESET.value,
            delivery_address=normalized,
            channel=OTPChannel.EMAIL.value,
            ip_address=ip_address,
        )

        from accounts import tasks

        transaction.on_commit(
            lambda: tasks.send_otp_email.delay(
                to=normalized,
                code=issued.code,
                purpose=issued.purpose,
                username=user.username,
            )
        )
        return ResetRequestResult(user_id=str(user.pk), expires_at=issued.expires_at)

    @transaction.atomic
    def confirm_reset(self, *, email: str, code: str, new_password: str) -> None:
        normalized = email.strip().lower() if email else ""
        if not normalized or not code or not new_password:
            raise ValidationError("Email, code and new password are required.", code="missing_fields")

        try:
            user = User.objects.get(email=normalized)
        except User.DoesNotExist as exc:
            raise NotFoundError("No account found for this email.", code="user_not_found") from exc

        self._otp.verify(user=user, purpose=OTPPurpose.PASSWORD_RESET.value, code=code)
        self._set_password(user, new_password)
        self._tokens.revoke_all_for_user(user)

    @transaction.atomic
    def change_password(self, *, user: User, current_password: str, new_password: str) -> None:
        if not user.check_password(current_password):
            raise AuthenticationError("Current password is incorrect.", code="invalid_password")
        if current_password == new_password:
            raise ValidationError("New password must differ from current password.", code="password_unchanged")
        self._set_password(user, new_password)
        self._tokens.revoke_all_for_user(user)

    @staticmethod
    def _set_password(user: User, new_password: str) -> None:
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise ValidationError("; ".join(exc.messages), code="password_weak") from exc
        user.set_password(new_password)
        user.save(update_fields=["password"])

