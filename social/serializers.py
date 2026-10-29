from __future__ import annotations

from rest_framework import serializers

from accounts.models import Follow, User
from social.models import Comment, CommentMedia, Like, Post, PostMedia, Reshare, SocialLocation
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


class CommentMediaSerializer(serializers.ModelSerializer):
    cdn_url = serializers.CharField(source="media.cdn_url", read_only=True, allow_null=True)
    media_type = serializers.CharField(source="media.media_type", read_only=True, allow_null=True)

    class Meta:
        model = CommentMedia
        fields = ["id", "cdn_url", "media_type", "position"]


class UserSocialSerializer(serializers.ModelSerializer):
    display_photo = serializers.StringRelatedField(source="profile.display_photo", read_only=True)
    avatar = serializers.StringRelatedField(source="profile.avatar", read_only=True)
    class Meta:
        model = User
        fields = (
            "id", "username","is_active", "display_photo", "avatar"
        )
        read_only_fields = fields
        

# Read shape for the shared location snapshot.

class SocialLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialLocation
        fields = [
            "id", "latitude", "longitude", "label",
            "formatted_address", "city", "state", "country", "status",
        ]
        read_only_fields = fields


# Coordinates any social object may be tagged with.

class LocationInputMixin(serializers.Serializer):
    location_label = serializers.CharField(max_length=120, required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        lat, lng = attrs.get("latitude"), attrs.get("longitude")
        # One without the other cannot be geocoded.
        if (lat is None) != (lng is None):
            raise serializers.ValidationError(
                {"latitude": "Send latitude and longitude together, or neither."}
            )
        return attrs


class PostListSerializer(serializers.ModelSerializer):
    author = UserSocialSerializer(read_only=True)
    attachments = PostMediaSerializer(many=True, read_only=True)
    is_liked = serializers.BooleanField(read_only=True)
    reshare_of_detail = serializers.SerializerMethodField()
    location = SocialLocationSerializer(read_only=True)
    mentions = UserSocialSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            "id", "author", "body", "visibility",
            "attachments", "is_liked",
            "reshare_of", "reshare_of_detail", "reshare_comment",
            "likes_count", "comments_count", "reshares_count",
            "mentions", "location", "created_at", "updated_at",
        ]

    def get_reshare_of_detail(self, obj):
        if obj.reshare_of_id:
            return PostListSerializer(obj.reshare_of, context=self.context).data
        return None


class MediaIdsValidationMixin:    

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


class PostCreateSerializer(MediaIdsValidationMixin, LocationInputMixin):
    body = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=PostVisibility.choices(),
        default=PostVisibility.PUBLIC.value,
        required=False,
    )
    media_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list,
    )
    mentions = serializers.ListField(
        child=serializers.CharField(max_length=150),
        required=False,
        default=list,
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

    def validate_mentions(self, value):
        if not value:
            return value
        usernames = [u.lstrip("@").lower() for u in value]
        existing = set(
            User.objects.filter(username__in=usernames)
            .values_list("username", flat=True)
        )
        missing = [u for u in usernames if u not in existing]
        if missing:
            raise serializers.ValidationError(
                f"Users not found: {', '.join(missing)}"
            )
        return usernames


class PostUpdateSerializer(MediaIdsValidationMixin, LocationInputMixin):
    body = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=PostVisibility.choices(), required=False)
    media_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


# ─────────────────────────────────────────────────────────────────────────────
#  Comment serializers
# ─────────────────────────────────────────────────────────────────────────────


class CommentSerializer(serializers.ModelSerializer):
    author = UserSocialSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    location = SocialLocationSerializer(read_only=True)
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id", "post", "author", "parent", "body",
            "likes_count", "replies_count",
            "is_liked", "replies", "location",
            "attachments",
            "created_at", "updated_at",
        ]

    def get_attachments(self, obj):
        attachments = getattr(obj, "attachments", None)
        if attachments is None:
            try:
                attachments = obj.attachments.all()
            except Exception:
                return []
        return CommentMediaSerializer(attachments, many=True).data

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


class CommentCreateSerializer(MediaIdsValidationMixin, LocationInputMixin):
    body = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    media_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list,
    )

    def validate_body(self, value):
        if not value and not self.initial_data.get("parent_id"):
            # Allow empty body only in some cases? But we need to allow media-only comments
            if not self.initial_data.get("media_ids"):
                raise serializers.ValidationError("Body is required.")
        elif not value and self.initial_data.get("media_ids"):
            pass
        return value



class CommentUpdateSerializer(MediaIdsValidationMixin, serializers.Serializer):
    body = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    media_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


# ─────────────────────────────────────────────────────────────────────────────
#  Reshare serializers
# ─────────────────────────────────────────────────────────────────────────────


class ReshareSerializer(serializers.ModelSerializer):
    user = UserSocialSerializer(read_only=True)
    original_post = PostListSerializer(read_only=True)
    reshare_post = PostListSerializer(read_only=True)
    location = SocialLocationSerializer(read_only=True)

    class Meta:
        model = Reshare
        fields = [
            "id", "user", "original_post", "reshare_post", "location",
            "created_at",
        ]


class ReshareCreateSerializer(LocationInputMixin):
    original_post_id = serializers.UUIDField()
    reshare_comment = serializers.CharField(max_length=500, required=False, allow_blank=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Like serializers
# ─────────────────────────────────────────────────────────────────────────────


class LikeSerializer(serializers.ModelSerializer):
    user = UserSocialSerializer(read_only=True)

    class Meta:
        model = Like
        fields = ["id", "user", "created_at"]
