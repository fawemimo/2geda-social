from __future__ import annotations

import logging
from typing import Sequence

from clients.messaging.base import (
    AllChannelsFailed,
    Channel,
    Message,
    MessagingError,
    MessagingProvider,
    SendResult,
)
from clients.messaging.phone import normalize
from clients.messaging.registry import get_messaging_provider

logger = logging.getLogger(__name__)

DEFAULT_OTP_TEMPLATE = (
    "{code} is your verification code. "
    "Thank you for choosing 2geda Social Network."
)

#: OTP channel preference. WhatsApp first — cheaper, richer, and the default
#: when the user expresses no preference. SMS is the fallback because it
#: reaches handsets that WhatsApp cannot.
DEFAULT_OTP_CHANNEL_ORDER: tuple[Channel, ...] = (Channel.WHATSAPP, Channel.SMS)


def resolve_channel_order(
    preferred: Channel | str | None = None,
    *,
    allowed: Sequence[Channel] = DEFAULT_OTP_CHANNEL_ORDER,
) -> tuple[Channel, ...]:
    """Preferred channel first, then the rest of the ladder.

    `None` (user expressed no preference) yields the default order, so WhatsApp
    leads. An explicit choice is honoured first but still falls back.
    """
    ladder = tuple(allowed)
    if preferred is None:
        return ladder
    channel = preferred if isinstance(preferred, Channel) else Channel(str(preferred).lower())
    return (channel,) + tuple(c for c in ladder if c != channel)


class MessagingService:

    def __init__(self, provider: MessagingProvider | None = None) -> None:
        self._provider = provider

    def provider_for(self, channel: Channel) -> MessagingProvider:
        if self._provider is not None:
            return self._provider
        return get_messaging_provider(channel)

    def send(
        self,
        *,
        to: str,
        body: str,
        channel: Channel = Channel.SMS,
        sender: str | None = None,
        reference: str | None = None,
    ) -> SendResult:
        message = Message(
            to=normalize(to),
            body=body,
            channel=channel,
            sender=sender,
            reference=reference,
        )
        result = self.provider_for(channel).send(message)
        logger.info(
            "%s delivered via %s (id=%s%s)",
            channel,
            result.provider,
            result.message_id,
            f", after {', '.join(result.attempts)}" if result.attempts else "",
        )
        return result

    def send_sms(self, *, to: str, body: str, **kwargs) -> SendResult:
        return self.send(to=to, body=body, channel=Channel.SMS, **kwargs)

    def send_whatsapp(self, *, to: str, body: str, **kwargs) -> SendResult:
        return self.send(to=to, body=body, channel=Channel.WHATSAPP, **kwargs)

    def send_with_fallback(
        self,
        *,
        to: str,
        body: str,
        channels: Sequence[Channel],
        **kwargs,
    ) -> SendResult:
        if not channels:
            raise ValueError("send_with_fallback requires at least one channel.")

        order = tuple(channels)
        failures: dict[str, str] = {}

        for channel in order:
            try:
                return self.send(to=to, body=body, channel=channel, **kwargs)
            except MessagingError as exc:
                failures[channel.value] = str(exc)
                logger.warning(
                    "OTP channel %s failed (%s); falling back", channel, exc
                )
                continue

        raise AllChannelsFailed(order, failures)

    def send_otp(
        self,
        *,
        to: str,
        code: str,
        channel: Channel | str | None = None,
        fallback: bool = True,
        template: str | None = None,
        **kwargs,
    ) -> SendResult:
        body = (template or DEFAULT_OTP_TEMPLATE).format(code=code)
        order = resolve_channel_order(channel)
        if not fallback:
            order = order[:1]
        return self.send_with_fallback(to=to, body=body, channels=order, **kwargs)
