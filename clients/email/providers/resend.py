from __future__ import annotations

import logging
import os

import requests

from clients.email.base import (
    EmailDeliveryError,
    EmailMessage,
    EmailProvider,
    SendResult,
)

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.resend.com/emails"

# 4xx other than 429 means the request itself is wrong; retrying cannot help.
_NON_RETRYABLE = range(400, 500)


class ResendProvider(EmailProvider):

    name = "resend"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("RESEND_API_KEY", "")
        self.api_url = (
            api_url or os.getenv("RESEND_EMAIL_URL") or DEFAULT_API_URL
        )
        self.timeout = timeout or int(os.getenv("RESEND_TIMEOUT", "15"))

    def send(self, message: EmailMessage) -> SendResult:
        payload: dict[str, object] = {
            "from": message.from_email,
            "to": list(message.to),
            "subject": message.subject,
            "html": message.html,
        }
        if message.text:
            payload["text"] = message.text
        if message.reply_to:
            payload["reply_to"] = message.reply_to
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)
        if message.headers:
            payload["headers"] = message.headers

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            detail = exc.response.text if exc.response is not None else ""
            raise EmailDeliveryError(
                f"Resend rejected the message ({status}): {detail[:300]}",
                provider=self.name,
                status_code=status,
                retryable=not (status in _NON_RETRYABLE and status != 429),
            ) from exc
        except requests.RequestException as exc:
            raise EmailDeliveryError(
                f"Resend request failed: {exc}", provider=self.name
            ) from exc
        except ValueError as exc:  # malformed JSON body
            raise EmailDeliveryError(
                f"Resend returned an unreadable response: {exc}", provider=self.name
            ) from exc

        return SendResult(
            message_id=str(data.get("id", "")),
            provider=self.name,
            raw=data if isinstance(data, dict) else {},
        )
