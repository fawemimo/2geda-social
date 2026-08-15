import hashlib
import hmac
import logging
import requests
from django.conf import settings
from tickets.models import Event, PaymentTransaction, Payout, SellerProfile, Ticket
from tickets.services.exceptions import PaymentVerificationFailed
from utils.enum import PaymentStatus, TransactionType
from utils.generators import generate_payout_reference

logger = logging.getLogger(__name__)

PAYSTACK_BASE = "https://api.paystack.co"


class PaymentService:

    @staticmethod
    def _headers() -> dict:
        secret_key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        return {
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def initialize_transaction(
        email: str,
        amount: float,
        reference: str,
        metadata: dict | None = None,
    ) -> dict:
        payload = {
            "email": email,
            "amount": int(amount * 100),
            "reference": reference,
            "callback_url": getattr(settings, "PAYSTACK_CALLBACK_URL", ""),
        }
        if metadata:
            payload["metadata"] = metadata

        resp = requests.post(
            f"{PAYSTACK_BASE}/transaction/initialize",
            json=payload,
            headers=PaymentService._headers(),
            timeout=30,
        )
        data = resp.json()
        if not data.get("status"):
            logger.exception(
                "Paystack init failed: %s",
                data.get("message"),
                extra={"reference": reference},
            )
            raise PaymentVerificationFailed(
                data.get("message", "Paystack initialization failed.")
            )
        return data["data"]

    @staticmethod
    def verify_transaction(reference: str) -> dict:
        resp = requests.get(
            f"{PAYSTACK_BASE}/transaction/verify/{reference}",
            headers=PaymentService._headers(),
            timeout=30,
        )
        data = resp.json()
        if not data.get("status"):
            logger.exception(
                "Paystack verify failed: %s",
                data.get("message"),
                extra={"reference": reference},
            )
            raise PaymentVerificationFailed(
                data.get("message", "Paystack verification failed.")
            )
        return data["data"]

    @staticmethod
    def verify_webhook_signature(payload_body: bytes, signature: str) -> bool:
        secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        expected = hmac.new(
            secret.encode("utf-8"),
            payload_body,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def handle_webhook(event: str, data: dict) -> None:
        if event == "charge.success":
            PaymentService._handle_charge_success(data)
        elif event == "charge.failed":
            PaymentService._handle_charge_failed(data)
        elif event == "refund.processed":
            PaymentService._handle_refund(data)
        else:
            logger.info("Unhandled Paystack webhook event: %s", event)

    @staticmethod
    def _handle_charge_success(data: dict) -> None:
        from tickets.services.ticket_service import TicketService

        reference = data.get("reference", "")
        if not reference:
            return

        existing = PaymentTransaction.objects.filter(reference=reference).first()
        if existing:
            logger.warning("Duplicate webhook for reference: %s", reference)
            return

        TicketService.verify_purchase(reference)

        logger.info("Webhook charge.success processed: %s", reference)

    @staticmethod
    def _handle_charge_failed(data: dict) -> None:
        reference = data.get("reference", "")
        if not reference:
            return
        from tickets.services.ticket_service import TicketService
        from tickets.models import TicketPurchase

        purchase = TicketPurchase.objects.filter(transaction_ref=reference).first()
        if purchase:
            TicketService._release_reservation(purchase)

        logger.info("Webhook charge.failed processed: %s", reference)

    @staticmethod
    def _handle_refund(data: dict) -> None:
        reference = data.get("reference", "")
        if not reference:
            return

        PaymentTransaction.objects.create(
            reference=reference,
            transaction_type=TransactionType.REFUND.value,
            amount=float(data.get("amount", 0)) / 100,
            fees=0,
            status=PaymentStatus.REFUNDED.value,
            notes=f"Paystack refund: {data.get('reason', '')}",
        )

        logger.info("Webhook refund processed: %s", reference)

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

        payout_ref = generate_payout_reference()

        payout = Payout.objects.create(
            seller=seller,
            event=event,
            amount=net_amount,
            fees_deducted=total_fees,
            payout_ref=payout_ref,
            status=PaymentStatus.PENDING.value,
        )

        return payout
