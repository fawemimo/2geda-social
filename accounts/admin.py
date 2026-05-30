from django.contrib import admin

from accounts.models import KYC, OTP, Connection, PointsRewarding, Referral, User, UserDevice, UserLocation, UserProfile
from utils.admin import BaseModelAdmin

@admin.register(User)
class UserAdmin(BaseModelAdmin):
    list_display = ("id", "email", "username", "is_active", "is_staff", "created_at")
    search_fields = ("email", "username")
    list_filter = ("is_active", "is_staff", "created_at","updated_at")


@admin.register(OTP)
class OTPAdmin(BaseModelAdmin):
    list_display = ("id", "user", "purpose", "channel", "delivery_address", "expires_at", "created_at")
    search_fields = ("user__email", "user__username", "delivery_address")
    list_filter = ("purpose", "channel", "created_at","updated_at")

@admin.register(UserDevice)
class UserDeviceAdmin(BaseModelAdmin):
    list_display = ("id", "user", "name", "platform", "last_seen_at", "last_ip", "is_trusted", "created_at")
    search_fields = ("user__email", "user__username", "name", "platform")
    list_filter = ("platform", "is_trusted", "created_at","updated_at")


@admin.register(UserLocation)
class UserLocationAdmin(BaseModelAdmin):
    list_display = ("id", "user", "latitude", "longitude", "created_at")
    search_fields = ("user__email", "user__username")
    list_filter = ("created_at","updated_at")

@admin.register(Referral)
class ReferralAdmin(BaseModelAdmin): ...


@admin.register(UserProfile)
class UserProfileAdmin(BaseModelAdmin):
    list_display = ("id", "user", "display_name", "bio", "created_at")
    search_fields = ("user__email", "user__username", "display_name")
    list_filter = ("created_at","updated_at")


@admin.register(KYC)
class KYCAdmin(BaseModelAdmin):
    list_display = ("id", "user", "status", "created_at")
    search_fields = ("user__email", "user__username")
    list_filter = ("status", "created_at","updated_at") 

@admin.register(PointsRewarding)
class PointsRewardingAdmin(BaseModelAdmin):
    list_display = ("id", "user", "points", "reason", "source", "is_claimed", "created_at")
    search_fields = ("user__email", "user__username")
    list_filter = ("is_claimed", "created_at","updated_at") 

@admin.register(Connection)
class ConnectionAdmin(BaseModelAdmin): ...
