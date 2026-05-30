from __future__ import annotations

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from accounts.models import User, UserDevice, UserProfile
from utils.enum import DevicePlatform


class DevicePayloadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    platform = serializers.ChoiceField(choices=DevicePlatform.choices(), required=True)
    device_fingerprint = serializers.CharField(max_length=256, required=True)
    os_version = serializers.CharField(max_length=30, required=False, allow_blank=True)
    app_version = serializers.CharField(max_length=20, required=False, allow_blank=True)
    push_token = serializers.CharField(required=False, allow_blank=True)


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.CharField(max_length=40)
    password = serializers.CharField(min_length=8, write_only=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    referral_code = serializers.CharField(max_length=12, required=False, allow_blank=True)


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=4, max_length=10)
    device = DevicePayloadSerializer(required=False)


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    purpose = serializers.CharField(max_length=20, required=False)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    device = DevicePayloadSerializer(required=False)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=4, max_length=10)
    new_password = serializers.CharField(min_length=8, write_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=8, write_only=True)


class ProfileImageUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class ProfileUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=40, required=False)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    display_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True)
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

