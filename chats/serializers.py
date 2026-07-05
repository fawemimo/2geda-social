from __future__ import annotations

from django.core.cache import cache
from rest_framework import serializers

from chats.models import Conversation, ConversationMember, JoinRequest, Message
from chats.services.chat_service import GROUP_MAX_MEMBERS, GROUP_MIN_MEMBERS

PRESENCE_CACHE_PREFIX = "online_user:"


class ConversationMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    display_name = serializers.CharField(source="user.profile.display_name", read_only=True, default="")
    avatar_url = serializers.CharField(source="user.profile.avatar.cdn_url", read_only=True, default=None)
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = ConversationMember
        fields = [
            "user_id", "username", "display_name", "avatar_url",
            "role", "is_muted", "last_read_at", "unread_count",
            "is_online",
        ]

    def get_is_online(self, obj) -> bool:
        return cache.get(f"{PRESENCE_CACHE_PREFIX}{obj.user_id}") is not None


class MessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.UUIDField(read_only=True)
    sender_username = serializers.CharField(source="sender.username", read_only=True)
    media_url = serializers.CharField(source="media.cdn_url", read_only=True, default=None)

    class Meta:
        model = Message
        fields = [
            "id", "conversation_id", "sender_id", "sender_username",
            "message_type", "body", "media_url",
            "reply_to_id", "is_edited", "delivery_status",
            "created_at", "is_deleted",
        ]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    members = ConversationMemberSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "conversation_type", "name", "description", "avatar",
            "is_locked", "last_message_at",
            "last_message_preview", "members", "last_message", "unread_count",
        ]

    def get_last_message(self, obj) -> dict | None:
        msg = (
            Message.objects.filter(conversation=obj, is_deleted=False)
            .select_related("sender")
            .order_by("-created_at")
            .first()
        )
        if msg:
            return MessageSerializer(msg).data
        return None

    def get_unread_count(self, obj) -> int:
        user = self.context.get("user")
        if not user and self.context.get("request"):
            user = self.context.get("request").user
        if user:
            try:
                return ConversationMember.objects.get(
                    conversation=obj, user=user, left_at__isnull=True
                ).unread_count
            except ConversationMember.DoesNotExist:
                pass
        return 0


class ConversationCreateSerializer(serializers.Serializer):
    recipient_id = serializers.UUIDField()


class GroupCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    member_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=GROUP_MIN_MEMBERS - 1,
        max_length=GROUP_MAX_MEMBERS - 1,
    )


class GroupMemberActionSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
    )


class GroupTargetMemberSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


class JoinRequestSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = JoinRequest
        fields = [
            "id", "conversation_id", "user_id", "username",
            "status", "created_at",
        ]


class PromoteToAdminSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


class UserSearchSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(source="id", read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    display_name = serializers.CharField(source="profile.display_name", read_only=True, default="")
    avatar_url = serializers.CharField(source="profile.avatar.cdn_url", read_only=True, default=None)

    class Meta:
        fields = ["user_id", "username", "email", "display_name", "avatar_url"]


class MediaSearchSerializer(serializers.ModelSerializer):
    sender_id = serializers.UUIDField(read_only=True)
    sender_username = serializers.CharField(source="sender.username", read_only=True)
    conversation_name = serializers.CharField(source="conversation.name", read_only=True, default="")
    media_url = serializers.CharField(source="media.cdn_url", read_only=True, default=None)
    media_type = serializers.CharField(source="media.media_type", read_only=True, default=None)
    media_filename = serializers.CharField(source="media.original_filename", read_only=True, default="")

    class Meta:
        model = Message
        fields = [
            "id", "conversation_id", "sender_id", "sender_username",
            "conversation_name", "body", "media_url", "media_type",
            "media_filename", "created_at",
        ]
