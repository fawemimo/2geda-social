from django.contrib import admin
from utils.admin import BaseModelAdmin
from .models import Media, MediaVariant, Collection, CollectionItem

@admin.register(Media)
class MediaAdmin(BaseModelAdmin):
    list_display = ("id", "owner", "media_type", "storage_key", "cdn_url", "created_at")
    list_filter = ("media_type", "created_at")
    search_fields = ("owner__email", "original_filename")
    readonly_fields = ("id", "owner", "media_type", "storage_key", "cdn_url", "created_at", "updated_at")


@admin.register(MediaVariant)
class MediaVariantAdmin(BaseModelAdmin):
    list_display = ("id", "media", "label", "storage_key", "cdn_url", "created_at")
    list_filter = ("label", "created_at")
    search_fields = ("media__owner__email", "media__original_filename")
    readonly_fields = ("id", "media", "label", "storage_key", "cdn_url", "created_at", "updated_at")


@admin.register(Collection)
class CollectionAdmin(BaseModelAdmin):
    list_display = ("id", "owner", "name", "created_at")
    list_filter = ("created_at",)
    search_fields = ("owner__email", "name")
    readonly_fields = ("id", "owner", "created_at", "updated_at")

@admin.register(CollectionItem)
class CollectionItemAdmin(BaseModelAdmin):
    list_display = ("id", "collection", "media", "created_at")
    list_filter = ("created_at",)
    search_fields = ("collection__name", "media__original_filename")
    readonly_fields = ("id", "collection", "media", "created_at")

