from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import OTP
from accounts.services.otp import IssuedOTP, OTPService
from accounts.services.exceptions import (
    OTPCooldownError,
    OTPExpiredError,
    OTPInvalidError,
    OTPMaxAttemptsError,
    OTPQuotaExceededError,
    ValidationError,
)
from accounts.services.otp_generator import DjangoOTPHasher, SecureOTPGenerator
from conftest import FakeLock, FakeRateLimiter

User = get_user_model()
pytestmark = pytest.mark.django_db


class TestOTPIssue:
    def setup_method(self):
        self.rate_limiter = FakeRateLimiter()
        self.lock = FakeLock()
        self.service = OTPService(
            generator=SecureOTPGenerator(),
            hasher=DjangoOTPHasher(),
            rate_limiter=self.rate_limiter,
            lock=self.lock,
        )
        self.user = User.objects.create_user(
            email="otpuser@test.com", username="otpuser", password="pass",
            is_active=True,
        )

    def test_issue_creates_otp_record(self):
        issued = self.service.issue(
            user=self.user,
            purpose="password_reset",
            delivery_address=self.user.email,
        )
        assert isinstance(issued, IssuedOTP)
        assert issued.purpose == "password_reset"
        assert issued.delivery_address == self.user.email
        assert len(issued.code) == 6
        assert issued.code.isdigit()

        db_otp = OTP.objects.get(pk=issued.otp_id)
        assert db_otp.user == self.user
        assert db_otp.purpose == "password_reset"
        assert db_otp.is_used is False

    def test_issue_invalidates_previous(self):
        first = self.service.issue(
            user=self.user, purpose="login",
            delivery_address=self.user.email,
        )
        self.rate_limiter.cooldowns.clear()
        second = self.service.issue(
            user=self.user, purpose="login",
            delivery_address=self.user.email,
        )
        first_db = OTP.objects.get(pk=first.otp_id)
        assert first_db.is_used is True
        second_db = OTP.objects.get(pk=second.otp_id)
        assert second_db.is_used is False

    def test_issue_cooldown(self):
        self.service.issue(
            user=self.user, purpose="password_reset",
            delivery_address=self.user.email,
        )
        with pytest.raises(OTPCooldownError):
            self.service.issue(
                user=self.user, purpose="password_reset",
                delivery_address=self.user.email,
            )

    def test_issue_different_purpose_no_cooldown(self):
        self.service.issue(
            user=self.user, purpose="login",
            delivery_address=self.user.email,
        )
        issued = self.service.issue(
            user=self.user, purpose="password_reset",
            delivery_address=self.user.email,
        )
        assert issued.purpose == "password_reset"

    def test_issue_quota_exceeded(self):
        self.service._daily_quota = 0
        with pytest.raises(OTPQuotaExceededError):
            self.service.issue(
                user=self.user, purpose="password_reset",
                delivery_address=self.user.email,
            )

    def test_issue_stores_ip_address(self):
        issued = self.service.issue(
            user=self.user, purpose="login",
            delivery_address=self.user.email,
            ip_address="203.0.113.42",
        )
        db_otp = OTP.objects.get(pk=issued.otp_id)
        assert db_otp.ip_address == "203.0.113.42"


class TestOTPVerify:
    def setup_method(self):
        self.rate_limiter = FakeRateLimiter()
        self.lock = FakeLock()
        self.hasher = DjangoOTPHasher()
        self.service = OTPService(
            generator=SecureOTPGenerator(),
            hasher=self.hasher,
            rate_limiter=self.rate_limiter,
            lock=self.lock,
        )
        self.user = User.objects.create_user(
            email="verifyuser@test.com", username="verifyuser", password="pass",
            is_active=True,
        )

    def _issue(self, purpose="login") -> str:
        issued = self.service.issue(
            user=self.user, purpose=purpose,
            delivery_address=self.user.email,
        )
        return issued.code

    def test_verify_valid_code(self):
        code = self._issue()
        record = self.service.verify(
            user=self.user, purpose="login", code=code,
        )
        assert record.is_used is True
        assert record.user == self.user

    def test_verify_invalid_code(self):
        self._issue()
        with pytest.raises(OTPInvalidError):
            self.service.verify(
                user=self.user, purpose="login", code="000000",
            )

    def test_verify_expired(self):
        code = self._issue()
        otp = OTP.objects.get(user=self.user, purpose="login", is_used=False)
        otp.expires_at = timezone.now() - timedelta(seconds=1)
        otp.save()
        with pytest.raises(OTPExpiredError):
            self.service.verify(
                user=self.user, purpose="login", code=code,
            )

    def test_verify_max_attempts(self):
        self._issue()
        for _ in range(5):
            with pytest.raises(OTPInvalidError):
                self.service.verify(
                    user=self.user, purpose="login", code="000000",
                )
        with pytest.raises(OTPMaxAttemptsError):
            self.service.verify(
                user=self.user, purpose="login", code="000000",
            )

    def test_verify_no_otp(self):
        with pytest.raises(OTPInvalidError):
            self.service.verify(
                user=self.user, purpose="login", code="123456",
            )

    def test_verify_different_purpose(self):
        code = self._issue(purpose="login")
        with pytest.raises(OTPInvalidError):
            self.service.verify(
                user=self.user, purpose="password_reset", code=code,
            )

    def test_verify_different_user(self):
        code = self._issue()
        other = User.objects.create_user(
            email="other@test.com", username="otheruser", password="pass",
            is_active=True,
        )
        with pytest.raises(OTPInvalidError):
            self.service.verify(
                user=other, purpose="login", code=code,
            )

    def test_verify_numeric_validation(self):
        with pytest.raises(ValidationError):
            self.service.verify(
                user=self.user, purpose="login", code="abc",
            )

    def test_verify_reuse_rejected(self):
        code = self._issue()
        self.service.verify(user=self.user, purpose="login", code=code)
        with pytest.raises(OTPInvalidError):
            self.service.verify(user=self.user, purpose="login", code=code)
