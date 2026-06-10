from django.contrib import admin

from displays.models import Display, DisplayComment, DisplayLike, DisplayView
from utils.admin import BaseModelAdmin


@admin.register(Display)
class DisplayAdmin(BaseModelAdmin):
    list_display = ["id", "author", "body_preview", "visibility", "expires_at", "views_count", "created_at", "is_deleted"]
    list_filter = ["visibility", "is_deleted", "expires_at"]
    search_fields = ["author__username", "author__email", "body"]
    date_hierarchy = "created_at"
    raw_id_fields = ["author", "media"]

    def body_preview(self, obj):
        return (obj.body or "")[:60]
    body_preview.short_description = "body"


@admin.register(DisplayComment)
class DisplayCommentAdmin(BaseModelAdmin):
    list_display = ["id", "display", "author", "body_preview", "created_at"]
    raw_id_fields = ["display", "author"]

    def body_preview(self, obj):
        return (obj.body or "")[:60]
    body_preview.short_description = "body"


@admin.register(DisplayLike)
class DisplayLikeAdmin(BaseModelAdmin):
    list_display = ["id", "display", "user", "created_at"]
    raw_id_fields = ["display", "user"]


@admin.register(DisplayView)
class DisplayViewAdmin(BaseModelAdmin):
    list_display = ["id", "display", "user", "created_at"]
    raw_id_fields = ["display", "user"]
