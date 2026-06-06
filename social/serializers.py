from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from accounts.models import Follow, User
from accounts.serializers import UserMeSerializer
from medias.models import Media
from social.models import Comment, Like, Post, PostMedia, Reshare
from utils.enum import PostVisibility


class FollowResponseSerializer(serializers.ModelSerializer):
    follower_id = serializers.UUIDField(source="follower.id", read_only=True)
    following_id = serializers.UUIDField(source="following.id", read_only=True)
    follower_username = serializers.CharField(source="follower.username", read_only=True)
    following_username = serializers.CharField(source="following.username", read_only=True)

    class Meta:
        model = Follow
        fields = [
            "id", "follower_id", "following_id",
            "follower_username", "following_username",
            "status", "accepted_at", "created_at",
        ]


# ─────────────────────────────────────────────────────────────────────────────
#  Post serializers
# ─────────────────────────────────────────────────────────────────────────────


class PostMediaSerializer(serializers.ModelSerializer):
    cdn_url = serializers.CharField(source="media.cdn_url", read_only=True, allow_null=True)
    media_type = serializers.CharField(source="media.media_type", read_only=True, allow_null=True)

    class Meta:
        model = PostMedia
        fields = ["id", "cdn_url", "media_type", "position"]


class PostListSerializer(serializers.ModelSerializer):
    author = UserMeSerializer(read_only=True)
    attachments = PostMediaSerializer(many=True, read_only=True)
    is_liked = serializers.SerializerMethodField()
    reshare_of_detail = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id", "author", "body", "visibility",
            "attachments", "is_liked",
            "reshare_of", "reshare_of_detail", "reshare_comment",
            "likes_count", "comments_count", "reshares_count",
            "location_label", "created_at", "updated_at",
        ]

    def get_is_liked(self, obj) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_reshare_of_detail(self, obj):
        if obj.reshare_of_id:
            return PostListSerializer(obj.reshare_of, context=self.context).data
        return None


class PostCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=PostVisibility.choices(),
        default=PostVisibility.PUBLIC.value,
        required=False,
    )
    media_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list,
    )
    reshare_of = serializers.UUIDField(required=False, allow_null=True)
    reshare_comment = serializers.CharField(max_length=500, required=False, allow_blank=True)
    location_label = serializers.CharField(max_length=120, required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)

    def validate_body(self, value):
        if not value and not self.initial_data.get("reshare_of"):
            raise serializers.ValidationError("Body is required when not resharing.")
        return value


class PostUpdateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=PostVisibility.choices(), required=False)
    media_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    location_label = serializers.CharField(max_length=120, required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Comment serializers
# ─────────────────────────────────────────────────────────────────────────────


class CommentSerializer(serializers.ModelSerializer):
    author = UserMeSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id", "post", "author", "parent", "body",
            "likes_count", "replies_count",
            "is_liked", "replies",
            "created_at", "updated_at",
        ]

    def get_is_liked(self, obj) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_replies(self, obj):
        if obj.parent_id:
            return None
        replies = obj.replies.filter(is_deleted=False).order_by("created_at")
        return CommentSerializer(replies, many=True, context=self.context).data


class CommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=1000)
    parent_id = serializers.UUIDField(required=False, allow_null=True)


class CommentUpdateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=1000)


# ─────────────────────────────────────────────────────────────────────────────
#  Reshare serializers
# ─────────────────────────────────────────────────────────────────────────────


class ReshareSerializer(serializers.ModelSerializer):
    user = UserMeSerializer(read_only=True)
    original_post = PostListSerializer(read_only=True)
    reshare_post = PostListSerializer(read_only=True)

    class Meta:
        model = Reshare
        fields = [
            "id", "user", "original_post", "reshare_post",
            "created_at",
        ]


class ReshareCreateSerializer(serializers.Serializer):
    original_post_id = serializers.UUIDField()
    reshare_comment = serializers.CharField(max_length=500, required=False, allow_blank=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Like serializers
# ─────────────────────────────────────────────────────────────────────────────


class LikeSerializer(serializers.ModelSerializer):
    user = UserMeSerializer(read_only=True)

    class Meta:
        model = Like
        fields = ["id", "user", "created_at"]
