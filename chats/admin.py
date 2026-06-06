from django.contrib import admin

from chats.models import Conversation, ConversationMember, Message, MessageReaction
from utils.admin import BaseModelAdmin, BaseTabularInline


class ConversationMemberInline(BaseTabularInline):
    model = ConversationMember
    fields = ("user", "role", "is_muted", "is_pinned", "last_read_at", "unread_count")
    ordering = ("-role", "user")
    autocomplete_fields = ("user",)


class MessageReactionInline(BaseTabularInline):
    model = MessageReaction
    fields = ("user", "emoji")
    autocomplete_fields = ("user",)


@admin.register(Conversation)
class ConversationAdmin(BaseModelAdmin):
    inlines = [ConversationMemberInline]
    list_display = (
        "id",
        "conversation_type",
        "name",
        "created_by",
        "last_message_at",
        "last_message_preview",
        "is_deleted",
        "created_at",
    )
    search_fields = ("id", "name", "created_by__email", "created_by__username")
    list_filter = ("conversation_type",)
    autocomplete_fields = ("created_by",)


@admin.register(ConversationMember)
class ConversationMemberAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "conversation",
        "user",
        "role",
        "is_muted",
        "is_pinned",
        "unread_count",
        "left_at",
    )
    search_fields = ("conversation__id", "user__email", "user__username")
    list_filter = ("role", "is_muted", "is_pinned")
    autocomplete_fields = ("conversation", "user", "added_by")


@admin.register(Message)
class MessageAdmin(BaseModelAdmin):
    inlines = [MessageReactionInline]
    list_display = (
        "id",
        "conversation",
        "sender",
        "message_type",
        "body",
        "delivery_status",
        "is_edited",
        "is_deleted",
        "created_at",
    )
    search_fields = ("conversation__id", "sender__email", "sender__username", "body")
    list_filter = ("message_type", "delivery_status", "is_edited")
    autocomplete_fields = ("conversation", "sender", "reply_to")


@admin.register(MessageReaction)
class MessageReactionAdmin(BaseModelAdmin):
    list_display = ("id", "message", "user", "emoji", "created_at")
    search_fields = ("message__id", "user__email", "user__username")
    autocomplete_fields = ("message", "user")
