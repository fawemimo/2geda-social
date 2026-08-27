from __future__ import annotations

import logging
import os

from clients.email.base import (
    EmailDeliveryError,
    EmailMessage,
    EmailProvider,
    SendResult,
)

from config import get_config

logger = logging.getLogger(__name__)

# Permanent SES failures — retrying these will never succeed.
_NON_RETRYABLE_CODES = frozenset(
    {
        "MessageRejected",
        "MailFromDomainNotVerifiedException",
        "ConfigurationSetDoesNotExistException",
        "AccountSendingPausedException",
    }
)


class SESProvider(EmailProvider):

    name = "ses"

    def __init__(
        self,
        *,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client=None,
    ) -> None:
        self._client = client
        self._region = region or get_config("AWS_S3_REGION_NAME")
        self._access_key_id = access_key_id or get_config("AWS_ACCESS_KEY_ID_SES")
        self._secret_access_key = (
            secret_access_key or get_config("AWS_SECRET_ACCESS_KEY_SES")
        )

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "ses",
                region_name=self._region,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
            )
        return self._client

    def send(self, message: EmailMessage) -> SendResult:
        from botocore.exceptions import BotoCoreError, ClientError

        body: dict[str, dict[str, str]] = {
            "Html": {"Data": message.html, "Charset": "UTF-8"},
        }
        if message.text:
            body["Text"] = {"Data": message.text, "Charset": "UTF-8"}

        destination: dict[str, list[str]] = {"ToAddresses": list(message.to)}
        if message.cc:
            destination["CcAddresses"] = list(message.cc)
        if message.bcc:
            destination["BccAddresses"] = list(message.bcc)

        kwargs: dict[str, object] = {
            "Source": message.from_email,
            "Destination": destination,
            "Message": {
                "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                "Body": body,
            },
        }
        if message.reply_to:
            kwargs["ReplyToAddresses"] = [message.reply_to]

        try:
            response = self.client.send_email(**kwargs)
        except ClientError as exc:
            error = exc.response.get("Error", {}) if exc.response else {}
            code = error.get("Code", "")
            status = (
                exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if exc.response
                else None
            )
            raise EmailDeliveryError(
                f"SES rejected the message ({code}): {error.get('Message', exc)}",
                provider=self.name,
                status_code=status,
                retryable=code not in _NON_RETRYABLE_CODES,
            ) from exc
        except BotoCoreError as exc:
            raise EmailDeliveryError(
                f"SES request failed: {exc}", provider=self.name
            ) from exc

        return SendResult(
            message_id=str(response.get("MessageId", "")),
            provider=self.name,
            raw=response if isinstance(response, dict) else {},
        )
