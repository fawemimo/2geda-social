from django.contrib import admin

from social.models import Comment, Like, Post, PostMedia, Reshare
from utils.admin import BaseModelAdmin, BaseTabularInline


class PostMediaInline(BaseTabularInline):
    model = PostMedia
    fields = ("media", "position")
    autocomplete_fields = ("media",)
    ordering = ("position",)


class CommentInline(BaseTabularInline):
    model = Comment
    fk_name = "post"
    fields = ("author", "body", "likes_count", "created_at")
    readonly_fields = ("id", "author", "body", "likes_count", "created_at")
    can_delete = False
    extra = 0
    ordering = ("-created_at",)
    max_num = 20

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Post)
class PostAdmin(BaseModelAdmin):
    inlines = [PostMediaInline, CommentInline]
    list_display = (
        "id",
        "author",
        "body",
        "visibility",
        "likes_count",
        "comments_count",
        "reshares_count",
        "is_deleted",
        "created_at",
    )
    search_fields = ("author__email", "author__username", "body")
    list_filter = ("visibility",)
    autocomplete_fields = ("author", "reshare_of")


@admin.register(PostMedia)
class PostMediaAdmin(BaseModelAdmin):
    list_display = ("id", "post", "media", "position")
    search_fields = ("post__author__email",)
    autocomplete_fields = ("post", "media")
    ordering = ("post", "position")


@admin.register(Comment)
class CommentAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "post",
        "author",
        "parent",
        "body",
        "likes_count",
        "replies_count",
        "is_deleted",
        "created_at",
    )
    search_fields = ("author__email", "author__username", "body")
    list_filter = ("post",)
    autocomplete_fields = ("post", "author", "parent")


@admin.register(Like)
class LikeAdmin(BaseModelAdmin):
    list_display = ("id", "user", "content_type", "object_id", "created_at")
    search_fields = ("user__email", "user__username")
    list_filter = ("content_type",)


@admin.register(Reshare)
class ReshareAdmin(BaseModelAdmin):
    list_display = ("id", "user", "original_post", "reshare_post", "created_at")
    search_fields = ("user__email", "user__username")
    autocomplete_fields = ("user", "original_post", "reshare_post")
