from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from tickets.models import Event, Payout, SellerProfile
from tickets.services.exceptions import ServiceError
from utils.enum import EventStatus, PayoutStatus
from utils.generators import generate_payout_reference

logger = logging.getLogger(__name__)


class PayoutService:

    @staticmethod
    def request_payout(
        *,
        seller: SellerProfile,
        event: Event,
        bank_name: str,
        account_number: str,
        account_name: str,
    ) -> Payout:
        if event.seller_id != seller.id:
            raise ServiceError(
                "You do not own this event.",
                code="not_event_owner",
                status_code=403,
            )

        now = timezone.now()
        event_ended = event.ends_at and event.ends_at <= now
        event_completed = event.status == EventStatus.COMPLETED.value
        event_cancelled = event.status == EventStatus.CANCELLED.value

        if not (event_ended or event_completed or event_cancelled):
            raise ServiceError(
                "Payout can only be requested after the event has ended.",
                code="event_not_ended",
            )

        existing = Payout.objects.filter(
            seller=seller,
            event=event,
            status__in=[PayoutStatus.REQUESTED.value, PayoutStatus.PROCESSING.value],
        ).exists()
        if existing:
            raise ServiceError(
                "A payout request for this event is already pending.",
                code="payout_already_requested",
            )

        gross = Decimal(str(event.total_revenue))
        commission = gross * (seller.commission_rate / Decimal("100"))
        net = gross - commission

        if net <= 0:
            raise ServiceError(
                "No revenue available for payout.",
                code="no_payout_amount",
            )

        payout = Payout.objects.create(
            seller=seller,
            event=event,
            amount=net,
            fees_deducted=commission,
            payout_ref=generate_payout_reference(),
            status=PayoutStatus.REQUESTED.value,
            bank_name=bank_name,
            account_number=account_number,
            account_name=account_name,
            requested_at=now,
        )

        logger.info(
            "Payout requested: ref=%s seller=%s event=%s amount=%s",
            payout.payout_ref, seller.id, event.id, net,
        )
        return payout

    @staticmethod
    def mark_paid(*, payout: Payout, admin: User, notes: str = "") -> Payout:
        if payout.status == PayoutStatus.PAID.value:
            raise ServiceError(
                "This payout has already been marked as paid.",
                code="payout_already_paid",
                status_code=409,
            )

        if payout.status not in (
            PayoutStatus.REQUESTED.value,
            PayoutStatus.PROCESSING.value,
        ):
            raise ServiceError(
                "Only requested or processing payouts can be marked as paid.",
                code="invalid_payout_status",
            )

        now = timezone.now()
        payout.status = PayoutStatus.PAID.value
        payout.paid_at = now
        payout.processed_by = admin
        payout.admin_notes = notes
        payout.save(update_fields=[
            "status", "paid_at", "processed_by", "admin_notes",
        ])

        PayoutService._send_paid_notifications(payout)

        logger.info("Payout marked paid: ref=%s by admin=%s", payout.payout_ref, admin.id)
        return payout

    @staticmethod
    def reject_payout(*, payout: Payout, admin: User, notes: str = "") -> Payout:
        if payout.status not in (
            PayoutStatus.REQUESTED.value,
            PayoutStatus.PROCESSING.value,
        ):
            raise ServiceError(
                "Only requested or processing payouts can be rejected.",
                code="invalid_payout_status",
            )

        payout.status = PayoutStatus.REJECTED.value
        payout.processed_by = admin
        payout.admin_notes = notes
        payout.save(update_fields=["status", "processed_by", "admin_notes"])

        PayoutService._send_rejected_notifications(payout)

        logger.info("Payout rejected: ref=%s by admin=%s", payout.payout_ref, admin.id)
        return payout

    @staticmethod
    def _send_paid_notifications(payout: Payout) -> None:
        seller_user = payout.seller.user
        event_title = payout.event.title[:50] if payout.event else "your event"
        amount_str = f"₦{payout.amount:,.2f}"

        from accounts.tasks import send_user_push_notification
        send_user_push_notification.delay(
            user_id=str(seller_user.id),
            title="Payout Sent!",
            body=(
                f"Your payout of {amount_str} for \"{event_title}\" has been "
                f"disbursed to {payout.bank_name} — {payout.account_number}."
            ),
            data={
                "type": "payout_paid",
                "payout_id": str(payout.id),
                "payout_ref": payout.payout_ref,
                "amount": str(payout.amount),
                "event_id": str(payout.event_id) if payout.event_id else None,
            },
        )

        from notifications.models import Notification
        from utils.enum import NotificationCategory, NotificationPriority, NotificationType
        Notification.objects.create(
            recipient=seller_user,
            notification_type=NotificationType.TICKET_PURCHASE.value,
            category=NotificationCategory.TICKETS.value,
            priority=NotificationPriority.HIGH.value,
            title="Payout Sent!",
            body=(
                f"Your payout of {amount_str} for \"{event_title}\" has been "
                f"disbursed to your account ({payout.bank_name} — "
                f"{payout.account_number})."
            ),
            action_url=f"/tickets/payouts/{payout.id}",
            metadata={
                "payout_id": str(payout.id),
                "payout_ref": payout.payout_ref,
                "amount": str(payout.amount),
            },
        )

        try:
            from clients.email.service import EmailService
            email_svc = EmailService("generic")
            email_svc.send_email(
                to=seller_user.email,
                obj=(
                    f"Hi {seller_user.username},\n\n"
                    f"Great news! Your payout of {amount_str} for "
                    f"\"{event_title}\" has been disbursed.\n\n"
                    f"Account details:\n"
                    f"  Bank: {payout.bank_name}\n"
                    f"  Account: {payout.account_number}\n"
                    f"  Name: {payout.account_name}\n\n"
                    f"Reference: {payout.payout_ref}\n\n"
                    f"Thank you for using 2geda Tickets."
                ),
                subject=f"Payout Sent — {event_title}",
            )
        except Exception:
            logger.exception("Failed to send payout email for ref=%s", payout.payout_ref)

    @staticmethod
    def _send_rejected_notifications(payout: Payout) -> None:
        seller_user = payout.seller.user
        event_title = payout.event.title[:50] if payout.event else "your event"
        amount_str = f"₦{payout.amount:,.2f}"
        reason = payout.admin_notes or "No reason provided."

        from accounts.tasks import send_user_push_notification
        send_user_push_notification.delay(
            user_id=str(seller_user.id),
            title="Payout Rejected",
            body=f"Your payout request of {amount_str} for \"{event_title}\" was rejected.",
            data={
                "type": "payout_rejected",
                "payout_id": str(payout.id),
                "payout_ref": payout.payout_ref,
            },
        )

        from notifications.models import Notification
        from utils.enum import NotificationCategory, NotificationPriority, NotificationType
        Notification.objects.create(
            recipient=seller_user,
            notification_type=NotificationType.TICKET_PURCHASE.value,
            category=NotificationCategory.TICKETS.value,
            priority=NotificationPriority.HIGH.value,
            title="Payout Rejected",
            body=(
                f"Your payout request of {amount_str} for \"{event_title}\" was "
                f"rejected. Reason: {reason}"
            ),
            action_url=f"/tickets/payouts/{payout.id}",
            metadata={
                "payout_id": str(payout.id),
                "payout_ref": payout.payout_ref,
                "reason": reason,
            },
        )
