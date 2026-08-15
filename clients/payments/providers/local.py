from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal
from typing import Any, Mapping

from clients.payments.base import (
    PaymentError,
    PaymentEventType,
    PaymentInitialization,
    PaymentProvider,
    PaymentState,
    PaymentVerification,
    WebhookEvent,
)

logger = logging.getLogger(__name__)


class MemoryProvider(PaymentProvider):
    name = "memory"
    signature_header = "x-test-signature"

    def __init__(self, *, default_state: PaymentState = PaymentState.SUCCESS) -> None:
        self.charges: dict[str, dict[str, Any]] = {}
        self.default_state = default_state

    def initialize(
        self,
        *,
        email: str,
        amount: Decimal,
        reference: str,
        currency: str = "NGN",
        callback_url: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> PaymentInitialization:
        self.charges[reference] = {
            "email": email,
            "amount": Decimal(amount),
            "currency": currency,
            "state": self.default_state,
            "metadata": dict(metadata or {}),
        }
        return PaymentInitialization(
            authorization_url=f"https://memory.test/pay/{reference}",
            reference=reference,
            access_code=uuid.uuid4().hex[:10],
            provider=self.name,
            raw={"reference": reference},
        )

    def verify(self, reference: str) -> PaymentVerification:
        charge = self.charges.get(reference)
        if charge is None:
            raise PaymentError(
                f"Unknown reference {reference!r}.",
                provider=self.name,
                reference=reference,
                retryable=False,
            )
        return PaymentVerification(
            reference=reference,
            state=charge["state"],
            amount=charge["amount"],
            currency=charge["currency"],
            provider=self.name,
            raw={"reference": reference},
        )

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        payload = json.loads(body or b"{}")
        return WebhookEvent(
            type=PaymentEventType(payload.get("type", PaymentEventType.UNKNOWN.value)),
            reference=str(payload.get("reference", "")),
            amount=Decimal(str(payload.get("amount", 0))),
            provider=self.name,
            raw=payload,
        )
    
    def set_state(self, reference: str, state: PaymentState) -> None:
        self.charges.setdefault(reference, {"amount": Decimal("0"), "currency": "NGN"})
        self.charges[reference]["state"] = state

    def set_amount(self, reference: str, amount: Decimal) -> None:
        self.charges.setdefault(reference, {"state": self.default_state, "currency": "NGN"})
        self.charges[reference]["amount"] = Decimal(amount)


class FailingProvider(PaymentProvider):
    name = "failing"

    def __init__(self, *, detail: str = "forced failure") -> None:
        self.detail = detail

    def initialize(self, **kwargs) -> PaymentInitialization:
        raise PaymentError(self.detail, provider=self.name)

    def verify(self, reference: str) -> PaymentVerification:
        raise PaymentError(self.detail, provider=self.name, reference=reference)

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        raise PaymentError(self.detail, provider=self.name)
