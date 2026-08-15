from __future__ import annotations

import logging
from decimal import Decimal
from typing import Mapping

from django.conf import settings

from clients.payments import (
    PaymentError,
    PaymentEventType,
    PaymentGateway,
    PaymentInitialization,
    PaymentVerification,
    WebhookEvent,
)
from tickets.models import Event, PaymentTransaction, Payout, SellerProfile, Ticket
from tickets.services.exceptions import PaymentVerificationFailed
from utils.enum import PaymentStatus, TransactionType
from utils.generators import generate_payout_reference

logger = logging.getLogger(__name__)


class PaymentService:

    @staticmethod
    def gateway() -> PaymentGateway:
        return PaymentGateway()

    @staticmethod
    def initialize_transaction(
        email: str,
        amount: Decimal | float | str,
        reference: str,
        metadata: dict | None = None,
    ) -> PaymentInitialization:
        try:
            return PaymentService.gateway().initialize(
                email=email,
                amount=amount,
                reference=reference,
                callback_url=getattr(settings, "PAYSTACK_CALLBACK_URL", ""),
                metadata=metadata,
            )
        except PaymentError as exc:
            logger.exception("Payment initialization failed: %s", exc)
            raise PaymentVerificationFailed(str(exc)) from exc

    @staticmethod
    def verify_transaction(reference: str) -> PaymentVerification:
        try:
            return PaymentService.gateway().verify(reference)
        except PaymentError as exc:
            logger.error("Payment verification failed: %s", exc)
            raise PaymentVerificationFailed(str(exc)) from exc

    @staticmethod
    def parse_webhook(body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Verify the signature and normalise. Raises on a bad signature."""
        return PaymentService.gateway().parse_webhook(body, headers)


    @staticmethod
    def handle_webhook(event: WebhookEvent) -> None:
        """React to a verified, gateway-neutral payment event."""
        if event.type is PaymentEventType.PAYMENT_SUCCEEDED:
            PaymentService._handle_charge_success(event)
        elif event.type is PaymentEventType.PAYMENT_FAILED:
            PaymentService._handle_charge_failed(event)
        elif event.type is PaymentEventType.REFUND_PROCESSED:
            PaymentService._handle_refund(event)
        else:
            logger.info(
                "Unhandled %s webhook event: %s", event.provider, event.raw.get("event")
            )

    @staticmethod
    def _handle_charge_success(event: WebhookEvent) -> None:
        from tickets.services.ticket_service import TicketService

        if not event.reference:
            return


        TicketService.verify_purchase(event.reference)
        logger.info("Webhook payment.succeeded processed: %s", event.reference)

    @staticmethod
    def _handle_charge_failed(event: WebhookEvent) -> None:
        from tickets.models import TicketPurchase
        from tickets.services.ticket_service import TicketService

        if not event.reference:
            return

        purchase = TicketPurchase.objects.filter(
            transaction_ref=event.reference
        ).first()
        if purchase:
            TicketService._release_reservation(purchase)

        logger.info("Webhook payment.failed processed: %s", event.reference)

    @staticmethod
    def _handle_refund(event: WebhookEvent) -> None:
        if not event.reference:
            return

        PaymentTransaction.objects.create(
            reference=event.reference,
            transaction_type=TransactionType.REFUND.value,
            # Already normalised to major units by the provider.
            amount=event.amount,
            fees=0,
            status=PaymentStatus.REFUNDED.value,
            notes=f"{event.provider} refund: {event.reason}",
        )

        logger.info("Webhook refund processed: %s", event.reference)

    # -- ledger / settlement ------------------------------------------------

    @staticmethod
    def log_transaction(
        seller: SellerProfile,
        transaction_type: str,
        amount: float,
        reference: str,
        event: Event | None = None,
        buyer=None,
        ticket: Ticket | None = None,
        fees: float = 0.0,
        status: str = PaymentStatus.SUCCESSFUL.value,
        notes: str = "",
    ) -> PaymentTransaction:
        return PaymentTransaction.objects.create(
            seller=seller,
            event=event,
            buyer=buyer,
            ticket=ticket,
            transaction_type=transaction_type,
            amount=amount,
            fees=fees,
            reference=reference,
            status=status,
            notes=notes,
        )

    @staticmethod
    def process_payout(seller: SellerProfile, event: Event | None = None) -> Payout:
        transactions = PaymentTransaction.objects.filter(
            seller=seller,
            status=PaymentStatus.SUCCESSFUL.value,
            transaction_type=TransactionType.PURCHASE.value,
        )
        if event:
            transactions = transactions.filter(event=event)

        total_amount = sum(float(t.amount) for t in transactions)
        total_fees = sum(float(t.fees) for t in transactions)
        net_amount = total_amount - total_fees

        payout = Payout.objects.create(
            seller=seller,
            event=event,
            amount=net_amount,
            fees_deducted=total_fees,
            payout_ref=generate_payout_reference(),
            status=PaymentStatus.PENDING.value,
        )

        return payout
