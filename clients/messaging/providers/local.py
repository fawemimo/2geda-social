from __future__ import annotations

import logging
import uuid

from clients.messaging.base import (
    Channel,
    ChannelNotSupported,
    Message,
    MessagingError,
    MessagingProvider,
    SendResult,
)

logger = logging.getLogger(__name__)

ALL_CHANNELS = frozenset({Channel.SMS, Channel.WHATSAPP})


class ConsoleProvider(MessagingProvider):
    """Logs instead of sending. Never logs the body — it carries OTP codes."""

    name = "console"
    channels = ALL_CHANNELS

    def send(self, message: Message) -> SendResult:
        logger.info(
            "[console-%s] recipient_set=1 body_len=%d", message.channel, len(message.body)
        )
        return SendResult(
            message_id=f"console-{uuid.uuid4()}",
            provider=self.name,
            channel=message.channel,
        )


class MemoryProvider(MessagingProvider):
    """Captures messages in a list. The test-suite transport."""

    name = "memory"
    channels = ALL_CHANNELS

    def __init__(self, *, channels: frozenset[Channel] | None = None) -> None:
        self.outbox: list[Message] = []
        if channels is not None:
            self.channels = channels

    def send(self, message: Message) -> SendResult:
        if not self.supports(message.channel):
            raise ChannelNotSupported(self.name, message.channel)
        self.outbox.append(message)
        return SendResult(
            message_id=f"memory-{len(self.outbox)}",
            provider=self.name,
            channel=message.channel,
            raw={"index": len(self.outbox) - 1},
        )

    def clear(self) -> None:
        self.outbox.clear()


class FailingProvider(MessagingProvider):
    """Always raises. Lets tests drive the failover chain deterministically."""

    name = "failing"
    channels = ALL_CHANNELS

    def __init__(
        self,
        *,
        detail: str = "forced failure",
        retryable: bool = True,
        name: str | None = None,
    ) -> None:
        self.detail = detail
        self.retryable = retryable
        self.calls: list[Message] = []
        if name:
            self.name = name

    def send(self, message: Message) -> SendResult:
        self.calls.append(message)
        raise MessagingError(
            self.detail,
            provider=self.name,
            channel=message.channel,
            retryable=self.retryable,
        )
