import json
import logging
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from accounts.models import User
from tickets.models import Event, PriceTier, Ticket, TicketPurchase
from tickets.services.exceptions import (
    InsufficientTickets,
    PaymentVerificationFailed,
    PricingMismatch,
)
from tickets.services.payment_service import PaymentService
from utils.enum import PaymentStatus, TicketStatus
from utils.generators import generate_ticket_code, generate_transaction_reference

logger = logging.getLogger(__name__)

_RESERVATION_TTL_MINUTES = 15


class TicketService:

    @staticmethod
    def calculate_available(tier: PriceTier) -> int:
        return tier.quantity - tier.quantity_sold - tier.quantity_reserved

    @staticmethod
    def initialize_purchase(
        buyer: User,
        event: Event,
        price_tier_id: str,
        quantity: int,
    ) -> dict:
        """
        Step 1: Reserve tickets, get Paystack authorization URL.
        Uses select_for_update() to prevent overselling.
        """
        import redis
        from django.conf import settings

        redis_client = redis.from_url(settings.CELERY_BROKER_URL)
        lock_key = f"lock:purchase:event:{event.id}"
        lock_acquired = redis_client.set(lock_key, "1", nx=True, ex=30)
        if not lock_acquired:
            raise InsufficientTickets()

        try:
            with transaction.atomic():
                tier = (
                    PriceTier.objects.select_for_update()
                    .filter(id=price_tier_id, event=event, is_active=True)
                    .first()
                )
                if not tier:
                    raise PricingMismatch()

                available = tier.quantity - tier.quantity_sold - tier.quantity_reserved
                if available < quantity:
                    raise InsufficientTickets()

                total_amount = tier.price * quantity
                ref = generate_transaction_reference()
                reserved_until = timezone.now() + timezone.timedelta(
                    minutes=_RESERVATION_TTL_MINUTES
                )

                purchase = TicketPurchase.objects.create(
                    buyer=buyer,
                    event=event,
                    quantity=quantity,
                    total_amount=total_amount,
                    fees_amount=0,
                    transaction_ref=ref,
                    reserved_until=reserved_until,
                )

                PriceTier.objects.filter(id=tier.id).update(
                    quantity_reserved=models.F("quantity_reserved") + quantity
                )

                for _ in range(quantity):
                    Ticket.objects.create(
                        event=event,
                        buyer=buyer,
                        price_tier=tier,
                        purchase=purchase,
                        ticket_code=generate_ticket_code(),
                        price_paid=tier.price,
                        status=TicketStatus.RESERVED.value,
                    )

                initialization = PaymentService.initialize_transaction(
                    email=buyer.email,
                    amount=total_amount,
                    reference=ref,
                    metadata={
                        "purchase_id": str(purchase.id),
                        "event_id": str(event.id),
                        "buyer_id": str(buyer.id),
                        "quantity": quantity,
                    },
                )

                # Field names still say "paystack" for schema compatibility;
                # the values now come from whichever gateway is configured.
                purchase.paystack_access_code = initialization.access_code
                purchase.paystack_authorization_url = initialization.authorization_url
                purchase.paystack_data = initialization.raw
                purchase.save(
                    update_fields=[
                        "paystack_access_code",
                        "paystack_authorization_url",
                        "paystack_data",
                    ]
                )

                return {
                    "purchase_id": str(purchase.id),
                    "transaction_ref": ref,
                    "authorization_url": purchase.paystack_authorization_url,
                    "access_code": purchase.paystack_access_code,
                    "total_amount": float(total_amount),
                }
        finally:
            redis_client.delete(lock_key)

    @staticmethod
    def verify_purchase(reference: str) -> dict:
        purchase = TicketPurchase.objects.filter(transaction_ref=reference).first()
        if not purchase:
            raise PaymentVerificationFailed("Purchase record not found.")

        if purchase.payment_status == PaymentStatus.SUCCESSFUL.value:
            return {
                "status": "already_confirmed",
                "purchase_id": str(purchase.id),
                "tickets": list(
                    purchase.tickets.values("id", "ticket_code", "qr_code_data")
                ),
            }

        verification = PaymentService.verify_transaction(reference)

        if not verification.is_successful:
            TicketService._release_reservation(purchase)
            raise PaymentVerificationFailed("Payment was not successful.")

        # `verification.amount` is a Decimal in major units for every gateway —
        # the kobo/naira conversion is the provider's job, not ours.
        if verification.amount < Decimal(str(purchase.total_amount)):
            TicketService._release_reservation(purchase)
            raise PaymentVerificationFailed("Payment amount mismatch.")

        with transaction.atomic():
            purchase.payment_status = PaymentStatus.SUCCESSFUL.value
            purchase.paystack_data = verification.raw
            purchase.save(update_fields=["payment_status", "paystack_data"])

            tickets = Ticket.objects.filter(purchase=purchase)
            now = timezone.now()
            tickets_to_update = []
            for ticket in tickets:
                ticket.status = TicketStatus.SOLD.value
                ticket.purchased_at = now
                ticket.qr_code_data = json.dumps(
                    {
                        "ticket_code": ticket.ticket_code,
                        "event_id": str(ticket.event_id),
                        "event_title": ticket.event.title,
                        "buyer_name": ticket.buyer.username,
                    }
                )
                tickets_to_update.append(ticket)

            Ticket.objects.bulk_update(
                tickets_to_update,
                fields=["status", "purchased_at", "qr_code_data"],
            )

            PriceTier.objects.filter(
                id=tickets.first().price_tier_id
            ).update(
                quantity_sold=models.F("quantity_sold") + purchase.quantity,
                quantity_reserved=models.F("quantity_reserved") - purchase.quantity,
            )

            Event.objects.filter(id=purchase.event_id).update(
                total_tickets_sold=models.F("total_tickets_sold") + purchase.quantity,
                total_revenue=models.F("total_revenue") + purchase.total_amount,
                tickets_available=models.F("tickets_available") - purchase.quantity,
            )

        return {
            "status": "confirmed",
            "purchase_id": str(purchase.id),
            "tickets": list(
                Ticket.objects.filter(purchase=purchase).values(
                    "id", "ticket_code", "qr_code_data"
                )
            ),
        }

    @staticmethod
    def _release_reservation(purchase: TicketPurchase) -> None:
        with transaction.atomic():
            purchase.payment_status = PaymentStatus.FAILED.value
            purchase.save(update_fields=["payment_status"])

            tickets = Ticket.objects.filter(purchase=purchase)
            if tickets.exists():
                tier_id = tickets.first().price_tier_id
                PriceTier.objects.filter(id=tier_id).update(
                    quantity_reserved=models.F("quantity_reserved") - purchase.quantity
                )
                tickets.update(status=TicketStatus.CANCELLED.value)

    @staticmethod
    def verify_ticket_code(code: str) -> Ticket | None:
        return Ticket.objects.filter(
            ticket_code=code, is_deleted=False
        ).select_related("event", "buyer").first()

    @staticmethod
    def get_buyer_tickets(buyer: User):
        return Ticket.objects.filter(
            buyer=buyer,
            is_deleted=False,
            status=TicketStatus.SOLD.value,
        ).select_related("event", "price_tier").order_by("-purchased_at")
