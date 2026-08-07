from __future__ import annotations

from rest_framework import serializers

from medias.models import Media


class MediaUploadSerializer(serializers.Serializer):
    file = serializers.FileField(write_only=True)


class MediaResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = [
            "id", "cdn_url", "media_type", "mime_type",
            "original_filename", "file_size_bytes",
            "width_px", "height_px",
            "processing_status", "processing_error",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class MediaPresignedUrlSerializer(serializers.Serializer):
    file_name = serializers.CharField(max_length=255)
