from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import (
    Connection,
    Follow,
    KYC,
    OTP,
    PointsRewarding,
    Referral,
    UserDevice,
    UserLocation,
    UserProfile,
)
from utils.enum import (
    ConnectionStatus,
    DevicePlatform,
    FollowStatus,
    KYCDocumentType,
    KYCStatus,
    OTPChannel,
    OTPPurpose,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


# ─────────────────────────────────────────────────────────────────────────────
#  User
# ─────────────────────────────────────────────────────────────────────────────


class TestUserModel:
    def test_create_user(self):
        user = User.objects.create_user(
            email="smithEze@example.com", username="smithEze", password="securepass123",
        )
        assert user.email == "smithEze@example.com"
        assert user.username == "smithEze"
        assert user.check_password("securepass123")
        assert user.is_active is False
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.referral_code is not None

    def test_create_user_normalizes_email(self):
        user = User.objects.create_user(
            email="smithEze@Example.COM", username="smithEze", password="pass",
        )
        assert user.email == "smithEze@example.com"

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            email="admin@example.com", username="admin", password="adminpass",
        )
        assert admin.is_staff is True
        assert admin.is_superuser is True
        assert admin.is_active is True

    def test_email_unique(self):
        User.objects.create_user(email="dup@test.com", username="u1", password="pass")
        with pytest.raises(IntegrityError):
            User.objects.create_user(email="dup@test.com", username="u2", password="pass")

    def test_username_unique(self):
        User.objects.create_user(email="a@test.com", username="same", password="pass")
        with pytest.raises(IntegrityError):
            User.objects.create_user(email="b@test.com", username="same", password="pass")

    def test_str(self):
        user = User.objects.create_user(
            email="str@test.com", username="struser", password="pass",
        )
        assert str(user) == "str@test.com>>"

    def test_soft_delete(self):
        user = User.objects.create_user(
            email="del@test.com", username="deluser", password="pass",
        )
        user.soft_delete()
        user.refresh_from_db()
        assert user.is_deleted is True
        assert user.is_active is False
        assert user.deleted_at is not None

    def test_active_manager(self):
        active = User.objects.create_user(
            email="active@test.com", username="activeuser", password="pass",
        )
        active.is_active = True
        active.save()
        deleted = User.objects.create_user(
            email="deleted@test.com", username="deleteduser", password="pass",
        )
        deleted.soft_delete()
        qs = User.objects.active()
        assert active in qs
        assert deleted not in qs

    def test_referral_code_auto_generated(self):
        a = User.objects.create_user(email="a@t.com", username="a", password="p")
        b = User.objects.create_user(email="b@t.com", username="b", password="p")
        assert a.referral_code != b.referral_code

    def test_referred_by(self):
        referrer = User.objects.create_user(
            email="ref@t.com", username="ref", password="p",
        )
        referred = User.objects.create_user(
            email="refd@t.com", username="refd", password="p",
            referred_by=referrer,
        )
        assert referred.referred_by == referrer


# ─────────────────────────────────────────────────────────────────────────────
#  OTP
# ─────────────────────────────────────────────────────────────────────────────


