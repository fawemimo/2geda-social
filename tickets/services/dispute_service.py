import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from chats.models import Conversation, ConversationMember
from tickets.models import Dispute, Ticket
from tickets.services.exceptions import DisputeAlreadyResolved
from utils.enum import DisputeStatus, MemberRole

logger = logging.getLogger(__name__)


def _broadcast_dispute_event(conversation_id: str, event: dict) -> None:
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"chat_{conversation_id}",
            event,
        )
    except Exception:
        logger.exception("Failed to broadcast dispute event")


class DisputeService:

    @staticmethod
    def open_dispute(
        buyer: User,
        ticket: Ticket,
        reason: str,
        description: str,
    ) -> Dispute:
        existing = Dispute.objects.filter(
            ticket=ticket,
            buyer=buyer,
        ).exclude(
            status__in=[DisputeStatus.CLOSED.value]
        ).first()
        if existing:
            return existing

        with transaction.atomic():
            conversation = Conversation.objects.create(
                conversation_type="group",
                name=f"Dispute: {ticket.ticket_code}",
                created_by=buyer,
            )

            ConversationMember.objects.create(
                conversation=conversation,
                user=buyer,
                role=MemberRole.MEMBER.value,
            )

            seller_user = ticket.event.seller.user
            ConversationMember.objects.create(
                conversation=conversation,
                user=seller_user,
                role=MemberRole.MEMBER.value,
            )

            dispute = Dispute.objects.create(
                ticket=ticket,
                buyer=buyer,
                seller=ticket.event.seller,
                event=ticket.event,
                reason=reason,
                description=description,
                status=DisputeStatus.OPEN.value,
                conversation=conversation,
            )

        _broadcast_dispute_event(
            str(conversation.id),
            {
                "type": "group_members_updated",
                "conversation_id": str(conversation.id),
                "action": "dispute_opened",
                "member_ids": [str(buyer.id), str(seller_user.id)],
            },
        )

        return dispute

    @staticmethod
    def assign_moderator(dispute: Dispute, moderator: User) -> Dispute:
        if dispute.status in (
            DisputeStatus.CLOSED.value,
            DisputeStatus.RESOLVED_BUYER.value,
            DisputeStatus.RESOLVED_SELLER.value,
        ):
            raise DisputeAlreadyResolved()

        with transaction.atomic():
            dispute.assigned_moderator = moderator
            dispute.status = DisputeStatus.UNDER_REVIEW.value
            dispute.save(update_fields=["assigned_moderator", "status"])

            ConversationMember.objects.get_or_create(
                conversation=dispute.conversation,
                user=moderator,
                defaults={"role": MemberRole.ADMIN.value},
            )

        _broadcast_dispute_event(
            str(dispute.conversation.id),
            {
                "type": "group_members_updated",
                "conversation_id": str(dispute.conversation.id),
                "action": "moderator_assigned",
                "moderator_id": str(moderator.id),
            },
        )

        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"user_{moderator.id}",
                {
                    "type": "dispute_assigned",
                    "conversation_id": str(dispute.conversation.id),
                    "dispute_id": str(dispute.id),
                    "message": "You have been assigned as a moderator to a dispute.",
                },
            )
        except Exception:
            logger.exception("Failed to notify moderator")

        return dispute

    @staticmethod
    def resolve(dispute: Dispute, moderator: User, resolution: str, notes: str = "") -> Dispute:
        if dispute.status in (
            DisputeStatus.CLOSED.value,
            DisputeStatus.RESOLVED_BUYER.value,
            DisputeStatus.RESOLVED_SELLER.value,
        ):
            raise DisputeAlreadyResolved()

        with transaction.atomic():
            dispute.status = resolution
            dispute.resolution_notes = notes
            dispute.resolved_at = timezone.now()
            dispute.assigned_moderator = moderator
            dispute.save(
                update_fields=[
                    "status",
                    "resolution_notes",
                    "resolved_at",
                    "assigned_moderator",
                ]
            )

            if dispute.conversation:
                dispute.conversation.is_locked = True
                dispute.conversation.save(update_fields=["is_locked"])
                _broadcast_dispute_event(
                    str(dispute.conversation.id),
                    {
                        "type": "group_locked",
                        "conversation_id": str(dispute.conversation.id),
                        "resolution": resolution,
                    },
                )

        return dispute

    @staticmethod
    def get_buyer_disputes(buyer: User):
        return Dispute.objects.filter(
            buyer=buyer, is_deleted=False
        ).select_related("ticket", "event", "assigned_moderator")

    @staticmethod
    def get_seller_disputes(seller_user: User):
        return Dispute.objects.filter(
            seller__user=seller_user, is_deleted=False
        ).select_related("ticket", "event", "assigned_moderator")

    @staticmethod
    def get_moderator_disputes(moderator: User):
        return Dispute.objects.filter(
            assigned_moderator=moderator, is_deleted=False
        ).select_related("ticket", "event", "buyer", "seller")
