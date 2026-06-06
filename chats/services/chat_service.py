from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from chats.models import Conversation, ConversationMember, Message, MessageReaction
from utils.enum import ConversationType, DeliveryStatus, MemberRole, MessageType, NotificationPriority, NotificationType

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    message: Message
    is_new_conversation: bool = False

# Single-responsibility service for all chat domain operations.

class ChatService:

    @staticmethod
# Return existing direct conversation or create a new one.
    @transaction.atomic
    def get_or_create_direct_conversation(
        user_a_id: str,
        user_b_id: str,
    ) -> tuple[Conversation, bool]:
        convs_a = set(
            ConversationMember.objects.filter(
                user_id=user_a_id, left_at__isnull=True
            ).values_list("conversation_id", flat=True)
        )
        convs_b = set(
            ConversationMember.objects.filter(
                user_id=user_b_id, left_at__isnull=True
            ).values_list("conversation_id", flat=True)
        )
        shared = convs_a & convs_b

        if shared:
            conv = Conversation.objects.get(pk=next(iter(shared)))
            return conv, False

        conv = Conversation.objects.create(
            conversation_type=ConversationType.DIRECT.value,
            created_by_id=user_a_id,
        )
        ConversationMember.objects.bulk_create([
            ConversationMember(conversation=conv, user_id=user_a_id, role=MemberRole.MEMBER.value),
            ConversationMember(conversation=conv, user_id=user_b_id, role=MemberRole.MEMBER.value),
        ])
        return conv, True

    @staticmethod
# Persist a new message and update conversation denormalised fields.
    @transaction.atomic
    def send_message(
        *,
        conversation_id: str,
        sender_id: str,
        body: str = "",
        message_type: str = MessageType.TEXT.value,
        reply_to_id: str | None = None,
    ) -> SendMessageResult:
        msg = Message.objects.create(
            conversation_id=conversation_id,
            sender_id=sender_id,
            message_type=message_type,
            body=body,
            reply_to_id=reply_to_id,
        )
        preview = body[:200] if body else f"[{message_type}]"
        Conversation.objects.filter(pk=conversation_id).update(
            last_message_at=timezone.now(),
            last_message_preview=preview,
        )
        ConversationMember.objects.filter(conversation_id=conversation_id).update(
            conversation_last_message_at=timezone.now(),
        )
        ConversationMember.objects.filter(
            conversation_id=conversation_id,
        ).exclude(user_id=sender_id).update(
            unread_count=F("unread_count") + 1,
        )

        msg = Message.objects.select_related("sender", "conversation").get(pk=msg.pk)
        ChatService._dispatch_message_notifications(msg)
        return SendMessageResult(message=msg)

    @staticmethod
    def _dispatch_message_notifications(msg: Message) -> None:
        from notifications.services.dto import CreateNotificationDTO
        from notifications.services.notification_services import NotificationService as NotificationCreator
        from notifications.tasks import dispatch_notification

        sender = msg.sender
        preview = msg.body[:200] if msg.body else f"[{msg.message_type}]"
        title = f"@{sender.username} sent you a message"

        other_members = ConversationMember.objects.filter(
            conversation=msg.conversation,
            left_at__isnull=True,
        ).exclude(user=sender).select_related("user")

        for member in other_members:
            if member.is_muted:
                continue
            try:
                dto = CreateNotificationDTO(
                    recipient_id=str(member.user_id),
                    notification_type=NotificationType.NEW_MESSAGE.value,
                    title=title,
                    body=preview,
                    actor_id=str(sender.id),
                    source_model=Message,
                    source_id=str(msg.id),
                    action_url=f"/chats/{msg.conversation_id}",
                    priority=NotificationPriority.NORMAL.value,
                )
                notification = NotificationCreator.create(dto)
                dispatch_notification.delay(str(notification.id))
            except Exception:
                logger.exception("Failed to dispatch message notification to %s", member.user_id)

    @staticmethod
# Reset unread count and update read watermark for a member.
    @transaction.atomic
    def mark_as_read(*, user_id: str, conversation_id: str) -> None:
        ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user_id=user_id,
        ).update(
            last_read_at=timezone.now(),
            unread_count=0,
        )

# Return the conversation if the user is an active member.
    @staticmethod
    def get_conversation_for_user(
        conversation_id: str,
        user_id: str,
    ) -> Conversation | None:
        try:
            member = ConversationMember.objects.get(
                conversation_id=conversation_id,
                user_id=user_id,
                left_at__isnull=True,
            )
            return member.conversation
        except ConversationMember.DoesNotExist:
            return None

# Return all active conversations for a user, newest-first.
    @staticmethod
    def get_user_conversations(user_id: str) -> list[Conversation]:
        member_ids = ConversationMember.objects.filter(
            user_id=user_id,
            left_at__isnull=True,
        ).values_list("conversation_id", flat=True)

        return list(
            Conversation.objects.filter(
                pk__in=list(member_ids), is_deleted=False
            ).order_by("-last_message_at")
        )

# Return paginated messages for a conversation (oldest-first).
    @staticmethod
    def get_messages(
        conversation_id: str,
        *,
        before: str | None = None,
        limit: int = 50,
    ) -> list[Message]:
        qs = Message.objects.filter(
            conversation_id=conversation_id,
            is_deleted=False,
        ).select_related("sender", "media").order_by("-created_at")

        if before:
            qs = qs.filter(created_at__lt=before)

        return list(qs[:limit][::-1])

    @staticmethod
    def is_member(conversation_id: str, user_id: str) -> bool:
        return ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user_id=user_id,
            left_at__isnull=True,
        ).exists()

