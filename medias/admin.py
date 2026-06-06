from django.contrib import admin

from medias.models import Collection, CollectionItem, Media, MediaVariant
from utils.admin import BaseModelAdmin, BaseTabularInline


class MediaVariantInline(BaseTabularInline):
    model = MediaVariant
    fields = ("label", "storage_key", "cdn_url", "width_px", "height_px", "file_size_bytes")
    ordering = ("label",)


@admin.register(Media)
class MediaAdmin(BaseModelAdmin):
    inlines = [MediaVariantInline]
    list_display = (
        "id",
        "owner",
        "media_type",
        "original_filename",
        "mime_type",
        "file_size_bytes",
        "processing_status",
        "created_at",
    )
    list_filter = ("media_type", "processing_status", "visibility")
    search_fields = ("owner__email", "original_filename")
    readonly_fields = (
        "id",
        "owner",
        "media_type",
        "storage_key",
        "cdn_url",
        "original_filename",
        "mime_type",
        "file_size_bytes",
        "width_px",
        "height_px",
        "duration_seconds",
        "processing_status",
        "created_at",
        "updated_at",
    )


@admin.register(MediaVariant)
class MediaVariantAdmin(BaseModelAdmin):
    list_display = ("id", "media", "label", "cdn_url", "width_px", "height_px")
    list_filter = ("label",)
    search_fields = ("media__owner__email", "media__original_filename")
    readonly_fields = (
        "id",
        "media",
        "label",
        "storage_key",
        "cdn_url",
        "width_px",
        "height_px",
        "file_size_bytes",
        "created_at",
        "updated_at",
    )


class CollectionItemInline(BaseTabularInline):
    model = CollectionItem
    fields = ("media", "position", "caption")
    ordering = ("position",)


@admin.register(Collection)
class CollectionAdmin(BaseModelAdmin):
    inlines = [CollectionItemInline]
    list_display = (
        "id",
        "owner",
        "name",
        "is_public",
        "items_count",
        "created_at",
    )
    list_filter = ("is_public",)
    search_fields = ("owner__email", "name")
    readonly_fields = ("id", "owner", "items_count", "created_at", "updated_at")


@admin.register(CollectionItem)
class CollectionItemAdmin(BaseModelAdmin):
    list_display = ("id", "collection", "media", "position", "created_at")
    search_fields = ("collection__name", "media__original_filename")
    ordering = ("collection", "position")
