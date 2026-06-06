from rest_framework import serializers

from notifications.models import Notification, NotificationPreference



class NotificationSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id", "notification_type", "category", "priority",
            "title", "body", "action_url", "metadata",
            "actor", "source",
            "is_read", "read_at", "created_at", "group_key",
        ]

    def get_actor(self, obj):
        if obj.actor_id:
            return {
                "id": str(obj.actor_id),
                "username": getattr(obj.actor, "username", None),
            }
        return None

    def get_source(self, obj):
        if obj.content_type_id and obj.object_id:
            return {
                "content_type": obj.content_type.model,
                "object_id": str(obj.object_id),
            }
        return None


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["category", "in_app_enabled", "push_enabled", "email_enabled"]


class PreferenceUpdateSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=[
        "social", "following", "mention", "chat", "system", "marketing",
    ])
    in_app_enabled = serializers.BooleanField(default=True, required=False)
    push_enabled = serializers.BooleanField(default=True, required=False)
    email_enabled = serializers.BooleanField(default=False, required=False)


class MuteActorSerializer(serializers.Serializer):
    actor_id = serializers.UUIDField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class MuteSourceSerializer(serializers.Serializer):
    source_model = serializers.CharField()
    source_id = serializers.UUIDField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class MuteSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    mute_type = serializers.CharField(read_only=True)
    muted_actor = serializers.SerializerMethodField(read_only=True)
    source = serializers.SerializerMethodField(read_only=True)
    muted_category = serializers.CharField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    reason = serializers.CharField(read_only=True)

    def get_muted_actor(self, obj):
        if obj.muted_actor_id:
            return {
                "id": str(obj.muted_actor_id),
                "username": getattr(obj.muted_actor, "username", None),
            }
        return None

    def get_source(self, obj):
        if obj.content_type_id and obj.object_id:
            return {
                "content_type": obj.content_type.model,
                "object_id": str(obj.object_id),
            }
        return None


class DeviceTokenSerializer(serializers.Serializer):
    device_token = serializers.CharField(max_length=512)
    device_fingerprint = serializers.CharField(max_length=256)
    platform = serializers.CharField(max_length=20, required=False, allow_blank=True)

