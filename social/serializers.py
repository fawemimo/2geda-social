from __future__ import annotations

from rest_framework import serializers

from accounts.models import Follow, User
from accounts.serializers import UserMeSerializer
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

class PostMediaSerializer(serializers.ModelSerializer):
    cdn_url = serializers.CharField(source="media.cdn_url", read_only=True, allow_null=True)
    media_type = serializers.CharField(source="media.media_type", read_only=True, allow_null=True)

    class Meta:
        model = PostMedia
        fields = ["id", "cdn_url", "media_type", "position"]


class UserSocialSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id", "username","is_active"
        )
        read_only_fields = fields
        

class PostListSerializer(serializers.ModelSerializer):
    author = UserSocialSerializer(read_only=True)
    attachments = PostMediaSerializer(many=True, read_only=True)
    is_liked = serializers.BooleanField(read_only=True)
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

    def get_reshare_of_detail(self, obj):
        if obj.reshare_of_id:
            return PostListSerializer(obj.reshare_of, context=self.context).data
        return None


class MediaIdsValidationMixin:
    """Rejects media ids the requester may not attach.

    The worker re-checks ownership before linking, but validating here turns a
    bad request into a 400 the client can act on instead of media that silently
    never appears on the post.
    """

    MAX_MEDIA_PER_POST = 10

    def validate_media_ids(self, value):
        if not value:
            return value

        if len(value) > self.MAX_MEDIA_PER_POST:
            raise serializers.ValidationError(
                f"A post may carry at most {self.MAX_MEDIA_PER_POST} media items."
            )

        ids = [str(v) for v in value]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Duplicate media ids are not allowed.")

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return value

        from medias.models import Media

        owned = {
            str(pk)
            for pk in Media.objects.filter(
                pk__in=ids, owner=user, is_deleted=False
            ).values_list("pk", flat=True)
        }
        unknown = [i for i in ids if i not in owned]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown media, or not owned by you: {', '.join(unknown)}"
            )
        return value


class PostCreateSerializer(MediaIdsValidationMixin, serializers.Serializer):
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


class PostUpdateSerializer(MediaIdsValidationMixin, serializers.Serializer):
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
    author = UserSocialSerializer(read_only=True)
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
    user = UserSocialSerializer(read_only=True)
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
