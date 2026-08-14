from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar


class Channel(str, Enum):
    SMS = "sms"
    WHATSAPP = "whatsapp"

    def __str__(self) -> str:  # keeps log lines readable
        return self.value


@dataclass(frozen=True, slots=True)
class Message:
    to: str
    body: str
    channel: Channel = Channel.SMS
    sender: str | None = None
    #: Correlation id echoed to providers that support one.
    reference: str | None = None

    def __post_init__(self) -> None:
        if not self.to:
            raise ValueError("Message requires a recipient.")
        if not self.body:
            raise ValueError("Message requires a body.")
        if not isinstance(self.channel, Channel):
            raise ValueError(f"Unknown channel: {self.channel!r}")


@dataclass(frozen=True, slots=True)
class SendResult:
    message_id: str
    provider: str
    channel: Channel
    raw: dict[str, Any] = field(default_factory=dict)
    #: Providers tried and failed before this one succeeded.
    attempts: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        # Returning a SendResult always means success, even without an id.
        return True


class MessagingError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        channel: Channel | None = None,
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.channel = channel
        self.status_code = status_code
        self.retryable = retryable


class ChannelNotSupported(MessagingError):
    def __init__(self, provider: str, channel: Channel) -> None:
        super().__init__(
            f"Provider {provider!r} does not support the {channel} channel.",
            provider=provider,
            channel=channel,
            retryable=False,
        )


class AllProvidersFailed(MessagingError):

    def __init__(self, channel: Channel, failures: dict[str, str]) -> None:
        detail = "; ".join(f"{name}: {err}" for name, err in failures.items())
        super().__init__(
            f"No provider could deliver the {channel} message — {detail}",
            provider="failover",
            channel=channel,
            retryable=True,
        )
        self.failures = failures


class AllChannelsFailed(MessagingError):
    """Every channel in the preference order was tried and none delivered.

    Distinct from AllProvidersFailed: that means one channel exhausted its
    vendors, this means the whole WhatsApp-then-SMS ladder is down.
    """

    def __init__(self, channels: tuple[Channel, ...], failures: dict[str, str]) -> None:
        detail = "; ".join(f"{name}: {err}" for name, err in failures.items())
        super().__init__(
            f"No channel could deliver the message "
            f"(tried {', '.join(c.value for c in channels)}) — {detail}",
            provider="channel-fallback",
            retryable=True,
        )
        self.channels = channels
        self.failures = failures


class MessagingProvider(ABC):

    #: Stable key used by the registry and in logs.
    name: ClassVar[str] = "base"
    #: Channels this provider advertises. The router never dispatches outside it.
    channels: ClassVar[frozenset[Channel]] = frozenset()

    def supports(self, channel: Channel) -> bool:
        return channel in self.channels

    def is_configured(self) -> bool:
        return True

    @abstractmethod
    def send(self, message: Message) -> SendResult:
        """Deliver `message`. Returns SendResult or raises MessagingError."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        chans = ",".join(sorted(c.value for c in self.channels))
        return f"<{type(self).__name__} name={self.name!r} channels={chans}>"
