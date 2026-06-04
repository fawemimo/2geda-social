from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from accounts.services.authentication import AuthenticationService
from accounts.services.exceptions import (
    AccountInactiveError,
    AccountLockedError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
)
from accounts.services.interfaces import IRateLimiter, ITokenManager
from accounts.services.password import PasswordService
from accounts.services.otp import OTPService
from utils.enum import OTPChannel

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def mock_rate_limiter():
    limiter = MagicMock(spec=IRateLimiter)
    limiter.cooldown.return_value = False
    limiter.hit.return_value = (True, 1)
    return limiter


@pytest.fixture
def mock_token_service():
    service = MagicMock(spec=ITokenManager)
    service.issue.return_value = {
        "access": "access-token",
        "access_expires_at": 1234567890,
        "refresh": "refresh-token",
        "refresh_expires_at": 1234567890,
    }
    return service


@pytest.fixture
def auth_service(mock_rate_limiter, mock_token_service):
    return AuthenticationService(
        rate_limiter=mock_rate_limiter,
        token_service=mock_token_service,
    )


@pytest.fixture
def active_user():
    return User.objects.create_user(
        email="alice@example.com",
        username="alice",
        phone_number="+2348012345678",
        password="secret123",
        is_active=True,
    )


class TestLogin:

    @patch("accounts.services.authentication.authenticate")
    def test_login_with_email(self, mock_auth, auth_service, mock_rate_limiter, mock_token_service, active_user):
        mock_auth.return_value = active_user
        result = auth_service.login(email="alice@example.com", password="secret123")

        assert result.user_id == str(active_user.pk)
        assert result.access == "access-token"
        mock_auth.assert_called_once_with(email="alice@example.com", password="secret123")
        mock_rate_limiter.reset.assert_called_once()
        mock_token_service.issue.assert_called_once()

    @patch("accounts.services.authentication.authenticate")
    def test_login_with_username(self, mock_auth, auth_service, mock_rate_limiter, active_user):
        mock_auth.return_value = active_user
        result = auth_service.login(username="alice", password="secret123")

        assert result.user_id == str(active_user.pk)
        mock_auth.assert_called_once_with(email="alice@example.com", password="secret123")
        mock_rate_limiter.reset.assert_called_once()

    @patch("accounts.services.authentication.authenticate")
    def test_login_with_phone(self, mock_auth, auth_service, mock_rate_limiter, active_user):
        mock_auth.return_value = active_user
        result = auth_service.login(phone_number="+2348012345678", password="secret123")

        assert result.user_id == str(active_user.pk)
        mock_auth.assert_called_once_with(email="alice@example.com", password="secret123")
        mock_rate_limiter.reset.assert_called_once()

    @patch("accounts.services.authentication.authenticate")
    def test_login_with_device(self, mock_auth, auth_service, active_user):
        mock_auth.return_value = active_user
        auth_service._register_or_update_device = MagicMock(return_value=MagicMock(pk="d1"))
        result = auth_service.login(
            email="alice@example.com",
            password="secret123",
            device_payload={"platform": "ios", "device_fingerprint": "fp123"},
            ip_address="203.0.113.42",
        )

        assert result.device_id == "d1"
        auth_service._register_or_update_device.assert_called_once_with(
            user=active_user, payload={"platform": "ios", "device_fingerprint": "fp123"}, ip_address="203.0.113.42"
        )

    @patch("accounts.services.authentication.authenticate")
    def test_login_user_not_found(self, mock_auth, auth_service, mock_rate_limiter):
        mock_auth.return_value = None

        with pytest.raises(AuthenticationError, match="Invalid email or password"):
            auth_service.login(email="nobody@example.com", password="secret123")

        mock_rate_limiter.hit.assert_called_once()

    @patch("accounts.services.authentication.authenticate")
    def test_login_wrong_password(self, mock_auth, auth_service, mock_rate_limiter, active_user):
        mock_auth.return_value = None

        with pytest.raises(AuthenticationError, match="Invalid email or password"):
            auth_service.login(email="alice@example.com", password="wrongpass")

        mock_rate_limiter.hit.assert_called_once()

    @patch("accounts.services.authentication.authenticate")
    def test_login_inactive_user(self, mock_auth, auth_service, active_user):
        active_user.is_active = False
        active_user.save()
        mock_auth.return_value = active_user

        with pytest.raises(AccountInactiveError):
            auth_service.login(email="alice@example.com", password="secret123")

    @patch("accounts.services.authentication.authenticate")
    def test_login_deleted_user(self, mock_auth, auth_service, active_user):
        active_user.is_deleted = True
        active_user.save()
        mock_auth.return_value = active_user

        with pytest.raises(AuthenticationError, match="deactivated"):
            auth_service.login(email="alice@example.com", password="secret123")

    def test_login_account_locked(self, auth_service, mock_rate_limiter):
        mock_rate_limiter.cooldown.return_value = True

        with pytest.raises(AccountLockedError):
            auth_service.login(email="locked@example.com", password="secret123")

    @patch("accounts.services.authentication.authenticate")
    def test_login_lockout_after_max_attempts(
        self, mock_auth, auth_service, mock_rate_limiter, active_user
    ):
        mock_auth.return_value = None
        # On the Nth hit, return (False, 11) to trigger lockout
        mock_rate_limiter.hit.return_value = (False, 11)

        with pytest.raises(AccountLockedError):
            auth_service.login(email="alice@example.com", password="wrongpass")

        mock_rate_limiter.start_cooldown.assert_called_once()

    def test_login_missing_identifier(self, auth_service):
        with pytest.raises(ValidationError, match="Identifier and password are required"):
            auth_service.login(password="secret123")

    def test_login_missing_password(self, auth_service):
        with pytest.raises(ValidationError, match="Identifier and password are required"):
            auth_service.login(email="alice@example.com", password="")


