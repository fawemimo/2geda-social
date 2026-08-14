from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: tuple[str, ...]
    subject: str
    html: str
    text: str = ""
    from_email: str = ""
    reply_to: str | None = None
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.to:
            raise ValueError("EmailMessage requires at least one recipient.")
        if not self.from_email:
            raise ValueError("EmailMessage requires a sender address.")


@dataclass(frozen=True, slots=True)
class SendResult:
    message_id: str
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return True


class EmailDeliveryError(RuntimeError):

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


class EmailProvider(ABC):
    name: ClassVar[str] = "base"

    @abstractmethod
    def send(self, message: EmailMessage) -> SendResult:
        """Deliver `message`. Returns SendResult or raises EmailDeliveryError."""

    def __repr__(self) -> str: 
        return f"<{type(self).__name__} name={self.name!r}>"
