from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar, Mapping


class PaymentState(str, Enum):

    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"

    def __str__(self) -> str:
        return self.value


class PaymentEventType(str, Enum):
    PAYMENT_SUCCEEDED = "payment_succeeded"
    PAYMENT_FAILED = "payment_failed"
    REFUND_PROCESSED = "refund_processed"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PaymentInitialization:
    authorization_url: str
    reference: str
    access_code: str = ""
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class PaymentVerification:

    reference: str
    state: PaymentState
    amount: Decimal = Decimal("0")
    currency: str = "NGN"
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_successful(self) -> bool:
        return self.state is PaymentState.SUCCESS


@dataclass(frozen=True, slots=True)
class WebhookEvent:

    type: PaymentEventType
    reference: str = ""
    amount: Decimal = Decimal("0")
    currency: str = "NGN"
    reason: str = ""
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentError(RuntimeError):

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        reference: str | None = None,
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.reference = reference
        self.status_code = status_code
        self.retryable = retryable


class PaymentInitializationFailed(PaymentError):
    pass


class PaymentVerificationFailed(PaymentError):
    pass


class InvalidWebhookSignature(PaymentError):

    def __init__(self, provider: str) -> None:
        super().__init__(
            "Webhook signature verification failed.",
            provider=provider,
            retryable=False,
        )


class PaymentProviderNotConfigured(PaymentError):
    def __init__(self, provider: str, detail: str = "") -> None:
        super().__init__(
            f"Payment provider {provider!r} is not configured. {detail}".strip(),
            provider=provider,
            retryable=False,
        )


class PaymentProvider(ABC):
    name: ClassVar[str] = "base"
    signature_header: ClassVar[str] = ""

    def is_configured(self) -> bool:
        return True

    @abstractmethod
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
        """Start a charge. `amount` is in major units."""

    @abstractmethod
    def verify(self, reference: str) -> PaymentVerification:
        """Ask the gateway what happened to `reference`."""

    @abstractmethod
    def parse_webhook(
        self, body: bytes, headers: Mapping[str, str]
    ) -> WebhookEvent:
        """Verify the signature and normalise the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name!r}>"
