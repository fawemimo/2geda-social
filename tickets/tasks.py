from __future__ import annotations

import logging

from celery import shared_task
from django.db import models, transaction
from django.utils import timezone

from utils.enum import PaymentStatus, TicketStatus

logger = logging.getLogger(__name__)


@shared_task(
    name="tickets.tasks.release_expired_reservations",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def release_expired_reservations() -> dict:
    from tickets.models import PriceTier, Ticket, TicketPurchase

    now = timezone.now()
    expired_purchases = TicketPurchase.objects.filter(
        payment_status=PaymentStatus.PENDING.value,
        reserved_until__lte=now,
    ).select_for_update(skip_locked=True)

    released_count = 0
    for purchase in expired_purchases:
        with transaction.atomic():
            tickets = Ticket.objects.filter(purchase=purchase)
            if tickets.exists():
                tier_id = tickets.first().price_tier_id
                qty = purchase.quantity
                PriceTier.objects.filter(id=tier_id).update(
                    quantity_reserved=models.F("quantity_reserved") - qty
                )
                tickets.update(status=TicketStatus.CANCELLED.value)
            purchase.payment_status = "expired"
            purchase.save(update_fields=["payment_status"])
            released_count += 1

    if released_count:
        logger.info("Released %d expired reservation(s).", released_count)
    return {"released_count": released_count}


@shared_task(
    name="tickets.tasks.send_purchase_confirmation_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def send_purchase_confirmation_email(purchase_id: str) -> None:
    from tickets.models import TicketPurchase

    purchase = TicketPurchase.objects.filter(id=purchase_id).first()
    if not purchase:
        logger.warning("Purchase %s not found for email.", purchase_id)
        return

    buyer = purchase.buyer
    tickets = purchase.tickets.all()

    subject = f"Ticket Purchase Confirmed — {purchase.event.title}"
    ticket_list = "\n".join(
        [f"  • {t.ticket_code} — ₦{t.price_paid}" for t in tickets]
    )
    message = (
        f"Hi {buyer.username},\n\n"
        f"Your purchase for {purchase.event.title} is confirmed!\n\n"
        f"Tickets:\n{ticket_list}\n\n"
        f"Total: ₦{purchase.total_amount}\n"
        f"Reference: {purchase.transaction_ref}\n\n"
        f"Thank you for using 2geda Tickets."
    )

    try:
        from django.core.mail import send_mail
        from django.conf import settings

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[buyer.email],
            fail_silently=False,
        )
        logger.info("Purchase confirmation email sent to %s", buyer.email)
    except Exception as e:
        logger.error("Failed to send email to %s: %s", buyer.email, e)


@shared_task(
    name="tickets.tasks.send_seller_purchase_notification",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def send_seller_purchase_notification(purchase_id: str) -> None:
    from tickets.models import TicketPurchase
    from notifications.models import Notification
    from utils.enum import NotificationType, NotificationCategory, NotificationPriority

    purchase = TicketPurchase.objects.filter(id=purchase_id).first()
    if not purchase:
        logger.warning("Purchase %s not found for seller notification.", purchase_id)
        return

    seller_user = purchase.event.seller.user

    try:
        Notification.objects.create(
            recipient=seller_user,
            actor=purchase.buyer,
            notification_type=NotificationType.TICKET_PURCHASE.value,
            category=NotificationCategory.TICKETS.value,
            priority=NotificationPriority.NORMAL.value,
            title="New Ticket Purchase!",
            body=(
                f"{purchase.buyer.username} purchased {purchase.quantity} ticket(s) "
                f"for {purchase.event.title}."
            ),
            metadata={
                "purchase_id": str(purchase.id),
                "event_id": str(purchase.event_id),
                "quantity": purchase.quantity,
                "total_amount": str(purchase.total_amount),
            },
        )
        logger.info(
            "Seller notification sent for purchase %s", purchase_id
        )
    except Exception as e:
        logger.error(
            "Failed to send seller notification for %s: %s", purchase_id, e
        )



