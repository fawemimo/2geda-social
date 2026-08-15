from __future__ import annotations

import logging
import os
import uuid

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

DEFAULT_BASE_URL = "https://api.ebulksms.com"


class EBulkSMSProvider(MessagingProvider):

    name = "ebulksms"
    channels = frozenset({Channel.SMS})

    def __init__(
        self,
        *,
        username: str | None = None,
        api_key: str | None = None,
        sender_id: str | None = None,
        base_url: str | None = None,
        whatsapp_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.username = username or os.getenv("EBULKSMS_USERNAME", "")
        self.api_key = api_key or os.getenv("EBULKSMS_APIKEY", "")
        self.sender_id = sender_id or os.getenv("EBULKSMS_SENDER_ID", "2geda")
        self.base_url = (
            base_url or os.getenv("EBULKSMS_BASEURL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.whatsapp_url = whatsapp_url or os.getenv("EBULKSMS_WHATSAPP_URL", "")
        self.timeout = timeout or int(os.getenv("EBULKSMS_TIMEOUT", "20"))

        # Shadow the class attribute so capability reflects configuration.
        supported = {Channel.SMS}
        if self.whatsapp_url:
            supported.add(Channel.WHATSAPP)
        self.channels = frozenset(supported)

    def is_configured(self) -> bool:
        return bool(self.username and self.api_key)

    def send(self, message: Message) -> SendResult:
        if not self.supports(message.channel):
            raise ChannelNotSupported(self.name, message.channel)

        recipient = to_national_digits(message.to)
        msg_id = message.reference or uuid.uuid4().hex[:12]

        if message.channel is Channel.WHATSAPP:
            url = self.whatsapp_url
            payload = {
                "username": self.username,
                "apikey": self.api_key,
                "sender": message.sender or self.sender_id,
                "messagetext": message.body,
                "recipient": recipient,
            }
        else:
            url = f"{self.base_url}/sendsms.json"
            payload = {
                "SMS": {
                    "auth": {"username": self.username, "apikey": self.api_key},
                    "message": {
                        "sender": message.sender or self.sender_id,
                        "messagetext": message.body,
                        "flash": "0",
                    },
                    "recipients": {"gsm": [{"msidn": recipient, "msgid": msg_id}]},
                }
            }

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            data = self._parse(response)

            if not response.ok:
                logger.exception(
                    "EBulkSMS %s error http=%s", message.channel, response.status_code
                )
                raise MessagingError(
                    f"EBulkSMS rejected the message (HTTP {response.status_code})",
                    provider=self.name,
                    channel=message.channel,
                    status_code=response.status_code,
                    retryable=not (400 <= response.status_code < 500)
                    or response.status_code == 429,
                )

            # EBulkSMS signals failure in the body with HTTP 200.
            status = str(
                data.get("response", {}).get("status", "")
                if isinstance(data, dict)
                else ""
            )
            if status.upper() != "SUCCESS":
                raise MessagingError(
                    f"EBulkSMS reported failure: {status or 'unknown'}",
                    provider=self.name,
                    channel=message.channel,
                    # Credit exhaustion / bad credentials will not fix themselves.
                    retryable="INSUFFICIENT" not in status.upper(),
                )
        except requests.RequestException as exc:
            raise MessagingError(
                f"EBulkSMS request failed: {exc}",
                provider=self.name,
                channel=message.channel,
            ) from exc

        return SendResult(
            message_id=msg_id,
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