class TestResolveUser:

    def test_resolve_by_email(self, active_user):
        result = AuthenticationService._resolve_user(email="alice@example.com")
        assert result == active_user

    def test_resolve_by_email_case_insensitive(self, active_user):
        result = AuthenticationService._resolve_user(email="ALICE@example.com")
        assert result == active_user

    def test_resolve_by_username(self, active_user):
        result = AuthenticationService._resolve_user(username="alice")
        assert result == active_user

    def test_resolve_by_phone(self, active_user):
        result = AuthenticationService._resolve_user(phone_number="+2348012345678")
        assert result == active_user

    def test_resolve_nonexistent_email(self):
        result = AuthenticationService._resolve_user(email="nobody@example.com")
        assert result is None

    def test_resolve_nonexistent_username(self):
        result = AuthenticationService._resolve_user(username="nonexistent")
        assert result is None

    def test_resolve_nonexistent_phone(self):
        result = AuthenticationService._resolve_user(phone_number="+2348000000000")
        assert result is None

    def test_resolve_no_args(self):
        result = AuthenticationService._resolve_user()
        assert result is None


class TestPasswordServiceRequestReset:

    @pytest.fixture
    def password_service(self):
        otp = MagicMock(spec=OTPService)
        otp.issue.return_value = MagicMock(
            code="123456", purpose="password_reset", expires_at="2026-06-04T12:00:00Z",
        )
        return PasswordService(otp_service=otp)

    @patch("accounts.tasks.send_otp_email.delay")
    def test_request_reset_with_email(
        self, mock_email, password_service, active_user
    ):
        result = password_service.request_reset(email="alice@example.com")
        assert result is not None
        assert result.user_id == str(active_user.pk)
        mock_email.assert_called_once_with(
            to="alice@example.com", code="123456",
            purpose="password_reset", username="alice",
        )

    @patch("accounts.tasks.send_otp_sms.delay")
    def test_request_reset_with_phone(
        self, mock_sms, password_service, active_user
    ):
        result = password_service.request_reset(phone_number="+2348012345678")
        assert result is not None
        assert result.user_id == str(active_user.pk)
        mock_sms.assert_called_once_with(
            to="+2348012345678", code="123456",
            purpose="password_reset",
        )

    def test_request_reset_nonexistent_email(self, password_service):
        result = password_service.request_reset(email="nobody@example.com")
        assert result is None

    def test_request_reset_nonexistent_phone(self, password_service):
        result = password_service.request_reset(phone_number="+2348000000000")
        assert result is None

    @patch("accounts.tasks.send_otp_email.delay")
    def test_request_reset_otp_channel_email(
        self, mock_email, password_service, active_user
    ):
        password_service.request_reset(email="alice@example.com")
        issued = password_service._otp.issue
        issued.assert_called_once()
        call_kwargs = issued.call_args.kwargs
        assert call_kwargs["channel"] == OTPChannel.EMAIL.value

    @patch("accounts.tasks.send_otp_sms.delay")
    def test_request_reset_otp_channel_sms(
        self, mock_sms, password_service, active_user
    ):
        password_service.request_reset(phone_number="+2348012345678")
        issued = password_service._otp.issue
        issued.assert_called_once()
        call_kwargs = issued.call_args.kwargs
        assert call_kwargs["channel"] == OTPChannel.SMS.value


