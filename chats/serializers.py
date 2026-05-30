from __future__ import annotations

from rest_framework import serializers

from chats.models import Conversation, ConversationMember, Message


class ConversationMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    display_name = serializers.CharField(source="user.profile.display_name", read_only=True, default="")
    avatar_url = serializers.CharField(source="user.profile.avatar.cdn_url", read_only=True, default=None)

    class Meta:
        model = ConversationMember
        fields = [
            "user_id", "username", "display_name", "avatar_url",
            "role", "is_muted", "last_read_at", "unread_count",
        ]


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
            "created_at",
        ]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    members = ConversationMemberSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "conversation_type", "last_message_at",
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
        user = self.context.get("request").user if self.context.get("request") else None
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

