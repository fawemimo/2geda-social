from __future__ import annotations

from rest_framework import serializers

from accounts.serializers import UserMeSerializer
from displays.models import Display, DisplayComment
from medias.models import Media


class DisplayMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = ["id", "cdn_url", "media_type", "width_px", "height_px", "duration_seconds"]


class DisplayListSerializer(serializers.ModelSerializer):
    author = UserMeSerializer(read_only=True)
    media = DisplayMediaSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Display
        fields = [
            "id", "author", "body", "media", "visibility",
            "expires_at", "created_at",
            "likes_count", "comments_count", "views_count", "reshares_count",
        ]


class DisplayCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    media_id = serializers.UUIDField(required=False, allow_null=True)
    visibility = serializers.ChoiceField(
        choices=["public", "followers", "private"],
        default="public",
        required=False,
    )
    reshare_of = serializers.UUIDField(required=False, allow_null=True)

    def validate_media_id(self, value):
        if value is None:
            return value
        if not Media.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Media not found.")
        return value


class DisplayCommentSerializer(serializers.ModelSerializer):
    author = UserMeSerializer(read_only=True)

    class Meta:
        model = DisplayComment
        fields = ["id", "display", "author", "body", "created_at"]
        read_only_fields = ["display", "author"]


class DisplayCommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=1000)
