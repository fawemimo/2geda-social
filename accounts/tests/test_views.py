from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.cache import make_user_me_cache_key
from accounts.models import UserDevice, UserProfile

User = get_user_model()
pytestmark = pytest.mark.django_db

API_ROOT = "/api/v2/accounts/"


def _auth_client(token: str = "test-access-token") -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


class TestRegisterView:
    url = f"{API_ROOT}auth/register/"

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_success(self, mock_start):
        mock_start.return_value = MagicMock(
            email="a@b.com",
            phone_number=None,
            otp_expires_at="2026-06-03T12:00:00Z",
            cooldown_until="2026-06-03T11:01:00Z",
        )
        resp = APIClient().post(self.url, {
            "email": "a@b.com",
            "username": "newuser",
            "password": "Str0ng!pass",
        }, format="json")
        assert resp.status_code == 202
        assert resp.data["status"] is True
        assert resp.data["data"]["next"] == "verify_otp"

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_with_optional_fields(self, mock_start):
        mock_start.return_value = MagicMock(
            email="a@b.com",
            phone_number="+2348012345678",
            otp_expires_at="2026-06-03T12:00:00Z",
            cooldown_until="2026-06-03T11:01:00Z",
        )
        resp = APIClient().post(self.url, {
            "email": "a@b.com",
            "username": "newuser",
            "password": "Str0ng!pass",
            "phone_number": "+2348012345678",
            "referral_code": "REF123",
        }, format="json")
        assert resp.status_code == 202
        mock_start.assert_called_once_with(
            email="a@b.com",
            username="newuser",
            password="Str0ng!pass",
            phone_number="+2348012345678",
            referral_code="REF123",
            ip_address=ANY,
            # Not supplied by the client -> no preference -> WhatsApp default.
            channel=None,
        )

    def test_register_missing_fields(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 400

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_phone_only(self, mock_start):
        mock_start.return_value = MagicMock(
            email=None, phone_number="+2348012345678",
            otp_expires_at="2026-06-03T12:00:00Z",
            cooldown_until="2026-06-03T11:01:00Z",
        )
        resp = APIClient().post(self.url, {
            "phone_number": "+2348012345678", "username": "phoneuser",
            "password": "Str0ng!pass",
        }, format="json")
        assert resp.status_code == 202
        assert resp.data["data"]["phone_number"] == "+2348012345678"

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_conflict(self, mock_start):
        from accounts.services.exceptions import ConflictError
        mock_start.side_effect = ConflictError()
        resp = APIClient().post(self.url, {
            "email": "dup@b.com", "username": "dupuser", "password": "Str0ng!pass",
        }, format="json")
        assert resp.status_code == 409

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_validation_error(self, mock_start):
        from accounts.services.exceptions import ValidationError
        mock_start.side_effect = ValidationError("Invalid input.")
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "username": "newuser", "password": "weak",
        }, format="json")
        assert resp.status_code == 400

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_invalid_email_domain(self, mock_start):
        from accounts.services.exceptions import ValidationError
        mock_start.side_effect = ValidationError(
            "The email domain 'baddomain.com' does not accept email.",
            code="email_domain_invalid",
        )
        resp = APIClient().post(self.url, {
            "email": "user@baddomain.com", "username": "domainuser",
            "password": "Str0ng!pass",
        }, format="json")
        assert resp.status_code == 400
        assert resp.data["code"] == "email_domain_invalid"

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_cooldown(self, mock_start):
        from accounts.services.exceptions import OTPCooldownError
        mock_start.side_effect = OTPCooldownError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "username": "newuser", "password": "Str0ng!pass",
        }, format="json")
        assert resp.status_code == 429

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_quota_exceeded(self, mock_start):
        from accounts.services.exceptions import OTPQuotaExceededError
        mock_start.side_effect = OTPQuotaExceededError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "username": "newuser", "password": "Str0ng!pass",
        }, format="json")
        assert resp.status_code == 429

    def test_register_no_identifier(self):
        resp = APIClient().post(self.url, {
            "username": "noid", "password": "Str0ng!pass",
        }, format="json")
        assert resp.status_code == 400

    @patch("accounts.views.RegistrationService.start_registration")
    def test_register_referral_not_found(self, mock_start):
        from accounts.services.exceptions import NotFoundError
        mock_start.side_effect = NotFoundError("Referral code not found.")
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "username": "newuser",
            "password": "Str0ng!pass", "referral_code": "INVALID",
        }, format="json")
        assert resp.status_code == 404


