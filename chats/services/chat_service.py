from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from chats.models import Conversation, ConversationMember, JoinRequest, Message, MessageReaction
from utils.enum import ConversationType, DeliveryStatus, MemberRole, MessageType, NotificationPriority, NotificationType

logger = logging.getLogger(__name__)

GROUP_MIN_MEMBERS = 3
GROUP_MAX_MEMBERS = 200


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    message: Message
    is_new_conversation: bool = False


class ChatService:

    @staticmethod
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
    @transaction.atomic
    def create_group_conversation(
        *,
        creator_id: str,
        name: str,
        description: str = "",
        member_ids: list[str],
    ) -> Conversation:
        all_ids = list({creator_id, *member_ids})
        if len(all_ids) < GROUP_MIN_MEMBERS:
            raise ValueError(
                f"A group must have at least {GROUP_MIN_MEMBERS} members."
            )
        if len(all_ids) > GROUP_MAX_MEMBERS:
            raise ValueError(
                f"A group cannot have more than {GROUP_MAX_MEMBERS} members."
            )

        conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name=name,
            description=description,
            created_by_id=creator_id,
        )

        members = []
        for uid in all_ids:
            role = MemberRole.OWNER.value if uid == creator_id else MemberRole.MEMBER.value
            members.append(
                ConversationMember(
                    conversation=conv,
                    user_id=uid,
                    role=role,
                    added_by_id=creator_id,
                )
            )
        ConversationMember.objects.bulk_create(members)
        return conv

    @staticmethod
    @transaction.atomic
    def add_group_members(
        *,
        conversation_id: str,
        actor_id: str,
        member_ids: list[str],
    ) -> Conversation:
        conv = Conversation.objects.get(pk=conversation_id)
        if conv.conversation_type != ConversationType.GROUP.value:
            raise PermissionError("Only group conversations can have members added.")

        if not ChatService._is_admin_or_owner(conversation_id, actor_id):
            raise PermissionError("Only admins or the owner can add members.")

        current_members = set(
            ConversationMember.objects.filter(
                conversation_id=conversation_id,
                left_at__isnull=True,
            ).values_list("user_id", flat=True)
        )

        new_ids = [uid for uid in member_ids if uid not in current_members]
        if not new_ids:
            return conv

        if len(current_members) + len(new_ids) > GROUP_MAX_MEMBERS:
            raise ValueError(
                f"Group cannot exceed {GROUP_MAX_MEMBERS} members."
            )

        ConversationMember.objects.bulk_create([
            ConversationMember(
                conversation=conv,
                user_id=uid,
                role=MemberRole.MEMBER.value,
                added_by_id=actor_id,
            )
            for uid in new_ids
        ])
        return conv

    @staticmethod
    @transaction.atomic
    def remove_group_member(
        *,
        conversation_id: str,
        actor_id: str,
        target_user_id: str,
    ) -> Conversation:
        conv = Conversation.objects.get(pk=conversation_id)
        if conv.conversation_type != ConversationType.GROUP.value:
            raise PermissionError("Only group conversations can have members removed.")

        if not ChatService._is_admin_or_owner(conversation_id, actor_id):
            raise PermissionError("Only admins or the owner can remove members.")

        if str(actor_id) == str(target_user_id):
            raise PermissionError("You cannot remove yourself. Use leave instead.")

        target_role = ChatService._get_member_role(conversation_id, target_user_id)
        if target_role == MemberRole.OWNER.value:
            raise PermissionError("Cannot remove the owner from the group.")

        member = ConversationMember.objects.get(
            conversation_id=conversation_id,
            user_id=target_user_id,
            left_at__isnull=True,
        )
        member.left_at = timezone.now()
        member.save(update_fields=["left_at"])

        if target_role in (MemberRole.ADMIN.value, MemberRole.OWNER.value):
            ChatService._auto_assign_admin_on_leave(conversation_id)

        return conv

    @staticmethod
    @transaction.atomic
    def toggle_group_lock(
        *,
        conversation_id: str,
        actor_id: str,
    ) -> Conversation:
        conv = Conversation.objects.get(pk=conversation_id)
        if conv.conversation_type != ConversationType.GROUP.value:
            raise PermissionError("Only group conversations can be locked.")

        if not ChatService._is_admin_or_owner(conversation_id, actor_id):
            raise PermissionError("Only admins or the owner can lock the group.")

        conv.is_locked = not conv.is_locked
        conv.locked_by_id = actor_id if conv.is_locked else None
        conv.save(update_fields=["is_locked", "locked_by"])
        return conv

    @staticmethod
    @transaction.atomic
    def delete_message(
        *,
        message_id: str,
        actor_id: str,
    ) -> Message:
        msg = Message.objects.select_related("conversation").get(pk=message_id)

        if str(msg.sender_id) == str(actor_id):
            msg.soft_delete(deleted_by_id=actor_id)
            return msg

        conv = msg.conversation
        if conv.conversation_type == ConversationType.GROUP.value:
            if ChatService._is_admin_or_owner(str(conv.id), actor_id):
                msg.soft_delete(deleted_by_id=actor_id)
                return msg

        raise PermissionError("You can only delete your own messages.")

    @staticmethod
    @transaction.atomic
    def send_message(
        *,
        conversation_id: str,
        sender_id: str,
        body: str = "",
        message_type: str = MessageType.TEXT.value,
        reply_to_id: str | None = None,
    ) -> SendMessageResult:
        conv = Conversation.objects.get(pk=conversation_id)
        if conv.is_locked:
            is_admin = ChatService._is_admin_or_owner(conversation_id, sender_id)
            if not is_admin:
                raise PermissionError("This group is locked. Only admins can send messages.")

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
    @transaction.atomic
    def request_to_join_group(
        *,
        conversation_id: str,
        user_id: str,
    ) -> JoinRequest:
        conv = Conversation.objects.get(pk=conversation_id)
        if conv.conversation_type != ConversationType.GROUP.value:
            raise PermissionError("Only group conversations accept join requests.")

        if ChatService.is_member(conversation_id, user_id):
            raise PermissionError("You are already a member of this group.")

        existing = JoinRequest.objects.filter(
            conversation_id=conversation_id,
            user_id=user_id,
        ).first()
        if existing and existing.status == JoinRequest.PENDING:
            raise PermissionError("You already have a pending join request for this group.")
        if existing and existing.status == JoinRequest.APPROVED:
            raise PermissionError("You are already a member of this group.")

        join_req = JoinRequest.objects.create(
            conversation_id=conversation_id,
            user_id=user_id,
        )

        ChatService._dispatch_join_request_notification(join_req)
        return join_req

    @staticmethod
    @transaction.atomic
    def approve_join_request(
        *,
        request_id: str,
        actor_id: str,
    ) -> JoinRequest:
        join_req = JoinRequest.objects.select_related("conversation").get(pk=request_id)

        if join_req.conversation.conversation_type != ConversationType.GROUP.value:
            raise PermissionError("Only group conversations accept join requests.")

        if not ChatService._is_admin_or_owner(str(join_req.conversation_id), actor_id):
            raise PermissionError("Only admins or the owner can approve join requests.")

        if join_req.status != JoinRequest.PENDING:
            raise PermissionError("This request has already been processed.")

        ConversationMember.objects.create(
            conversation=join_req.conversation,
            user=join_req.user,
            role=MemberRole.MEMBER.value,
            added_by_id=actor_id,
        )

        join_req.status = JoinRequest.APPROVED
        join_req.processed_by_id = actor_id
        join_req.processed_at = timezone.now()
        join_req.save(update_fields=["status", "processed_by_id", "processed_at"])

        ChatService._dispatch_join_response_notification(join_req)
        return join_req

    @staticmethod
    @transaction.atomic
    def reject_join_request(
        *,
        request_id: str,
        actor_id: str,
    ) -> JoinRequest:
        join_req = JoinRequest.objects.select_related("conversation").get(pk=request_id)

        if join_req.conversation.conversation_type != ConversationType.GROUP.value:
            raise PermissionError("Only group conversations accept join requests.")

        if not ChatService._is_admin_or_owner(str(join_req.conversation_id), actor_id):
            raise PermissionError("Only admins or the owner can reject join requests.")

        if join_req.status != JoinRequest.PENDING:
            raise PermissionError("This request has already been processed.")

        join_req.status = JoinRequest.REJECTED
        join_req.processed_by_id = actor_id
        join_req.processed_at = timezone.now()
        join_req.save(update_fields=["status", "processed_by_id", "processed_at"])

        ChatService._dispatch_join_response_notification(join_req)
        return join_req

    @staticmethod
    def get_pending_join_requests(
        conversation_id: str,
        user_id: str,
    ) -> list[JoinRequest]:
        if not ChatService._is_admin_or_owner(conversation_id, user_id):
            raise PermissionError("Only admins or the owner can view join requests.")

        return list(
            JoinRequest.objects.filter(
                conversation_id=conversation_id,
                status=JoinRequest.PENDING,
            ).select_related("user").order_by("created_at")
        )

    @staticmethod
    @transaction.atomic
    def promote_to_admin(
        *,
        conversation_id: str,
        actor_id: str,
        target_user_id: str,
    ) -> ConversationMember:
        if not ChatService._is_admin_or_owner(conversation_id, actor_id):
            raise PermissionError("Only admins or the owner can promote members.")

        member = ConversationMember.objects.get(
            conversation_id=conversation_id,
            user_id=target_user_id,
            left_at__isnull=True,
        )
        if member.role == MemberRole.OWNER.value:
            raise ValueError("The owner is already the highest role.")
        if member.role == MemberRole.ADMIN.value:
            raise ValueError("This member is already an admin.")

        member.role = MemberRole.ADMIN.value
        member.save(update_fields=["role"])
        return member

    @staticmethod
    def _auto_assign_admin_on_leave(conversation_id: str) -> None:
        remaining_admins = ConversationMember.objects.filter(
            conversation_id=conversation_id,
            left_at__isnull=True,
            role__in=[MemberRole.ADMIN.value, MemberRole.OWNER.value],
        )
        if remaining_admins.exists():
            return

        oldest = ConversationMember.objects.filter(
            conversation_id=conversation_id,
            left_at__isnull=True,
        ).order_by("created_at").first()

        if oldest:
            oldest.role = MemberRole.ADMIN.value
            oldest.save(update_fields=["role"])
            logger.info(
                "Auto-promoted user=%s to ADMIN in conversation=%s",
                oldest.user_id, conversation_id,
            )

    @staticmethod
    def _dispatch_join_request_notification(join_req: JoinRequest) -> None:
        from notifications.services.dto import CreateNotificationDTO
        from notifications.services.notification_services import NotificationService as NotificationCreator
        from notifications.tasks import dispatch_notification

        admins = ConversationMember.objects.filter(
            conversation=join_req.conversation,
            left_at__isnull=True,
            role__in=[MemberRole.ADMIN.value, MemberRole.OWNER.value],
        ).select_related("user")

        conv_name = join_req.conversation.name or "Group"
        title = f"@{join_req.user.username} wants to join {conv_name}"
        body = f"@{join_req.user.username} has requested to join the group."

        for admin in admins:
            try:
                dto = CreateNotificationDTO(
                    recipient_id=str(admin.user_id),
                    notification_type=NotificationType.JOIN_REQUEST.value,
                    title=title,
                    body=body,
                    actor_id=str(join_req.user_id),
                    source_model=JoinRequest,
                    source_id=str(join_req.id),
                    action_url=f"/chats/{join_req.conversation_id}",
                    priority=NotificationPriority.NORMAL.value,
                    metadata={
                        "conversation_id": str(join_req.conversation_id),
                        "join_request_id": str(join_req.id),
                        "requesting_user_id": str(join_req.user_id),
                    },
                )
                notification = NotificationCreator.create(dto)
                dispatch_notification.delay(str(notification.id))
            except Exception:
                logger.exception("Failed to dispatch join request notification to admin %s", admin.user_id)

    @staticmethod
    def _dispatch_join_response_notification(join_req: JoinRequest) -> None:
        from notifications.services.dto import CreateNotificationDTO
        from notifications.services.notification_services import NotificationService as NotificationCreator
        from notifications.tasks import dispatch_notification

        conv_name = join_req.conversation.name or "Group"

        if join_req.status == JoinRequest.APPROVED:
            notif_type = NotificationType.JOIN_APPROVED.value
            title = f"Your request to join {conv_name} was approved"
            body = f"You can now participate in {conv_name}."
        else:
            notif_type = NotificationType.JOIN_REJECTED.value
            title = f"Your request to join {conv_name} was rejected"
            body = "An admin declined your join request."

        try:
            dto = CreateNotificationDTO(
                recipient_id=str(join_req.user_id),
                notification_type=notif_type,
                title=title,
                body=body,
                actor_id=str(join_req.processed_by_id),
                source_model=JoinRequest,
                source_id=str(join_req.id),
                action_url=f"/chats/{join_req.conversation_id}",
                priority=NotificationPriority.NORMAL.value,
                metadata={
                    "conversation_id": str(join_req.conversation_id),
                    "join_request_id": str(join_req.id),
                    "status": join_req.status,
                },
            )
            notification = NotificationCreator.create(dto)
            dispatch_notification.delay(str(notification.id))
        except Exception:
            logger.exception("Failed to dispatch join response notification to %s", join_req.user_id)

    @staticmethod
    @transaction.atomic
    def mark_as_read(*, user_id: str, conversation_id: str) -> None:
        ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user_id=user_id,
        ).update(
            last_read_at=timezone.now(),
            unread_count=0,
        )

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

    @staticmethod
    def _is_admin_or_owner(conversation_id: str, user_id: str) -> bool:
        return ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user_id=user_id,
            left_at__isnull=True,
            role__in=[MemberRole.ADMIN.value, MemberRole.OWNER.value],
        ).exists()

    @staticmethod
    def _get_member_role(conversation_id: str, user_id: str) -> str | None:
        try:
            member = ConversationMember.objects.get(
                conversation_id=conversation_id,
                user_id=user_id,
                left_at__isnull=True,
            )
            return member.role
        except ConversationMember.DoesNotExist:
            return None

    @staticmethod
    def search_messages(
        user_id: str,
        query: str,
        *,
        conversation_id: str | None = None,
        limit: int = 50,
    ) -> list[Message]:
        user_conv_ids = list(
            ConversationMember.objects.filter(
                user_id=user_id, left_at__isnull=True,
            ).values_list("conversation_id", flat=True)
        )

        if not user_conv_ids:
            return []

        qs = Message.objects.filter(
            conversation_id__in=user_conv_ids,
            is_deleted=False,
            body__icontains=query,
        ).select_related("sender", "media", "conversation")

        if conversation_id:
            str_ids = [str(cid) for cid in user_conv_ids]
            if conversation_id not in str_ids:
                return []
            qs = qs.filter(conversation_id=conversation_id)

        return list(qs.order_by("-created_at")[:limit])

    @staticmethod
    def search_conversations(
        user_id: str,
        query: str,
    ) -> list[Conversation]:
        user_conv_ids = list(
            ConversationMember.objects.filter(
                user_id=user_id, left_at__isnull=True,
            ).values_list("conversation_id", flat=True)
        )

        if not user_conv_ids:
            return []

        return list(
            Conversation.objects.filter(
                pk__in=user_conv_ids,
                is_deleted=False,
                name__icontains=query,
            ).order_by("-last_message_at")
        )

    @staticmethod
    def search_media(
        user_id: str,
        query: str,
        *,
        media_type: str | None = None,
        limit: int = 50,
    ) -> list[Message]:
        user_conv_ids = list(
            ConversationMember.objects.filter(
                user_id=user_id, left_at__isnull=True,
            ).values_list("conversation_id", flat=True)
        )

        if not user_conv_ids:
            return []

        qs = Message.objects.filter(
            conversation_id__in=user_conv_ids,
            is_deleted=False,
            media__isnull=False,
            media__original_filename__icontains=query,
        ).select_related("sender", "media", "conversation")

        if media_type:
            qs = qs.filter(media__media_type=media_type)

        return list(qs.order_by("-created_at")[:limit])
