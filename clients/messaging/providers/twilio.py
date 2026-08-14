from __future__ import annotations

import logging
import os

import requests

from clients.messaging.base import (
    Channel,
    ChannelNotSupported,
    Message,
    MessagingError,
    MessagingProvider,
    SendResult,
)
from clients.messaging.phone import to_whatsapp

logger = logging.getLogger(__name__)

API_ROOT = "https://api.twilio.com/2010-04-01"

# Twilio error codes that will never succeed on retry (bad number, opted out,
# unreachable destination). Anything else is treated as transient.
_PERMANENT_CODES = frozenset({21211, 21214, 21606, 21610, 21612, 21614, 63003})


class TwilioProvider(MessagingProvider):

    name = "twilio"
    channels = frozenset({Channel.SMS, Channel.WHATSAPP})

    def __init__(
        self,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        sms_from: str | None = None,
        whatsapp_from: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN", "")
        self.sms_from = sms_from or os.getenv("TWILIO_FROM_NUMBER", "")
        self.whatsapp_from = whatsapp_from or os.getenv("TWILIO_WHATSAPP_FROM", "")
        self.timeout = timeout or int(os.getenv("TWILIO_TIMEOUT", "20"))

    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token)

    def _addresses(self, message: Message) -> tuple[str, str]:
        if message.channel is Channel.WHATSAPP:
            sender = message.sender or self.whatsapp_from
            return to_whatsapp(sender), to_whatsapp(message.to)
        return (message.sender or self.sms_from), message.to

    def send(self, message: Message) -> SendResult:
        if not self.supports(message.channel):
            raise ChannelNotSupported(self.name, message.channel)

        sender, recipient = self._addresses(message)
        if not sender:
            raise MessagingError(
                f"No Twilio sender configured for {message.channel}.",
                provider=self.name,
                channel=message.channel,
                retryable=False,
            )

        try:
            response = requests.post(
                f"{API_ROOT}/Accounts/{self.account_sid}/Messages.json",
                data={"From": sender, "To": recipient, "Body": message.body},
                auth=(self.account_sid, self.auth_token),
                timeout=self.timeout,
            )
            payload = self._parse(response)
            if not response.ok:
                code = payload.get("code")
                # Twilio error bodies echo the recipient number — log codes only.
                logger.error(
                    "Twilio %s error http=%s code=%s",
                    message.channel, response.status_code, code,
                )
                raise MessagingError(
                    f"Twilio rejected the message (code={code})",
                    provider=self.name,
                    channel=message.channel,
                    status_code=response.status_code,
                    retryable=code not in _PERMANENT_CODES,
                )
        except requests.RequestException as exc:
            raise MessagingError(
                f"Twilio request failed: {exc}",
                provider=self.name,
                channel=message.channel,
            ) from exc

        return SendResult(
            message_id=str(payload.get("sid", "")),
            provider=self.name,
            channel=message.channel,
            raw=payload,
        )

    @staticmethod
    def _parse(response) -> dict:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