class TestVerifyRegistrationOTPView:
    url = f"{API_ROOT}auth/verify-otp/"

    @patch("accounts.views.RegistrationService.complete_registration")
    def test_verify_success_without_device(self, mock_complete):
        mock_complete.return_value = MagicMock(
            user_id="u1", email="a@b.com", phone_number=None,
            access="access-token", refresh="refresh-token",
        )
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "code": "123456",
        }, format="json")
        assert resp.status_code == 201
        assert resp.data["data"]["user_id"] == "u1"

    @patch("accounts.views.DeviceService.register")
    @patch("accounts.views.RegistrationService.complete_registration")
    def test_verify_success_with_device(self, mock_complete, mock_dev_reg):
        user = User.objects.create_user(
            email="devreg@test.com", username="devreguser", password="pass",
        )
        mock_complete.return_value = MagicMock(
            user_id=str(user.pk), email="a@b.com", phone_number=None,
            access="access-token", refresh="refresh-token",
        )
        mock_dev_reg.return_value = MagicMock()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "code": "123456",
            "device": {"platform": "ios", "device_fingerprint": "fp123"},
        }, format="json")
        assert resp.status_code == 201
        mock_dev_reg.assert_called_once()

    @patch("accounts.views.RegistrationService")
    def test_verify_invalid_code(self, mock_reg_svc):
        from accounts.services.exceptions import OTPInvalidError
        mock_reg_svc.return_value.complete_registration.side_effect = OTPInvalidError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "code": "000000",
        }, format="json")
        assert resp.status_code == 400

    @patch("accounts.views.RegistrationService")
    def test_verify_expired(self, mock_reg_svc):
        from accounts.services.exceptions import OTPExpiredError
        mock_reg_svc.return_value.complete_registration.side_effect = OTPExpiredError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "code": "123456",
        }, format="json")
        assert resp.status_code == 400

    @patch("accounts.views.RegistrationService")
    def test_verify_max_attempts(self, mock_reg_svc):
        from accounts.services.exceptions import OTPMaxAttemptsError
        mock_reg_svc.return_value.complete_registration.side_effect = OTPMaxAttemptsError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "code": "123456",
        }, format="json")
        assert resp.status_code == 429

    @patch("accounts.views.RegistrationService")
    def test_verify_validation_error(self, mock_reg_svc):
        from accounts.services.exceptions import ValidationError
        mock_reg_svc.return_value.complete_registration.side_effect = ValidationError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "code": "abc",
        }, format="json")
        assert resp.status_code == 400

    def test_verify_no_code(self):
        resp = APIClient().post(self.url, {"email": "a@b.com"}, format="json")
        assert resp.status_code == 400

    def test_verify_no_identifier(self):
        resp = APIClient().post(self.url, {"code": "123456"}, format="json")
        assert resp.status_code == 400

    @patch("accounts.views.DeviceService.register")
    @patch("accounts.views.RegistrationService.complete_registration")
    def test_verify_success_with_device_phone(self, mock_complete, mock_dev_reg):
        user = User.objects.create_user(
            email="devregphone@test.com", username="devregphone", password="pass",
        )
        mock_complete.return_value = MagicMock(
            user_id=str(user.pk), email=None, phone_number="+2348012345678",
            access="access-token", refresh="refresh-token",
        )
        mock_dev_reg.return_value = MagicMock()
        resp = APIClient().post(self.url, {
            "phone_number": "+2348012345678", "code": "123456",
            "device": {"platform": "android", "device_fingerprint": "fp456"},
        }, format="json")
        assert resp.status_code == 201
        assert resp.data["data"]["phone_number"] == "+2348012345678"


