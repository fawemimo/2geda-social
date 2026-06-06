from django.contrib import admin

from notifications.models import (
    Notification,
    NotificationAttachment,
    NotificationBatch,
    NotificationMute,
    NotificationPreference,
)
from utils.admin import BaseModelAdmin, BaseTabularInline


class NotificationAttachmentInline(BaseTabularInline):
    model = NotificationAttachment
    fields = ("attachment_type", "cdn_url", "alt_text", "position")
    ordering = ("position",)


@admin.register(Notification)
class NotificationAdmin(BaseModelAdmin):
    inlines = [NotificationAttachmentInline]
    list_display = (
        "id",
        "recipient",
        "actor",
        "notification_type",
        "category",
        "priority",
        "title",
        "is_read",
        "is_deleted",
        "created_at",
    )
    list_filter = ("notification_type", "category", "priority", "is_read")
    search_fields = ("recipient__username", "actor__username", "title")
    autocomplete_fields = ("recipient", "actor")


@admin.register(NotificationAttachment)
class NotificationAttachmentAdmin(BaseModelAdmin):
    list_display = ("id", "notification", "attachment_type", "cdn_url", "position")
    list_filter = ("attachment_type",)
    search_fields = ("notification__title",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "user",
        "category",
        "in_app_enabled",
        "push_enabled",
        "email_enabled",
    )
    list_filter = ("category", "in_app_enabled", "push_enabled", "email_enabled")
    search_fields = ("user__username",)


@admin.register(NotificationMute)
class NotificationMuteAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "user",
        "mute_type",
        "muted_actor",
        "muted_category",
        "expires_at",
        "created_at",
    )
    list_filter = ("mute_type", "muted_category")
    search_fields = ("user__username", "muted_actor__username")
    autocomplete_fields = ("user", "muted_actor")


@admin.register(NotificationBatch)
class NotificationBatchAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "recipient",
        "group_key",
        "total_count",
        "is_read",
        "last_event_at",
    )
    list_filter = ("is_read",)
    search_fields = ("recipient__username", "group_key")
    autocomplete_fields = ("recipient", "latest_notification")