class TestOTPModel:
    def test_create_otp(self):
        user = User.objects.create_user(email="otp@t.com", username="otp", password="p")
        otp = OTP.objects.create(
            user=user,
            code_hash="hashed_code",
            purpose=OTPPurpose.REGISTRATION.value,
            delivery_address="otp@t.com",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        assert otp.purpose == "registration"
        assert otp.channel == OTPChannel.EMAIL.value
        assert otp.is_used is False
        assert otp.attempt_count == 0
        assert otp.pk is not None

    def test_is_valid_returns_true_when_active(self):
        user = User.objects.create_user(email="otpvalid@t.com", username="otpv", password="p")
        otp = OTP.objects.create(
            user=user,
            code_hash="h",
            purpose=OTPPurpose.LOGIN.value,
            delivery_address="otpvalid@t.com",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        assert otp.is_valid() is True

    def test_is_valid_returns_false_when_used(self):
        user = User.objects.create_user(email="otpused@t.com", username="otpu", password="p")
        otp = OTP.objects.create(
            user=user,
            code_hash="h",
            purpose=OTPPurpose.LOGIN.value,
            delivery_address="otpused@t.com",
            expires_at=timezone.now() + timedelta(minutes=5),
            is_used=True,
        )
        assert otp.is_valid() is False

    def test_is_valid_returns_false_when_expired(self):
        user = User.objects.create_user(email="otpexp@t.com", username="otpe", password="p")
        otp = OTP.objects.create(
            user=user,
            code_hash="h",
            purpose=OTPPurpose.LOGIN.value,
            delivery_address="otpexp@t.com",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        assert otp.is_valid() is False

    def test_str(self):
        user = User.objects.create_user(email="otpstr@t.com", username="otps", password="p")
        otp = OTP.objects.create(
            user=user,
            code_hash="h",
            purpose=OTPPurpose.PASSWORD_RESET.value,
            delivery_address="otpstr@t.com",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        assert "password_reset" in str(otp)
        assert str(user.pk) in str(otp)


# ─────────────────────────────────────────────────────────────────────────────
#  UserDevice
# ─────────────────────────────────────────────────────────────────────────────


class TestUserDeviceModel:
    def test_create_device(self):
        user = User.objects.create_user(email="dev@t.com", username="dev", password="p")
        device = UserDevice.objects.create(
            user=user,
            platform=DevicePlatform.IOS.value,
            device_fingerprint="fp-unique-123",
        )
        assert device.platform == "ios"
        assert device.is_trusted is False
        assert device.pk is not None
        assert device.created_at is not None

    def test_unique_together_user_and_fingerprint(self):
        user = User.objects.create_user(email="devuniq@t.com", username="devu", password="p")
        UserDevice.objects.create(
            user=user, platform=DevicePlatform.IOS.value, device_fingerprint="fp-1",
        )
        with pytest.raises(IntegrityError):
            UserDevice.objects.create(
                user=user, platform=DevicePlatform.ANDROID.value, device_fingerprint="fp-1",
            )

    def test_revoke(self):
        user = User.objects.create_user(email="devrev@t.com", username="devr", password="p")
        device = UserDevice.objects.create(
            user=user,
            platform=DevicePlatform.WEB.value,
            device_fingerprint="fp-revoke",
            push_token="tok",
            is_trusted=True,
        )
        device.revoke()
        device.refresh_from_db()
        assert device.push_token == ""
        assert device.is_trusted is False
        assert device.is_deleted is True

    def test_str(self):
        user = User.objects.create_user(email="devstr@t.com", username="devs", password="p")
        device = UserDevice.objects.create(
            user=user, platform=DevicePlatform.DESKTOP.value, device_fingerprint="fp-str",
        )
        assert "Desktop" in str(device) or "desktop" in str(device)


# ─────────────────────────────────────────────────────────────────────────────
#  UserLocation
# ─────────────────────────────────────────────────────────────────────────────


class TestUserLocationModel:
    def test_create_location(self):
        user = User.objects.create_user(email="loc@t.com", username="loc", password="p")
        loc = UserLocation.objects.create(
            user=user,
            latitude="48.8566",
            longitude="2.3522",
            ip_address="203.0.113.42",
        )
        assert float(loc.latitude) == 48.8566
        assert float(loc.longitude) == 2.3522
        assert loc.pk is not None

    def test_ordering_newest_first(self):
        user = User.objects.create_user(email="locord@t.com", username="loco", password="p")
        old = UserLocation.objects.create(
            user=user, latitude="0.0", longitude="0.0",
        )
        new = UserLocation.objects.create(
            user=user, latitude="1.0", longitude="1.0",
        )
        qs = UserLocation.objects.all()
        assert qs[0] == new
        assert qs[1] == old

    def test_str(self):
        user = User.objects.create_user(email="locstr@t.com", username="locs", password="p")
        loc = UserLocation.objects.create(
            user=user, latitude="10.0", longitude="20.0",
        )
        assert "10.0" in str(loc)
        assert "20.0" in str(loc)


# ─────────────────────────────────────────────────────────────────────────────
#  Referral
# ─────────────────────────────────────────────────────────────────────────────


class TestReferralModel:
    def test_create_referral(self):
        referrer = User.objects.create_user(email="r1@t.com", username="r1", password="p")
        referred = User.objects.create_user(email="r2@t.com", username="r2", password="p")
        ref = Referral.objects.create(referrer=referrer, referred_user=referred)
        assert ref.reward_granted is False
        assert ref.pk is not None

    def test_one_to_one_referred_user(self):
        referrer = User.objects.create_user(email="r3@t.com", username="r3", password="p")
        a = User.objects.create_user(email="r4@t.com", username="r4", password="p")
        Referral.objects.create(referrer=referrer, referred_user=a)
        with pytest.raises(IntegrityError):
            Referral.objects.create(referrer=referrer, referred_user=a)

    def test_str(self):
        referrer = User.objects.create_user(email="r5@t.com", username="r5", password="p")
        referred = User.objects.create_user(email="r6@t.com", username="r6", password="p")
        ref = Referral.objects.create(referrer=referrer, referred_user=referred)
        assert "r5" in str(ref)
        assert "r6" in str(ref)


# ─────────────────────────────────────────────────────────────────────────────
#  PointsRewarding
# ─────────────────────────────────────────────────────────────────────────────


class TestPointsRewardingModel:
    def test_create_reward(self):
        user = User.objects.create_user(email="pts@t.com", username="pts", password="p")
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(User)
        reward = PointsRewarding.objects.create(
            user=user,
            points=100,
            reason="referral bonus",
            source_content_type=ct,
            source_object_id=user.pk,
        )
        assert reward.points == 100
        assert reward.is_claimed is False
        assert reward.pk is not None

    def test_str(self):
        user = User.objects.create_user(email="ptsstr@t.com", username="ptss", password="p")
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(User)
        reward = PointsRewarding.objects.create(
            user=user,
            points=50,
            reason="login streak",
            source_content_type=ct,
            source_object_id=user.pk,
        )
        assert "50pts" in str(reward)
        assert "login streak" in str(reward)


# ─────────────────────────────────────────────────────────────────────────────
#  UserProfile
# ─────────────────────────────────────────────────────────────────────────────


class TestUserProfileModel:
    def test_auto_created_via_signal(self):
        user = User.objects.create_user(email="prof@t.com", username="prof", password="p")
        assert hasattr(user, "profile")
        assert user.profile is not None

    def test_defaults(self):
        user = User.objects.create_user(email="profdef@t.com", username="profdef", password="p")
        assert user.profile.display_name == ""
        assert user.profile.bio == ""
        assert user.profile.is_private is False
        assert user.profile.is_verified is False
        assert user.profile.followers_count == 0
        assert user.profile.following_count == 0
        assert user.profile.posts_count == 0

    def test_str(self):
        user = User.objects.create_user(email="profstr@t.com", username="profstr", password="p")
        assert str(user.profile) == "Profile(profstr)"


# ─────────────────────────────────────────────────────────────────────────────
#  Follow
# ─────────────────────────────────────────────────────────────────────────────


class TestFollowModel:
    def test_create_follow(self):
        a = User.objects.create_user(email="f1@t.com", username="f1", password="p")
        b = User.objects.create_user(email="f2@t.com", username="f2", password="p")
        follow = Follow.objects.create(follower=a, following=b)
        assert follow.status == FollowStatus.ACCEPTED.value
        assert follow.pk is not None

    def test_unique_together(self):
        a = User.objects.create_user(email="f3@t.com", username="f3", password="p")
        b = User.objects.create_user(email="f4@t.com", username="f4", password="p")
        Follow.objects.create(follower=a, following=b)
        with pytest.raises(IntegrityError):
            Follow.objects.create(follower=a, following=b)

    def test_str(self):
        a = User.objects.create_user(email="f5@t.com", username="f5", password="p")
        b = User.objects.create_user(email="f6@t.com", username="f6", password="p")
        follow = Follow.objects.create(follower=a, following=b, status=FollowStatus.PENDING.value)
        assert "f5" in str(follow)
        assert "f6" in str(follow)
        assert "pending" in str(follow)


# ─────────────────────────────────────────────────────────────────────────────
#  Connection
# ─────────────────────────────────────────────────────────────────────────────


class TestConnectionModel:
    def test_create_connection(self):
        a = User.objects.create_user(email="c1@t.com", username="c1", password="p")
        b = User.objects.create_user(email="c2@t.com", username="c2", password="p")
        conn = Connection.objects.create(requester=a, recipient=b)
        assert conn.status == ConnectionStatus.PENDING.value
        assert conn.pk is not None

    def test_unique_together(self):
        a = User.objects.create_user(email="c3@t.com", username="c3", password="p")
        b = User.objects.create_user(email="c4@t.com", username="c4", password="p")
        Connection.objects.create(requester=a, recipient=b)
        with pytest.raises(IntegrityError):
            Connection.objects.create(requester=a, recipient=b)

    def test_str(self):
        a = User.objects.create_user(email="c5@t.com", username="c5", password="p")
        b = User.objects.create_user(email="c6@t.com", username="c6", password="p")
        conn = Connection.objects.create(requester=a, recipient=b, status=ConnectionStatus.ACCEPTED.value)
        assert "c5" in str(conn)
        assert "c6" in str(conn)
        assert "accepted" in str(conn)


# ─────────────────────────────────────────────────────────────────────────────
#  KYC
# ─────────────────────────────────────────────────────────────────────────────


class TestKYCModel:
    def test_create_kyc_default_status(self):
        user = User.objects.create_user(email="kyc@t.com", username="kyc", password="p")
        kyc = KYC.objects.create(user=user)
        assert kyc.status == KYCStatus.NOT_SUBMITTED.value
        assert kyc.pk is not None

    def test_approve(self):
        user = User.objects.create_user(email="kycapp@t.com", username="kyca", password="p")
        reviewer = User.objects.create_user(email="admin@t.com", username="admin", password="p")
        kyc = KYC.objects.create(user=user)
        kyc.approve(reviewer)
        kyc.refresh_from_db()
        assert kyc.status == KYCStatus.APPROVED.value
        assert kyc.reviewed_by == reviewer
        assert kyc.reviewed_at is not None
        assert kyc.expires_at is not None
        # Signal should also mark profile as verified
        user.profile.refresh_from_db()
        assert user.profile.is_verified is True

    def test_reject(self):
        user = User.objects.create_user(email="kycrej@t.com", username="kycr", password="p")
        reviewer = User.objects.create_user(email="admin2@t.com", username="admin2", password="p")
        kyc = KYC.objects.create(user=user)
        kyc.reject(reviewer, reason="Document illegible")
        kyc.refresh_from_db()
        assert kyc.status == KYCStatus.REJECTED.value
        assert kyc.reviewed_by == reviewer
        assert kyc.rejection_reason == "Document illegible"
        # Signal should mark profile as not verified
        user.profile.refresh_from_db()
        assert user.profile.is_verified is False

    def test_str(self):
        user = User.objects.create_user(email="kycstr@t.com", username="kycs", password="p")
        kyc = KYC.objects.create(user=user, status=KYCStatus.PENDING.value)
        assert "kycs" in str(kyc)
        assert "pending" in str(kyc)