class TestResendOTPView:
    url = f"{API_ROOT}auth/resend-otp/"

    @patch("accounts.tasks.send_otp_email")
    @patch("accounts.views.RegistrationService.resend_registration_otp")
    def test_resend_registration_otp(self, mock_resend, mock_email):
        mock_resend.return_value = MagicMock(
            email="a@b.com", phone_number=None,
            otp_expires_at="2026-06-03T12:00:00Z",
            cooldown_until="2026-06-03T11:01:00Z",
        )
        resp = APIClient().post(self.url, {"email": "a@b.com"}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["purpose"] == "registration"

    @patch("accounts.tasks.send_otp_email")
    @patch("accounts.views.OTPService.issue")
    def test_resend_password_reset_otp(self, mock_issue, mock_email):
        user = User.objects.create_user(
            email="bob@test.com", username="bob", password="pass", is_active=True,
        )
        mock_issue.return_value = MagicMock(
            code="654321", expires_at="2026-06-03T12:00:00Z", purpose="password_reset",
        )
        resp = APIClient().post(self.url, {
            "email": user.email, "purpose": "password_reset",
        }, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["purpose"] == "password_reset"

    def test_resend_unknown_email(self):
        resp = APIClient().post(self.url, {
            "email": "nonexistent@test.com", "purpose": "password_reset",
        }, format="json")
        assert resp.status_code == 404

    @patch("accounts.tasks.send_otp_message")
    @patch("accounts.views.RegistrationService.resend_registration_otp")
    def test_resend_registration_phone(self, mock_resend, mock_whatsapp):
        mock_resend.return_value = MagicMock(
            email=None, phone_number="+2348012345678",
            otp_expires_at="2026-06-03T12:00:00Z",
            cooldown_until="2026-06-03T11:01:00Z",
        )
        resp = APIClient().post(self.url, {
            "phone_number": "+2348012345678",
        }, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["phone_number"] == "+2348012345678"

    @patch("accounts.views.RegistrationService.resend_registration_otp")
    def test_resend_registration_not_found(self, mock_resend):
        from accounts.services.exceptions import NotFoundError
        mock_resend.side_effect = NotFoundError("No pending registration.")
        resp = APIClient().post(self.url, {"email": "a@b.com"}, format="json")
        assert resp.status_code == 404

    @patch("accounts.views.RegistrationService.resend_registration_otp")
    def test_resend_registration_cooldown(self, mock_resend):
        from accounts.services.exceptions import OTPCooldownError
        mock_resend.side_effect = OTPCooldownError()
        resp = APIClient().post(self.url, {"email": "a@b.com"}, format="json")
        assert resp.status_code == 429

    @patch("accounts.views.RegistrationService.resend_registration_otp")
    def test_resend_registration_quota_exceeded(self, mock_resend):
        from accounts.services.exceptions import OTPQuotaExceededError
        mock_resend.side_effect = OTPQuotaExceededError()
        resp = APIClient().post(self.url, {"email": "a@b.com"}, format="json")
        assert resp.status_code == 429

    @patch("accounts.tasks.send_otp_email")
    @patch("accounts.views.OTPService.issue")
    def test_resend_other_cooldown(self, mock_issue, mock_email):
        from accounts.services.exceptions import OTPCooldownError
        user = User.objects.create_user(
            email="cooldown@test.com", username="cooldown", password="pass", is_active=True,
        )
        mock_issue.side_effect = OTPCooldownError()
        resp = APIClient().post(self.url, {
            "email": user.email, "purpose": "password_reset",
        }, format="json")
        assert resp.status_code == 429

    @patch("accounts.tasks.send_otp_email")
    @patch("accounts.views.OTPService.issue")
    def test_resend_other_quota_exceeded(self, mock_issue, mock_email):
        from accounts.services.exceptions import OTPQuotaExceededError
        user = User.objects.create_user(
            email="quota@test.com", username="quotauser", password="pass", is_active=True,
        )
        mock_issue.side_effect = OTPQuotaExceededError()
        resp = APIClient().post(self.url, {
            "email": user.email, "purpose": "password_reset",
        }, format="json")
        assert resp.status_code == 429

    def test_resend_no_identifier(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 400

    def test_resend_no_identifier_with_purpose(self):
        resp = APIClient().post(self.url, {"purpose": "password_reset"}, format="json")
        assert resp.status_code == 400


class TestLoginView:
    url = f"{API_ROOT}auth/login/"
    mock_result = MagicMock(
        user_id="u1", access="access-token", access_expires_at=1234567890,
        refresh="refresh-token", refresh_expires_at=1234567890,
        device_id="d1", token_type="Bearer",
    )

    @patch("accounts.views.AuthenticationService.login")
    def test_login_with_email(self, mock_login):
        mock_login.return_value = self.mock_result
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "password": "password123",
        }, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["token_type"] == "Bearer"
        mock_login.assert_called_once_with(
            email="a@b.com", username=None, phone_number=None,
            password="password123", device_payload=None, ip_address=ANY,
        )

    @patch("accounts.views.AuthenticationService.login")
    def test_login_with_username(self, mock_login):
        mock_login.return_value = self.mock_result
        resp = APIClient().post(self.url, {
            "username": "smithEze", "password": "password123",
        }, format="json")
        assert resp.status_code == 200
        mock_login.assert_called_once_with(
            email=None, username="smithEze", phone_number=None,
            password="password123", device_payload=None, ip_address=ANY,
        )

    @patch("accounts.views.AuthenticationService.login")
    def test_login_with_phone(self, mock_login):
        mock_login.return_value = self.mock_result
        resp = APIClient().post(self.url, {
            "phone_number": "+2348012345678", "password": "password123",
        }, format="json")
        assert resp.status_code == 200
        mock_login.assert_called_once_with(
            email=None, username=None, phone_number="+2348012345678",
            password="password123", device_payload=None, ip_address=ANY,
        )

    @patch("accounts.views.AuthenticationService.login")
    def test_login_with_device(self, mock_login):
        mock_login.return_value = self.mock_result
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "password": "password123",
            "device": {"platform": "ios", "device_fingerprint": "fp123"},
        }, format="json")
        assert resp.status_code == 200
        mock_login.assert_called_once_with(
            email="a@b.com", username=None, phone_number=None,
            password="password123", device_payload={
                "platform": "ios", "device_fingerprint": "fp123"},
            ip_address=ANY,
        )

    @patch("accounts.views.AuthenticationService.login")
    def test_login_auth_error(self, mock_login):
        from accounts.services.exceptions import AuthenticationError
        mock_login.side_effect = AuthenticationError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "password": "wrong",
        }, format="json")
        assert resp.status_code == 401

    @patch("accounts.views.AuthenticationService.login")
    def test_login_account_locked(self, mock_login):
        from accounts.services.exceptions import AccountLockedError
        mock_login.side_effect = AccountLockedError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "password": "password123",
        }, format="json")
        assert resp.status_code == 423

    @patch("accounts.views.AuthenticationService.login")
    def test_login_account_inactive(self, mock_login):
        from accounts.services.exceptions import AccountInactiveError
        mock_login.side_effect = AccountInactiveError()
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "password": "password123",
        }, format="json")
        assert resp.status_code == 403

    def test_login_no_identifier(self):
        resp = APIClient().post(self.url, {"password": "password123"}, format="json")
        assert resp.status_code == 400
        assert "identifier_required" in str(resp.data)

    def test_login_empty_body(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 400


class TestLogoutView:
    url = f"{API_ROOT}auth/logout/"

    def test_logout_unauthenticated(self):
        resp = APIClient().post(self.url, {"refresh": "x"}, format="json")
        assert resp.status_code == 401

    @patch("accounts.views.AuthenticationService.logout")
    def test_logout_success(self, mock_logout):
        user = User.objects.create_user(
            email="logout@test.com", username="logoutuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
        resp = client.post(self.url, {"refresh": "test-refresh"}, format="json")
        assert resp.status_code == 200



class TestLogoutEverywhereView:
    url = f"{API_ROOT}auth/logout-everywhere/"

    def test_logout_everywhere_success(self):
        user = User.objects.create_user(
            email="everywhere@test.com", username="everyuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["sessions_revoked"] >= 0

    def test_logout_everywhere_unauthenticated(self):
        resp = APIClient().post(self.url, format="json")
        assert resp.status_code == 401


class TestTokenRefreshView:
    url = f"{API_ROOT}auth/token/refresh/"

    @patch("accounts.views.TokenService.refresh")
    def test_refresh_success(self, mock_refresh):
        mock_refresh.return_value = {
            "access": "new-access", "refresh": "new-refresh", "token_type": "Bearer",
        }
        resp = APIClient().post(self.url, {"refresh": "old-refresh"}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["access"] == "new-access"

    def test_refresh_missing_token(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 400


class TestPasswordResetRequestView:
    url = f"{API_ROOT}auth/password/reset/"

    @patch("accounts.views.PasswordService.request_reset")
    def test_reset_request_with_email(self, mock_request):
        mock_request.return_value = MagicMock()
        resp = APIClient().post(self.url, {"email": "a@b.com"}, format="json")
        assert resp.status_code == 200
        assert "If that email or phone number" in resp.data["message"]
        mock_request.assert_called_once_with(
            email="a@b.com", phone_number=None, ip_address=ANY,
        )

    @patch("accounts.views.PasswordService.request_reset")
    def test_reset_request_with_phone(self, mock_request):
        mock_request.return_value = MagicMock()
        resp = APIClient().post(self.url, {"phone_number": "+2348012345678"}, format="json")
        assert resp.status_code == 200
        mock_request.assert_called_once_with(
            email=None, phone_number="+2348012345678", ip_address=ANY,
        )

    def test_reset_request_no_identifier(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 400



class TestPasswordResetConfirmView:
    url = f"{API_ROOT}auth/password/reset/confirm/"

    @patch("accounts.views.PasswordService.confirm_reset")
    def test_confirm_with_email(self, mock_confirm):
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "code": "123456", "new_password": "NewStr0ng!",
        }, format="json")
        assert resp.status_code == 200
        mock_confirm.assert_called_once_with(
            email="a@b.com", phone_number=None,
            code="123456", new_password="NewStr0ng!",
        )

    @patch("accounts.views.PasswordService.confirm_reset")
    def test_confirm_with_phone(self, mock_confirm):
        resp = APIClient().post(self.url, {
            "phone_number": "+2348012345678", "code": "123456", "new_password": "NewStr0ng!",
        }, format="json")
        assert resp.status_code == 200
        mock_confirm.assert_called_once_with(
            email=None, phone_number="+2348012345678",
            code="123456", new_password="NewStr0ng!",
        )

    def test_confirm_no_identifier(self):
        resp = APIClient().post(self.url, {"code": "123456", "new_password": "NewStr0ng!"}, format="json")
        assert resp.status_code == 400

    def test_confirm_empty_body(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 400



class TestPasswordChangeView:
    url = f"{API_ROOT}auth/password/change/"

    def test_change_success(self):
        user = User.objects.create_user(
            email="changepw@test.com", username="changepwuser",
            password="OldStr0ng!", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {
            "current_password": "OldStr0ng!",
            "new_password": "NewStr0ng!2",
        }, format="json")
        assert resp.status_code == 200

    def test_change_unauthenticated(self):
        resp = APIClient().post(self.url, {
            "current_password": "old", "new_password": "new",
        }, format="json")
        assert resp.status_code == 401



class TestMeView:
    url = f"{API_ROOT}me/"

    def test_me_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_me_success(self):
        user = User.objects.create_user(
            email="me@test.com", username="meuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        assert resp.status_code == 200
        assert resp.data["data"]["email"] == "me@test.com"

    def test_me_returns_cached_response_on_repeat_request(self):
        user = User.objects.create_user(
            email="cached@test.com", username="cacheduser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp1 = client.get(self.url)
        resp2 = client.get(self.url)
        assert resp1.data == resp2.data

    def test_me_cache_key_exists_after_first_request(self):
        user = User.objects.create_user(
            email="key@test.com", username="keyuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.get(self.url)
        assert cache.get(make_user_me_cache_key(str(user.pk))) is not None

    def test_me_cache_invalidated_on_user_update(self):
        user = User.objects.create_user(
            email="old@test.com", username="olduser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp1 = client.get(self.url)
        assert resp1.data["data"]["email"] == "old@test.com"
        user.email = "new@test.com"
        user.save()
        resp2 = client.get(self.url)
        assert resp2.data["data"]["email"] == "new@test.com"

    def test_me_cache_invalidated_on_profile_change(self):
        user = User.objects.create_user(
            email="profile@test.com", username="profileuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.get(self.url)
        profile = UserProfile.objects.get(user=user)
        profile.display_name = "Changed"
        profile.save()
        assert cache.get(make_user_me_cache_key(str(user.pk))) is None

    def test_me_cache_is_per_user(self):
        user1 = User.objects.create_user(
            email="u1@test.com", username="userone", password="pass", is_active=True,
        )
        user2 = User.objects.create_user(
            email="u2@test.com", username="usertwo", password="pass", is_active=True,
        )
        client1 = APIClient()
        client1.force_authenticate(user=user1)
        client2 = APIClient()
        client2.force_authenticate(user=user2)
        resp1 = client1.get(self.url)
        resp2 = client2.get(self.url)
        assert resp1.data["data"]["email"] == "u1@test.com"
        assert resp2.data["data"]["email"] == "u2@test.com"


# ─────────────────────────────────────────────────────────────────────────────
#  ProfileView
# ─────────────────────────────────────────────────────────────────────────────


class TestProfileView:
    url = f"{API_ROOT}me/profile/"

    def test_get_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_get_success(self):
        user = User.objects.create_user(
            email="prof@test.com", username="profuser", password="pass", is_active=True,
        )
        UserProfile.objects.get_or_create(user=user)
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        assert resp.status_code == 200
        assert resp.data["data"]["user"]["email"] == "prof@test.com"

    def test_patch_success(self):
        user = User.objects.create_user(
            email="patchprof@test.com", username="patchprof", password="pass", is_active=True,
        )
        UserProfile.objects.get_or_create(user=user)
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.patch(self.url, {"display_name": "New Name"}, format="json")
        assert resp.status_code == 200

    def test_patch_unauthenticated(self):
        resp = APIClient().patch(self.url, {"display_name": "x"}, format="json")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
#  ProfileAvatarUpdateView & ProfileCoverUpdateView
# ─────────────────────────────────────────────────────────────────────────────


class TestProfileAvatarView:
    url = f"{API_ROOT}me/profile/avatar/"

    def test_put_unauthenticated(self):
        resp = APIClient().put(self.url, {}, format="multipart")
        assert resp.status_code == 401

    def test_delete_unauthenticated(self):
        resp = APIClient().delete(self.url)
        assert resp.status_code == 401

    def test_delete_success(self):
        user = User.objects.create_user(
            email="avatar@test.com", username="avataruser", password="pass", is_active=True,
        )
        UserProfile.objects.get_or_create(user=user)
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.delete(self.url)
        assert resp.status_code == 200


class TestProfileCoverView:
    url = f"{API_ROOT}me/profile/cover/"

    def test_put_unauthenticated(self):
        resp = APIClient().put(self.url, {}, format="multipart")
        assert resp.status_code == 401

    def test_delete_unauthenticated(self):
        resp = APIClient().delete(self.url)
        assert resp.status_code == 401

    def test_delete_success(self):
        user = User.objects.create_user(
            email="cover@test.com", username="coveruser", password="pass", is_active=True,
        )
        UserProfile.objects.get_or_create(user=user)
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.delete(self.url)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
#  DeviceListCreateView
# ─────────────────────────────────────────────────────────────────────────────


class TestDeviceListCreateView:
    url = f"{API_ROOT}me/devices/"

    def test_get_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_get_success(self):
        user = User.objects.create_user(
            email="dev@test.com", username="devuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        assert resp.status_code == 200

    def test_post_success(self):
        user = User.objects.create_user(
            email="devpost@test.com", username="devpostuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {
            "platform": "ios",
            "device_fingerprint": "fp123",
        }, format="json")
        assert resp.status_code == 201

    def test_post_unauthenticated(self):
        resp = APIClient().post(self.url, {
            "platform": "ios", "device_fingerprint": "fp123",
        }, format="json")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
#  DeviceDetailView
# ─────────────────────────────────────────────────────────────────────────────


class TestDeviceDetailView:
    url_template = f"{API_ROOT}me/devices/{{device_id}}/"

    def test_delete_unauthenticated(self):
        resp = APIClient().delete(
            self.url_template.format(device_id="00000000-0000-0000-0000-000000000001"),
        )
        assert resp.status_code == 401

    def test_delete_success(self):
        user = User.objects.create_user(
            email="devdet@test.com", username="devdetuser", password="pass", is_active=True,
        )
        device = UserDevice.objects.create(
            user=user, platform="ios", device_fingerprint="fp123",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.delete(self.url_template.format(device_id=device.pk))
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
#  DevicePushTokenView
# ─────────────────────────────────────────────────────────────────────────────


class TestDevicePushTokenView:
    url_template = f"{API_ROOT}me/devices/{{device_id}}/push-token/"

    def test_post_unauthenticated(self):
        resp = APIClient().post(
            self.url_template.format(device_id="00000000-0000-0000-0000-000000000001"),
            {"push_token": "tok123"}, format="json",
        )
        assert resp.status_code == 401

    def test_post_success(self):
        user = User.objects.create_user(
            email="pushtok@test.com", username="pushtokuser", password="pass", is_active=True,
        )
        device = UserDevice.objects.create(
            user=user, platform="ios", device_fingerprint="fp123",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            self.url_template.format(device_id=device.pk),
            {"push_token": "tok123"}, format="json",
        )
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
#  DeviceTrustView
# ─────────────────────────────────────────────────────────────────────────────


class TestDeviceTrustView:
    url_template = f"{API_ROOT}me/devices/{{device_id}}/trust/"

    def test_post_unauthenticated(self):
        resp = APIClient().post(
            self.url_template.format(device_id="00000000-0000-0000-0000-000000000001"),
        )
        assert resp.status_code == 401

    def test_post_success(self):
        user = User.objects.create_user(
            email="trust@test.com", username="trustuser", password="pass", is_active=True,
        )
        device = UserDevice.objects.create(
            user=user, platform="ios", device_fingerprint="fp123",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url_template.format(device_id=device.pk))
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
#  ConnectDiscoveryView
# ─────────────────────────────────────────────────────────────────────────────


class TestConnectDiscoveryView:
    url = f"{API_ROOT}connect/discover/"

    def test_get_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    @patch("accounts.views.ConnectService.get_discoverable_users")
    def test_get_success(self, mock_discover):
        user = User.objects.create_user(
            email="disc@test.com", username="discuser", password="pass", is_active=True,
        )
        mock_discover.return_value = User.objects.none()
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        assert resp.status_code == 200

    @patch("accounts.views.ConnectService.get_discoverable_users")
    def test_get_with_filters(self, mock_discover):
        user = User.objects.create_user(
            email="discfilt@test.com", username="discfiltuser", password="pass", is_active=True,
        )
        mock_discover.return_value = User.objects.none()
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url, {"distance_km": "50", "city": "Paris"})
        assert resp.status_code == 200
        mock_discover.assert_called_once_with(user, {
            "distance_km": 50.0, "city": "Paris",
        })


# ─────────────────────────────────────────────────────────────────────────────
#  ConnectRequestView
# ─────────────────────────────────────────────────────────────────────────────


class TestConnectRequestView:
    url_template = f"{API_ROOT}connect/request/{{user_id}}/"

    def test_post_unauthenticated(self):
        resp = APIClient().post(
            self.url_template.format(user_id="00000000-0000-0000-0000-000000000001"),
        )
        assert resp.status_code == 401

    @patch("accounts.views.async_send_connection_request.delay")
    def test_post_success(self, mock_delay):
        user = User.objects.create_user(
            email="req@test.com", username="requser", password="pass", is_active=True,
        )
        target = User.objects.create_user(
            email="target@test.com", username="targetuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url_template.format(user_id=target.pk))
        assert resp.status_code == 202
        mock_delay.assert_called_once_with(
            requester_id=str(user.id), recipient_id=str(target.id),
        )


# ─────────────────────────────────────────────────────────────────────────────
#  ConnectRespondView
# ─────────────────────────────────────────────────────────────────────────────


class TestConnectRespondView:
    url_template = f"{API_ROOT}connect/respond/{{connection_id}}/"

    def test_post_unauthenticated(self):
        resp = APIClient().post(
            self.url_template.format(connection_id="00000000-0000-0000-0000-000000000001"),
            {"action": "accept"}, format="json",
        )
        assert resp.status_code == 401

    @patch("accounts.views.async_respond_to_connection.delay")
    def test_post_accept(self, mock_delay):
        user = User.objects.create_user(
            email="resp@test.com", username="respuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            self.url_template.format(connection_id="00000000-0000-0000-0000-000000000001"),
            {"action": "accept"}, format="json",
        )
        assert resp.status_code == 202

    def test_post_invalid_action(self):
        user = User.objects.create_user(
            email="respinv@test.com", username="respinvuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            self.url_template.format(connection_id="00000000-0000-0000-0000-000000000001"),
            {"action": "invalid"}, format="json",
        )
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  UserLocationUpdateView
# ─────────────────────────────────────────────────────────────────────────────


class TestUserLocationUpdateView:
    url = f"{API_ROOT}location/update/"

    def test_post_unauthenticated(self):
        resp = APIClient().post(self.url, {
            "latitude": "48.8566", "longitude": "2.3522",
        }, format="json")
        assert resp.status_code == 401

    @patch("accounts.services.discovery_cache.DiscoveryCache.set_location")
    @patch("accounts.services.discovery_cache.DiscoveryCache.set_metadata")
    @patch("accounts.services.discovery_cache.DiscoveryCache.invalidate_user")
    @patch("accounts.views.process_user_location.delay")
    def test_post_success(self, mock_task, mock_inval, mock_meta, mock_loc):
        user = User.objects.create_user(
            email="loc@test.com", username="locuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {
            "latitude": "48.8566", "longitude": "2.3522",
        }, format="json")
        assert resp.status_code == 202
        uid = str(user.id)
        mock_loc.assert_called_once_with(uid, 48.8566, 2.3522)
        mock_task.assert_called_once_with(
            user_id=uid, latitude="48.8566", longitude="2.3522", ip_address=ANY,
        )

    def test_post_invalid_coords(self):
        user = User.objects.create_user(
            email="locinv@test.com", username="locinvuser", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {
            "latitude": "not-a-number", "longitude": "2.3522",
        }, format="json")
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  UserListView
# ─────────────────────────────────────────────────────────────────────────────


class TestUserListView:
    url = f"{API_ROOT}users/"

    def test_get_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_get_returns_active_users(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url)
        assert resp.status_code == 200
        assert resp.data["status"] is True
        usernames = {u["username"] for u in resp.data["data"]}
        assert "viewer" in usernames

    def test_get_excludes_inactive_and_deleted(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        User.objects.create_user(
            email="u1@t.com", username="activeuser", password="pass", is_active=True,
        )
        User.objects.create_user(
            email="u2@t.com", username="inactiveuser", password="pass", is_active=False,
        )
        deleted = User.objects.create_user(
            email="u3@t.com", username="deleteduser", password="pass", is_active=True,
        )
        deleted.is_deleted = True
        deleted.save()

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url)
        usernames = {u["username"] for u in resp.data["data"]}
        assert "activeuser" in usernames
        assert "inactiveuser" not in usernames
        assert "deleteduser" not in usernames

    def test_includes_profile_fields(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        user = User.objects.create_user(
            email="u@t.com", username="johndoe", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(
            user=user, defaults={"display_name": "John Doe", "first_name": "John", "last_name": "Doe", "current_city": "Berlin"},
        )

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url)
        data = next(u for u in resp.data["data"] if u["username"] == "johndoe")
        assert data["display_name"] == "John Doe"
        assert data["first_name"] == "John"
        assert data["last_name"] == "Doe"
        assert data["current_city"] == "Berlin"
        assert data["avatar"] is None
        assert data["is_verified"] is False

    def test_search_username_icontains(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        User.objects.create_user(
            email="a@t.com", username="alpha", password="pass", is_active=True,
        )
        User.objects.create_user(
            email="b@t.com", username="beta", password="pass", is_active=True,
        )
        User.objects.create_user(
            email="c@t.com", username="gamma", password="pass", is_active=True,
        )

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url, {"username": "alp"})
        assert resp.status_code == 200
        usernames = {u["username"] for u in resp.data["data"]}
        assert "alpha" in usernames
        assert "beta" not in usernames

    def test_search_email_icontains(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        User.objects.create_user(
            email="john@example.com", username="john", password="pass", is_active=True,
        )
        User.objects.create_user(
            email="jane@example.org", username="jane", password="pass", is_active=True,
        )

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url, {"email": "example.com"})
        usernames = {u["username"] for u in resp.data["data"]}
        assert "john" in usernames
        assert "jane" not in usernames

    def test_search_display_name_icontains(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        u1 = User.objects.create_user(
            email="a@t.com", username="userone", password="pass", is_active=True,
        )
        u2 = User.objects.create_user(
            email="b@t.com", username="usertwo", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=u1, defaults={"display_name": "smithEze Wonderland"})
        UserProfile.objects.update_or_create(user=u2, defaults={"display_name": "Bob Builder"})

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url, {"display_name": "wonder"})
        usernames = {u["username"] for u in resp.data["data"]}
        assert "userone" in usernames
        assert "usertwo" not in usernames

    def test_search_first_name_icontains(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        u1 = User.objects.create_user(
            email="a@t.com", username="smithEze", password="pass", is_active=True,
        )
        u2 = User.objects.create_user(
            email="b@t.com", username="bob", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=u1, defaults={"first_name": "smithEze"})
        UserProfile.objects.update_or_create(user=u2, defaults={"first_name": "Benjamin"})

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url, {"first_name": "ben"})
        usernames = {u["username"] for u in resp.data["data"]}
        assert "bob" in usernames
        assert "smithEze" not in usernames

    def test_search_last_name_icontains(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        u1 = User.objects.create_user(
            email="a@t.com", username="smithEze", password="pass", is_active=True,
        )
        u2 = User.objects.create_user(
            email="b@t.com", username="bob", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=u1, defaults={"last_name": "Smith"})
        UserProfile.objects.update_or_create(user=u2, defaults={"last_name": "Johnson"})

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url, {"last_name": "smith"})
        usernames = {u["username"] for u in resp.data["data"]}
        assert "smithEze" in usernames
        assert "bob" not in usernames

    def test_search_city_icontains(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        u1 = User.objects.create_user(
            email="a@t.com", username="smithEze", password="pass", is_active=True,
        )
        u2 = User.objects.create_user(
            email="b@t.com", username="bob", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=u1, defaults={"current_city": "New York"})
        UserProfile.objects.update_or_create(user=u2, defaults={"current_city": "Los Angeles"})

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url, {"city": "york"})
        usernames = {u["username"] for u in resp.data["data"]}
        assert "smithEze" in usernames
        assert "bob" not in usernames

    def test_combined_filters(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        u1 = User.objects.create_user(
            email="a@test.com", username="smithEze", password="pass", is_active=True,
        )
        u2 = User.objects.create_user(
            email="b@example.com", username="amy", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=u1, defaults={"first_name": "smithEze", "current_city": "Paris"})
        UserProfile.objects.update_or_create(user=u2, defaults={"first_name": "Amy", "current_city": "Paris"})

        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url, {"city": "paris", "first_name": "Al"})
        usernames = {u["username"] for u in resp.data["data"]}
        assert "smithEze" in usernames
        assert "amy" not in usernames


# ─────────────────────────────────────────────────────────────────────────────
#  UserDetailView
# ─────────────────────────────────────────────────────────────────────────────


class TestUserDetailView:
    url_template = f"{API_ROOT}users/{{user_id}}/"

    def test_get_unauthenticated(self):
        resp = APIClient().get(
            self.url_template.format(user_id="00000000-0000-0000-0000-000000000001"),
        )
        assert resp.status_code == 401

    def test_get_success(self):
        user = User.objects.create_user(
            email="u@t.com", username="testuser", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=user, defaults={
            "display_name": "Test User",
            "first_name": "Test",
            "last_name": "User",
            "bio": "Hello world",
            "current_city": "New York",
            "is_verified": True,
        })

        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url_template.format(user_id=user.id))
        assert resp.status_code == 200
        assert resp.data["status"] is True
        assert resp.data["data"]["id"] == str(user.id)
        assert resp.data["data"]["username"] == "testuser"
        assert resp.data["data"]["display_name"] == "Test User"
        assert resp.data["data"]["first_name"] == "Test"
        assert resp.data["data"]["last_name"] == "User"
        assert resp.data["data"]["bio"] == "Hello world"
        assert resp.data["data"]["current_city"] == "New York"
        assert resp.data["data"]["is_verified"] is True

    def test_get_not_found(self):
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(
            self.url_template.format(user_id="00000000-0000-0000-0000-000000000001"),
        )
        assert resp.status_code == 404
        assert resp.data["status"] is False

    def test_get_deleted_user_returns_404(self):
        user = User.objects.create_user(
            email="u@t.com", username="testuser", password="pass", is_active=True,
        )
        user.is_deleted = True
        user.save()

        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self.url_template.format(user_id=user.id))
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  Parametrized auth-required check for all authenticated-only endpoints
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthRequiredViews:
    auth_endpoints = [
        ("GET", f"{API_ROOT}users/"),
        ("GET", f"{API_ROOT}users/00000000-0000-0000-0000-000000000000/"),
        ("GET", f"{API_ROOT}me/"),
        ("GET", f"{API_ROOT}me/profile/"),
        ("PATCH", f"{API_ROOT}me/profile/"),
        ("PUT", f"{API_ROOT}me/profile/avatar/"),
        ("DELETE", f"{API_ROOT}me/profile/avatar/"),
        ("PUT", f"{API_ROOT}me/profile/cover/"),
        ("DELETE", f"{API_ROOT}me/profile/cover/"),
        ("GET", f"{API_ROOT}me/devices/"),
        ("POST", f"{API_ROOT}me/devices/"),
        ("DELETE", f"{API_ROOT}me/devices/00000000-0000-0000-0000-000000000000/"),
        ("POST", f"{API_ROOT}me/devices/00000000-0000-0000-0000-000000000000/push-token/"),
        ("POST", f"{API_ROOT}me/devices/00000000-0000-0000-0000-000000000000/trust/"),
        ("GET", f"{API_ROOT}connect/discover/"),
        ("POST", f"{API_ROOT}connect/request/00000000-0000-0000-0000-000000000000/"),
        ("POST", f"{API_ROOT}connect/respond/00000000-0000-0000-0000-000000000000/"),
        ("POST", f"{API_ROOT}location/update/"),
        ("POST", f"{API_ROOT}auth/logout/"),
        ("POST", f"{API_ROOT}auth/logout-everywhere/"),
        ("POST", f"{API_ROOT}auth/password/change/"),
    ]

    @pytest.mark.parametrize("method,url", auth_endpoints)
    def test_returns_401_when_unauthenticated(self, method, url):
        client = APIClient()
        body = {"action": "accept", "push_token": "x",
                "latitude": "0", "longitude": "0"}
        if method == "GET":
            resp = client.get(url)
        elif method == "POST":
            resp = client.post(url, body, format="json")
        elif method == "PUT":
            resp = client.put(url, body, format="json")
        elif method == "PATCH":
            resp = client.patch(url, body, format="json")
        elif method == "DELETE":
            resp = client.delete(url)
        else:
            raise ValueError(f"Unknown method {method}")
        assert resp.status_code == 401, f"{method} {url} returned {resp.status_code} instead of 401"
