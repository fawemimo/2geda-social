from __future__ import annotations

import os

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from accounts.models import User, UserDevice, UserProfile
from utils import images
from utils.enum import DevicePlatform


class DevicePayloadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    platform = serializers.ChoiceField(choices=DevicePlatform.choices(), required=True)
    device_fingerprint = serializers.CharField(max_length=256, required=True)
    os_version = serializers.CharField(max_length=30, required=False, allow_blank=True)
    app_version = serializers.CharField(max_length=20, required=False, allow_blank=True)
    push_token = serializers.CharField(required=False, allow_blank=True)


#: How the caller may ask for a phone OTP. Omitting it means "no preference",
#: which resolves to WhatsApp with SMS as the fallback.
OTP_CHANNEL_CHOICES = ("whatsapp", "sms")


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    username = serializers.CharField(max_length=40)
    password = serializers.CharField(min_length=8, write_only=True)
    referral_code = serializers.CharField(max_length=12, required=False, allow_blank=True)
    channel = serializers.ChoiceField(
        choices=OTP_CHANNEL_CHOICES,
        required=False,
        allow_blank=True,
        help_text="Preferred phone OTP channel. Defaults to WhatsApp, falls back to SMS.",
    )

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone_number"):
            raise serializers.ValidationError(
                "Either email or phone_number is required.", code="identifier_required"
            )
        return attrs


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    code = serializers.CharField(min_length=4, max_length=10)
    device = DevicePayloadSerializer(required=False)

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone_number"):
            raise serializers.ValidationError(
                "Either email or phone_number is required.", code="identifier_required"
            )
        return attrs


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    purpose = serializers.CharField(max_length=20, required=False)
    channel = serializers.ChoiceField(
        choices=OTP_CHANNEL_CHOICES,
        required=False,
        allow_blank=True,
        help_text="Preferred phone OTP channel. Defaults to WhatsApp, falls back to SMS.",
    )

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone_number"):
            raise serializers.ValidationError(
                "Either email or phone_number is required.", code="identifier_required"
            )
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    username = serializers.CharField(max_length=40, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)
    device = DevicePayloadSerializer(required=False)

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("username") and not attrs.get("phone_number"):
            raise serializers.ValidationError(
                "Either email, username, or phone_number is required.", code="identifier_required"
            )
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone_number"):
            raise serializers.ValidationError(
                "Either email or phone_number is required.", code="identifier_required"
            )
        return attrs


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    code = serializers.CharField(min_length=4, max_length=10)
    new_password = serializers.CharField(min_length=8, write_only=True)

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone_number"):
            raise serializers.ValidationError(
                "Either email or phone_number is required.", code="identifier_required"
            )
        return attrs


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=8, write_only=True)


class ProfileImageUploadSerializer(serializers.Serializer):
    """Profile pictures only — the payload must be a real, decodable image.

    `ImageField` makes Pillow verify the bytes, so a renamed `.jpg` that is
    really a PDF (or a script) is rejected here rather than in the worker.
    """

    file = serializers.ImageField()

    def validate_file(self, value):
        # Size first: it is free, and it short-circuits before any decode.
        if value.size > images.MAX_UPLOAD_BYTES:
            raise serializers.ValidationError(
                f"Image must be {images.MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller."
            )
        if not value.size:
            raise serializers.ValidationError("Uploaded file is empty.")

        ext = os.path.splitext(getattr(value, "name", "") or "")[1].lower()
        if ext and ext not in images.ALLOWED_EXTENSIONS:
            raise serializers.ValidationError(
                f"Unsupported image type '{ext}'. Allowed: "
                f"{', '.join(sorted(images.ALLOWED_EXTENSIONS))}."
            )

        # Header-only probe — confirms the real format and guards against
        # decompression bombs without decoding the full raster.
        value.seek(0)
        try:
            images.probe(value.read())
        except images.ImageValidationError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        finally:
            value.seek(0)

        return value


class ProfileUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=30, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=30, required=False, allow_blank=True)
    username = serializers.CharField(max_length=40, required=False)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    display_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True)
    work = serializers.CharField(max_length=100, required=False, allow_blank=True)
    current_city = serializers.CharField(max_length=50, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False)
    is_private = serializers.BooleanField(required=False)


class UserMeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id", "email", "username", "phone_number",
            "is_active", "is_email_verified", "is_phone_verified",
            "referral_code", "created_at",
        )
        read_only_fields = fields


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserMeSerializer(read_only=True)
    avatar = serializers.CharField(source="avatar.cdn_url", read_only=True, allow_null=True)
    cover_photo = serializers.CharField(source="cover_photo.cdn_url", read_only=True, allow_null=True)

    class Meta:
        model = UserProfile
        fields = (
            "user", "display_name", "bio", "website", "date_of_birth",
            "is_private", "is_verified", "followers_count", "following_count",
            "posts_count", "avatar", "cover_photo",
        )
        read_only_fields = (
            "user", "is_verified", "followers_count", "following_count", "posts_count",
            "avatar", "cover_photo",
        )


class UserDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserDevice
        fields = (
            "id", "name", "platform", "os_version", "app_version",
            "is_trusted", "last_seen_at", "last_ip", "created_at",
        )
        read_only_fields = fields


class PushTokenUpdateSerializer(serializers.Serializer):
    push_token = serializers.CharField()

# Response shape returned by /auth/token/refresh/.

class TokenObtainPairResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    token_type = serializers.CharField()

# Custom claims for SimpleJWT-issued tokens.

class UserTokenObtainPairSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["username"] = user.username
        token["email"] = user.email
        return token


class ConnectFilterSerializer(serializers.Serializer):
    distance_km = serializers.FloatField(required=False, min_value=0.0, default=300.0)
    city = serializers.CharField(required=False, allow_blank=True)
    state = serializers.CharField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True)


class ConnectUserSerializer(serializers.ModelSerializer):
    distance_km = serializers.FloatField(read_only=True, required=False)
    city = serializers.CharField(source='loc_city', read_only=True, required=False)
    state = serializers.CharField(source='loc_state', read_only=True, required=False)
    display_name = serializers.CharField(source='profile.display_name', read_only=True)
    avatar = serializers.StringRelatedField(source='profile.avatar', read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "display_name", "avatar", "distance_km", "city", "state")

class ConnectRespondSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["accept", "reject"])


class UserLocationIngestSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=True)


class UserListSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source="profile.display_name", read_only=True, default="")
    first_name = serializers.CharField(source="profile.first_name", read_only=True, default="")
    last_name = serializers.CharField(source="profile.last_name", read_only=True, default="")
    current_city = serializers.CharField(source="profile.current_city", read_only=True, default="")
    avatar = serializers.CharField(source="profile.avatar.cdn_url", read_only=True, default=None)
    is_verified = serializers.BooleanField(source="profile.is_verified", read_only=True, default=False)

    class Meta:
        model = User
        fields = [
            "id", "username", "email",
            "display_name", "first_name", "last_name",
            "current_city", "avatar", "is_verified",
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source="profile.display_name", read_only=True, default="")
    first_name = serializers.CharField(source="profile.first_name", read_only=True, default="")
    last_name = serializers.CharField(source="profile.last_name", read_only=True, default="")
    bio = serializers.CharField(source="profile.bio", read_only=True, default="")
    website = serializers.URLField(source="profile.website", read_only=True, default="")
    work = serializers.CharField(source="profile.work", read_only=True, default="")
    current_city = serializers.CharField(source="profile.current_city", read_only=True, default="")
    date_of_birth = serializers.DateField(source="profile.date_of_birth", read_only=True, default=None)
    is_private = serializers.BooleanField(source="profile.is_private", read_only=True, default=False)
    is_verified = serializers.BooleanField(source="profile.is_verified", read_only=True, default=False)
    followers_count = serializers.IntegerField(source="profile.followers_count", read_only=True, default=0)
    following_count = serializers.IntegerField(source="profile.following_count", read_only=True, default=0)
    posts_count = serializers.IntegerField(source="profile.posts_count", read_only=True, default=0)
    avatar = serializers.CharField(source="profile.avatar.cdn_url", read_only=True, default=None)
    cover_photo = serializers.CharField(source="profile.cover_photo.cdn_url", read_only=True, default=None)
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email",
            "display_name", "first_name", "last_name",
            "bio", "website", "work", "current_city", "date_of_birth",
            "is_private", "is_verified",
            "followers_count", "following_count", "posts_count",
            "avatar", "cover_photo", "is_online",
        ]

    def get_is_online(self, obj) -> bool:
        from django.core.cache import cache
        return cache.get(f"online_user:{obj.id}") is not None

