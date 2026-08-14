from __future__ import annotations

import logging
import uuid

from clients.email.base import (
    EmailDeliveryError,
    EmailMessage,
    EmailProvider,
    SendResult,
)

logger = logging.getLogger(__name__)


class ConsoleProvider(EmailProvider):
    name = "console"

    def send(self, message: EmailMessage) -> SendResult:
        logger.info(
            "[console-email] subject=%r recipients=%d html_bytes=%d",
            message.subject,
            len(message.to),
            len(message.html),
        )
        return SendResult(message_id=f"console-{uuid.uuid4()}", provider=self.name)


class MemoryProvider(EmailProvider):
    name = "memory"

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> SendResult:
        self.outbox.append(message)
        return SendResult(
            message_id=f"memory-{len(self.outbox)}",
            provider=self.name,
            raw={"index": len(self.outbox) - 1},
        )

    def clear(self) -> None:
        self.outbox.clear()


class FailingProvider(EmailProvider):

    name = "failing"

    def __init__(self, *, detail: str = "forced failure", retryable: bool = True) -> None:
        self.detail = detail
        self.retryable = retryable

    def send(self, message: EmailMessage) -> SendResult:
        raise EmailDeliveryError(
            self.detail, provider=self.name, retryable=self.retryable
        )
