from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

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
        )

    def test_register_missing_fields(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 400


class TestVerifyRegistrationOTPView:
    url = f"{API_ROOT}auth/verify-otp/"

    @patch("accounts.views.RegistrationService.complete_registration")
    def test_verify_success_without_device(self, mock_complete):
        mock_complete.return_value = MagicMock(
            user_id="u1", email="a@b.com",
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
            user_id=str(user.pk), email="a@b.com",
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



class TestResendOTPView:
    url = f"{API_ROOT}auth/resend-otp/"

    @patch("accounts.tasks.send_otp_email")
    @patch("accounts.views.RegistrationService.resend_registration_otp")
    def test_resend_registration_otp(self, mock_resend, mock_email):
        mock_resend.return_value = MagicMock(
            email="a@b.com",
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


class TestLoginView:
    url = f"{API_ROOT}auth/login/"

    @patch("accounts.views.AuthenticationService.login")
    def test_login_success(self, mock_login):
        mock_login.return_value = MagicMock(
            user_id="u1", access="access-token", access_expires_at=1234567890,
            refresh="refresh-token", refresh_expires_at=1234567890,
            device_id="d1", token_type="Bearer",
        )
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "password": "password123",
        }, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["token_type"] == "Bearer"

    @patch("accounts.views.AuthenticationService.login")
    def test_login_with_device(self, mock_login):
        mock_login.return_value = MagicMock(
            user_id="u1", access="access-token", access_expires_at=1234567890,
            refresh="refresh-token", refresh_expires_at=1234567890,
            device_id="d1", token_type="Bearer",
        )
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "password": "password123",
            "device": {"platform": "ios", "device_fingerprint": "fp123"},
        }, format="json")
        assert resp.status_code == 200

    def test_login_missing_fields(self):
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
    def test_reset_request_success(self, mock_request):
        mock_request.return_value = MagicMock()
        resp = APIClient().post(self.url, {"email": "a@b.com"}, format="json")
        assert resp.status_code == 200
        assert "If that email is registered" in resp.data["message"]

    def test_reset_request_missing_email(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 400



class TestPasswordResetConfirmView:
    url = f"{API_ROOT}auth/password/reset/confirm/"

    @patch("accounts.views.PasswordService.confirm_reset")
    def test_confirm_success(self, mock_confirm):
        resp = APIClient().post(self.url, {
            "email": "a@b.com", "code": "123456", "new_password": "NewStr0ng!",
        }, format="json")
        assert resp.status_code == 200

    def test_confirm_missing_fields(self):
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
#  Parametrized auth-required check for all authenticated-only endpoints
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthRequiredViews:
    auth_endpoints = [
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
