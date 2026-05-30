from django.contrib import admin
from chats.models import ConversationMember, Message, Conversation, MessageReaction
from utils.admin import BaseModelAdmin


@admin.register(Conversation)
class ConversationAdmin(BaseModelAdmin):
    list_display = ("id","created_by", "conversation_type","created_at", "updated_at")
    search_fields = ("id",)

@admin.register(ConversationMember)
class ConversationMemberAdmin(BaseModelAdmin):
    list_display = ("id", "conversation", "user", "conversation_last_message_at")
    search_fields = ("conversation__id", "user__email")

@admin.register(Message)
class MessageAdmin(BaseModelAdmin):
    list_display = ("id", "conversation", "sender", "created_at")
    search_fields = ("conversation__id", "sender__email", "content_type")

@admin.register(MessageReaction)
class MessageReactionAdmin(BaseModelAdmin):
    list_display = ("id", "message", "user", "created_at")
    search_fields = ("message__id", "user__email")

