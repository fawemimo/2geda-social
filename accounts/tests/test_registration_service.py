from __future__ import annotations

from unittest.mock import ANY, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from accounts.models import Referral, UserProfile
from accounts.services.otp_generator import DjangoOTPHasher
from accounts.services.registration import RegistrationService
from accounts.services.exceptions import (
    ConflictError,
    NotFoundError,
    OTPCooldownError,
    OTPExpiredError,
    OTPInvalidError,
    OTPMaxAttemptsError,
    OTPQuotaExceededError,
    ValidationError,
)
from accounts.services.tokens import TokenService

User = get_user_model()
pytestmark = pytest.mark.django_db


DOMAIN_PATCH = "accounts.services.registration._domain_has_mx"


class TestStartRegistration:
    def setup_method(self):
        cache.clear()
        self.service = RegistrationService()
        self._domain_patcher = patch(DOMAIN_PATCH, return_value=True)
        self._domain_mock = self._domain_patcher.start()

    def teardown_method(self):
        self._domain_patcher.stop()

    @patch("accounts.tasks.send_otp_email.delay")
    def test_happy_path_email(self, mock_email_delay):
        result = self.service.start_registration(
            email="smithEze@example.com",
            username="smithEze",
            password="Str0ng!pass",
        )
        assert result.email == "smithEze@example.com"
        assert result.phone_number is None
        assert result.otp_expires_at is not None
        assert result.cooldown_until is not None
        mock_email_delay.assert_called_once_with(
            to="smithEze@example.com", code=ANY,
            purpose="registration", username="smithEze",
        )

    @patch("accounts.tasks.send_otp_message.delay")
    def test_happy_path_phone(self, mock_whatsapp_delay):
        result = self.service.start_registration(
            email=None,
            username="bob",
            password="Str0ng!pass",
            phone_number="+2348012345678",
        )
        assert result.phone_number == "+2348012345678"
        assert result.email is None
        mock_whatsapp_delay.assert_called_once_with(
            to="+2348012345678", code=ANY, purpose="registration", channel=None,
        )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_existing_user_conflict(self, _mock):
        User.objects.create_user(
            email="existing@example.com", username="existing", password="pass",
        )
        with pytest.raises(ConflictError):
            self.service.start_registration(
                email="existing@example.com",
                username="other",
                password="Str0ng!pass",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_existing_username_conflict(self, _mock):
        User.objects.create_user(
            email="other@example.com", username="taken", password="pass",
        )
        with pytest.raises(ConflictError):
            self.service.start_registration(
                email="new@example.com",
                username="taken",
                password="Str0ng!pass",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_weak_password(self, _mock):
        with pytest.raises(ValidationError):
            self.service.start_registration(
                email="weak@example.com",
                username="weakuser",
                password="short",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_cooldown(self, _mock):
        self.service.start_registration(
            email="cooldown@example.com",
            username="cooldown",
            password="Str0ng!pass",
        )
        with pytest.raises(OTPCooldownError):
            self.service.start_registration(
                email="cooldown@example.com",
                username="cooldown2",
                password="Str0ng!pass2",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_quota_exceeded(self, _mock):
        self.service._daily_quota = 0
        with pytest.raises(OTPQuotaExceededError):
            self.service.start_registration(
                email="quota@example.com",
                username="quotauser",
                password="Str0ng!pass",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_invalid_email_format(self, _mock):
        with pytest.raises(ValidationError):
            self.service.start_registration(
                email="not-an-email",
                username="badmail",
                password="Str0ng!pass",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_invalid_username(self, _mock):
        with pytest.raises(ValidationError):
            self.service.start_registration(
                email="valid@example.com",
                username="ab",
                password="Str0ng!pass",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_valid_referral(self, _mock):
        referrer = User.objects.create_user(
            email="referrer@example.com", username="referrer", password="pass",
            is_active=True,
        )
        result = self.service.start_registration(
            email="referred@example.com",
            username="referred",
            password="Str0ng!pass",
            referral_code=referrer.referral_code,
        )
        assert result.email == "referred@example.com"

    @patch("accounts.tasks.send_otp_email.delay")
    def test_invalid_referral(self, _mock):
        with pytest.raises(NotFoundError):
            self.service.start_registration(
                email="noref@example.com",
                username="noref",
                password="Str0ng!pass",
                referral_code="INVALIDREF",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    def test_email_normalized(self, _mock):
        result = self.service.start_registration(
            email="  smithEze@Example.COM  ",
            username="smithEzenorm",
            password="Str0ng!pass",
        )
        assert result.email == "smithEze@example.com"

    @patch(DOMAIN_PATCH, return_value=False)
    @patch("accounts.tasks.send_otp_email.delay")
    def test_email_domain_rejected(self, _mock, _mock_domain):
        with pytest.raises(ValidationError, match="does not accept email"):
            self.service.start_registration(
                email="user@nonexistent-test-domain-12345.com",
                username="baddomain",
                password="Str0ng!pass",
            )

    @patch(DOMAIN_PATCH, return_value=False)
    @patch("accounts.tasks.send_otp_email.delay")
    def test_email_domain_rejected_with_code(self, _mock, _mock_domain):
        with pytest.raises(ValidationError) as exc:
            self.service.start_registration(
                email="user@baddomain.com",
                username="baddomain2",
                password="Str0ng!pass",
            )
        assert exc.value.code == "email_domain_invalid"

    @patch(DOMAIN_PATCH, return_value=True)
    @patch("accounts.tasks.send_otp_email.delay")
    def test_email_domain_accepted_with_mx(self, _mock_email, _mock_domain):
        result = self.service.start_registration(
            email="user@gmail.com",
            username="validmxuser",
            password="Str0ng!pass",
        )
        assert result.email == "user@gmail.com"


class TestCompleteRegistration:
    def setup_method(self):
        cache.clear()
        self.hasher = DjangoOTPHasher()
        self.service = RegistrationService()
        self._domain_patcher = patch(DOMAIN_PATCH, return_value=True)
        self._domain_mock = self._domain_patcher.start()

    def teardown_method(self):
        self._domain_patcher.stop()

    def _start(self, email="complete@example.com", username="completeuser") -> str:
        self.service.start_registration(
            email=email, username=username, password="Str0ng!pass",
        )
        return "123456"  # Dev OTP

    @patch("accounts.tasks.send_otp_email.delay")
    @patch.object(TokenService, "issue")
    def test_happy_path(self, mock_issue, _mock_email):
        mock_issue.return_value = {
            "access": "access-token", "access_expires_at": 1234567890,
            "refresh": "refresh-token", "token_type": "Bearer",
        }
        code = self._start()
        result = self.service.complete_registration(
            email="complete@example.com", code=code,
        )
        assert result.email == "complete@example.com"
        assert result.access == "access-token"
        user = User.objects.get(email="complete@example.com")
        assert str(user.pk) == result.user_id
        assert user.is_active is True
        assert user.is_email_verified is True
        assert UserProfile.objects.filter(user=user).exists()

    @patch("accounts.tasks.send_otp_message.delay")
    @patch.object(TokenService, "issue")
    def test_phone_registration(self, mock_issue, _mock_whatsapp):
        mock_issue.return_value = {
            "access": "access-token", "access_expires_at": 1234567890,
            "refresh": "refresh-token", "token_type": "Bearer",
        }
        self.service.start_registration(
            email=None, username="phonereg", password="Str0ng!pass",
            phone_number="+2348012345678",
        )
        result = self.service.complete_registration(
            phone_number="+2348012345678", code="123456",
        )
        assert result.phone_number == "+2348012345678"
        user = User.objects.get(phone_number="+2348012345678")
        assert user.is_phone_verified is True

    @patch("accounts.tasks.send_otp_email.delay")
    @patch.object(TokenService, "issue")
    def test_with_referral(self, mock_issue, _mock_email):
        mock_issue.return_value = {
            "access": "access-token", "access_expires_at": 1234567890,
            "refresh": "refresh-token", "token_type": "Bearer",
        }
        referrer = User.objects.create_user(
            email="referrer@example.com", username="referrer", password="pass",
            is_active=True,
        )
        code = "123456"
        self.service.start_registration(
            email="referred@example.com", username="referred",
            password="Str0ng!pass",
            referral_code=referrer.referral_code,
        )
        result = self.service.complete_registration(
            email="referred@example.com", code=code,
        )
        assert Referral.objects.filter(
            referrer=referrer, referred_user_id=result.user_id,
        ).exists()

    def test_invalid_code(self):
        self._start()
        with pytest.raises(OTPInvalidError):
            self.service.complete_registration(
                email="complete@example.com", code="000000",
            )

    def test_max_attempts(self):
        self._start()
        for _ in range(5):
            with pytest.raises(OTPInvalidError):
                self.service.complete_registration(
                    email="complete@example.com", code="000000",
                )
        with pytest.raises(OTPMaxAttemptsError):
            self.service.complete_registration(
                email="complete@example.com", code="000000",
            )

    def test_no_pending_registration(self):
        with pytest.raises(OTPExpiredError):
            self.service.complete_registration(
                email="neverstarted@example.com", code="123456",
            )

    @patch("accounts.tasks.send_otp_email.delay")
    @patch.object(TokenService, "issue")
    def test_integrity_conflict(self, mock_issue, _mock_email):
        mock_issue.return_value = {
            "access": "access-token", "access_expires_at": 1234567890,
            "refresh": "refresh-token", "token_type": "Bearer",
        }
        self._start(email="conflictacc@example.com", username="conflictacc2")
        # Another process creates a user with the same email before we complete
        User.objects.create_user(
            email="conflictacc@example.com", username="someoneelse", password="pass",
        )
        with pytest.raises(ConflictError):
            self.service.complete_registration(
                email="conflictacc@example.com", code="123456",
            )

    def test_numeric_code_validation(self):
        self._start()
        with pytest.raises(ValidationError):
            self.service.complete_registration(
                email="complete@example.com", code="abc",
            )


class TestResendRegistrationOTP:
    def setup_method(self):
        cache.clear()
        self.service = RegistrationService()
        self._domain_patcher = patch(DOMAIN_PATCH, return_value=True)
        self._domain_mock = self._domain_patcher.start()

    def teardown_method(self):
        self._domain_patcher.stop()

    def _start(self, email="resend@example.com"):
        self.service.start_registration(
            email=email, username="resenduser", password="Str0ng!pass",
        )

    def _clear_cooldown(self, identifier: str) -> None:
        from accounts.services.cache import hashed_key, make_key
        key = make_key("pending_registration", "cooldown", hashed_key(identifier.lower()))
        cache.delete(key)

    @patch("accounts.tasks.send_otp_email.delay")
    def test_resend_success(self, mock_email_delay):
        self._start()

        self._clear_cooldown("resend@example.com")
        mock_email_delay.reset_mock()
        result = self.service.resend_registration_otp(email="resend@example.com")
        assert result.email == "resend@example.com"
        mock_email_delay.assert_called_once()

    def test_resend_no_pending(self):
        with pytest.raises(NotFoundError):
            self.service.resend_registration_otp(email="neverstarted@example.com")

    @patch("accounts.tasks.send_otp_email.delay")
    def test_resend_cooldown(self, _mock):
        self._start()
        with pytest.raises(OTPCooldownError):
            self.service.resend_registration_otp(email="resend@example.com")

    @patch("accounts.tasks.send_otp_email.delay")
    def test_resend_quota_exceeded(self, _mock):
        self._start()
        self._clear_cooldown("resend@example.com")
        self.service._daily_quota = 0
        with pytest.raises(OTPQuotaExceededError):
            self.service.resend_registration_otp(email="resend@example.com")
