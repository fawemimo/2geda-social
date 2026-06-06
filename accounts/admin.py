from django.contrib import admin

from accounts.models import (
    KYC,
    Connection,
    Follow,
    OTP,
    PointsRewarding,
    Referral,
    User,
    UserDevice,
    UserLocation,
    UserProfile,
)
from utils.admin import BaseModelAdmin, BaseStackedInline


class UserProfileInline(BaseStackedInline):
    model = UserProfile
    can_delete = False
    fields = (
        "first_name",
        "last_name",
        "display_name",
        "bio",
        "website",
        "work",
        "current_city",
        "date_of_birth",
        "display_photo",
        "avatar",
        "cover_photo",
        "is_private",
        "is_verified",
        "followers_count",
        "following_count",
        "posts_count",
    )


@admin.register(User)
class UserAdmin(BaseModelAdmin):
    inlines = [UserProfileInline]
    list_display = (
        "id",
        "email",
        "username",
        "phone_number",
        "is_active",
        "is_staff",
        "is_email_verified",
        "is_phone_verified",
        "created_at",
    )
    search_fields = ("email", "username", "phone_number")
    list_filter = (
        "is_active",
        "is_staff",
        "is_email_verified",
        "is_phone_verified",
    )


@admin.register(OTP)
class OTPAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "user",
        "purpose",
        "channel",
        "delivery_address",
        "expires_at",
        "is_used",
        "created_at",
    )
    search_fields = ("user__email", "user__username", "delivery_address")
    list_filter = ("purpose", "channel", "is_used")


@admin.register(UserDevice)
class UserDeviceAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "user",
        "name",
        "platform",
        "is_trusted",
        "last_seen_at",
        "last_ip",
        "created_at",
    )
    search_fields = ("user__email", "user__username", "name")
    list_filter = ("platform", "is_trusted")


@admin.register(UserLocation)
class UserLocationAdmin(BaseModelAdmin):
    list_display = ("id", "user", "latitude", "longitude", "ip_address", "created_at")
    search_fields = ("user__email", "user__username")


@admin.register(Referral)
class ReferralAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "referrer",
        "referred_user",
        "reward_granted",
        "reward_granted_at",
        "created_at",
    )
    search_fields = ("referrer__email", "referred_user__email", "referrer__username")
    list_filter = ("reward_granted",)


@admin.register(UserProfile)
class UserProfileAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "user",
        "display_name",
        "is_verified",
        "followers_count",
        "following_count",
        "posts_count",
    )
    search_fields = ("user__email", "user__username", "display_name")
    list_filter = ("is_verified", "is_private")


@admin.register(KYC)
class KYCAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "document_type",
        "provider_name",
        "submitted_at",
        "reviewed_at",
    )
    search_fields = ("user__email", "user__username", "provider_reference")
    list_filter = ("status", "document_type", "provider_name")


@admin.register(PointsRewarding)
class PointsRewardingAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "user",
        "points",
        "reason",
        "is_claimed",
        "claimed_at",
        "expires_at",
        "created_at",
    )
    search_fields = ("user__email", "user__username", "reason")
    list_filter = ("is_claimed",)


@admin.register(Connection)
class ConnectionAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "requester",
        "recipient",
        "status",
        "accepted_at",
        "created_at",
    )
    search_fields = (
        "requester__email",
        "recipient__email",
        "requester__username",
        "recipient__username",
    )
    list_filter = ("status",)


@admin.register(Follow)
class FollowAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "follower",
        "following",
        "status",
        "accepted_at",
        "created_at",
    )
    search_fields = (
        "follower__email",
        "following__email",
        "follower__username",
        "following__username",
    )
    list_filter = ("status",)
