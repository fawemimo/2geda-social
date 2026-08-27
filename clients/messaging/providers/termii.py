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
from clients.messaging.phone import to_national_digits

logger = logging.getLogger(__name__)


def _resolve(explicit: str | None, name: str, default: str = "") -> str:

    if explicit is not None:
        return explicit
    from config import get_config

    return str(get_config(name, default) or default)

DEFAULT_BASE_URL = "https://api.ng.termii.com"

_TERMII_CHANNEL = {
    Channel.SMS: "generic",
    Channel.WHATSAPP: "whatsapp",
}


class TermiiProvider(MessagingProvider):

    name = "termii"
    channels = frozenset({Channel.SMS, Channel.WHATSAPP})

    def __init__(
        self,
        *,
        api_key: str | None = None,
        sender_id: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_key = _resolve(api_key, "TERMII_API_KEY")
        self.sender_id = _resolve(sender_id, "TERMII_SENDER_ID", "2geda")
        self.base_url = (
            base_url or os.getenv("TERMII_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = timeout or int(os.getenv("TERMII_TIMEOUT", "20"))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def send(self, message: Message) -> SendResult:
        if not self.supports(message.channel):
            raise ChannelNotSupported(self.name, message.channel)

        payload = {
            "to": to_national_digits(message.to),
            "from": message.sender or self.sender_id,
            "sms": message.body,
            "type": "plain",
            "channel": _TERMII_CHANNEL[message.channel],
            "api_key": self.api_key,
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/sms/send",
                json=payload,
                timeout=self.timeout,
            )
            data = self._parse(response)

            if not response.ok:
                logger.exception(
                    "Termii %s error http=%s code=%s",
                    message.channel,
                    response.status_code,
                    data.get("code"),
                )
                raise MessagingError(
                    f"Termii rejected the message: {data.get('message', response.status_code)}",
                    provider=self.name,
                    channel=message.channel,
                    status_code=response.status_code,
                    # 4xx other than 429 is a request-shape/credential problem.
                    retryable=not (400 <= response.status_code < 500)
                    or response.status_code == 429,
                )

            # Termii can return HTTP 200 with an error code in the body.
            message_id = data.get("message_id")
            if not message_id and data.get("code") not in (None, "ok"):
                raise MessagingError(
                    f"Termii reported failure: {data.get('message', data.get('code'))}",
                    provider=self.name,
                    channel=message.channel,
                )
        except requests.RequestException as exc:
            raise MessagingError(
                f"Termii request failed: {exc}",
                provider=self.name,
                channel=message.channel,
            ) from exc

        return SendResult(
            message_id=str(message_id or ""),
            provider=self.name,
            channel=message.channel,
            raw=data,
        )

    @staticmethod
    def _parse(response) -> dict:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
