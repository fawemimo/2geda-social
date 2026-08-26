from django.contrib import admin

from advertisements.models import (
    AdCreative,
    AdDailyMetric,
    AdEvent,
    AdPlacement,
    Advertisement,
)
from utils.admin import BaseModelAdmin


class AdCreativeInline(admin.TabularInline):
    model = AdCreative
    extra = 0
    fields = ["media", "headline", "caption", "alt_text", "position"]


class AdPlacementInline(admin.TabularInline):
    model = AdPlacement
    extra = 0
    fields = [
        "mode", "screen_position", "display_seconds",
        "is_skippable", "skip_after_seconds", "show_every_n",
    ]


@admin.register(Advertisement)
class AdvertisementAdmin(BaseModelAdmin):
    list_display = [
        "title", "advertiser", "status", "starts_at", "ends_at",
        "impressions_count", "clicks_count", "amount_spent",
    ]
    list_filter = ["status", "objective", "pricing_model"]
    search_fields = ["title", "caption", "advertiser__username"]
    inlines = [AdCreativeInline, AdPlacementInline]
    readonly_fields = [
        "impressions_count", "clicks_count", "conversions_count", "amount_spent",
        "activated_at", "completed_at", "reviewed_at",
    ]


@admin.register(AdEvent)
class AdEventAdmin(admin.ModelAdmin):
    list_display = ["advertisement", "event_type", "user", "created_at"]
    list_filter = ["event_type"]
    readonly_fields = [f.name for f in AdEvent._meta.fields]


@admin.register(AdDailyMetric)
class AdDailyMetricAdmin(admin.ModelAdmin):
    list_display = ["advertisement", "date", "impressions", "clicks", "spend"]
    list_filter = ["date"]