class TestPasswordServiceConfirmReset:

    @pytest.fixture
    def password_service(self):
        otp = MagicMock(spec=OTPService)
        tokens = MagicMock(spec=ITokenManager)
        return PasswordService(otp_service=otp, token_service=tokens)

    def test_confirm_reset_with_email(self, password_service, active_user):
        password_service.confirm_reset(
            email="alice@example.com", code="123456", new_password="NewStr0ng!"
        )
        password_service._otp.verify.assert_called_once_with(
            user=active_user, purpose="password_reset", code="123456"
        )
        password_service._tokens.revoke_all_for_user.assert_called_once_with(active_user)
        active_user.refresh_from_db()
        assert active_user.check_password("NewStr0ng!")

    def test_confirm_reset_with_phone(self, password_service, active_user):
        password_service.confirm_reset(
            phone_number="+2348012345678", code="123456", new_password="NewStr0ng!"
        )
        password_service._otp.verify.assert_called_once_with(
            user=active_user, purpose="password_reset", code="123456"
        )
        active_user.refresh_from_db()
        assert active_user.check_password("NewStr0ng!")

    def test_confirm_reset_nonexistent_email(self, password_service):
        with pytest.raises(NotFoundError):
            password_service.confirm_reset(
                email="nobody@example.com", code="123456", new_password="NewStr0ng!"
            )

    def test_confirm_reset_nonexistent_phone(self, password_service):
        with pytest.raises(NotFoundError):
            password_service.confirm_reset(
                phone_number="+2348000000000", code="123456", new_password="NewStr0ng!"
            )


class TestPasswordServiceResolveIdentifier:

    def test_resolve_by_email(self, active_user):
        identifier, user, channel = PasswordService._resolve_identifier(email="alice@example.com")
        assert identifier == "alice@example.com"
        assert user == active_user
        assert channel == OTPChannel.EMAIL.value

    def test_resolve_by_email_case_insensitive(self, active_user):
        identifier, user, channel = PasswordService._resolve_identifier(email="ALICE@example.com")
        assert identifier == "alice@example.com"
        assert user == active_user

    def test_resolve_by_phone(self, active_user):
        identifier, user, channel = PasswordService._resolve_identifier(phone_number="+2348012345678")
        assert identifier == "+2348012345678"
        assert user == active_user
        assert channel == OTPChannel.SMS.value

    def test_resolve_nonexistent_email(self):
        identifier, user, channel = PasswordService._resolve_identifier(email="nobody@example.com")
        assert identifier == "nobody@example.com"
        assert user is None
        assert channel == OTPChannel.EMAIL.value

    def test_resolve_nonexistent_phone(self):
        identifier, user, channel = PasswordService._resolve_identifier(phone_number="+2348000000000")
        assert identifier == "+2348000000000"
        assert user is None
        assert channel == OTPChannel.SMS.value

    def test_resolve_no_args(self):
        identifier, user, channel = PasswordService._resolve_identifier()
        assert identifier is None
        assert user is None
        assert channel is None
