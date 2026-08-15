from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Mapping

from clients.payments.base import (
    PaymentInitialization,
    PaymentProvider,
    PaymentVerification,
    WebhookEvent,
)
from clients.payments.registry import get_provider

logger = logging.getLogger(__name__)


class PaymentGateway:

    def __init__(self, provider: PaymentProvider | None = None) -> None:
        self._provider = provider

    @property
    def provider(self) -> PaymentProvider:
        if self._provider is None:
            self._provider = get_provider()
        return self._provider

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def signature_header(self) -> str:
        return self.provider.signature_header

    def initialize(
        self,
        *,
        email: str,
        amount: Decimal | float | int | str,
        reference: str,
        currency: str = "NGN",
        callback_url: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> PaymentInitialization:
        
        result = self.provider.initialize(
            email=email,
            amount=Decimal(str(amount)),
            reference=reference,
            currency=currency,
            callback_url=callback_url,
            metadata=metadata,
        )
        logger.info(
            "Payment initialized via %s (reference=%s)", result.provider, result.reference
        )
        return result

    def verify(self, reference: str) -> PaymentVerification:
        result = self.provider.verify(reference)
        logger.info(
            "Payment verified via %s (reference=%s state=%s)",
            result.provider, result.reference, result.state,
        )
        return result

    def parse_webhook(
        self, body: bytes, headers: Mapping[str, str]
    ) -> WebhookEvent:
        return self.provider.parse_webhook(body, headers)
