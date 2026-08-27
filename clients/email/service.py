from __future__ import annotations

import logging
import os
from typing import Any, Iterable

from clients.email.base import EmailMessage, EmailProvider, SendResult
from clients.email.registry import get_provider
from clients.email.rendering import EmailRenderer

from config import get_str

logger = logging.getLogger(__name__)

DEFAULT_FROM_NAME = "2geda Social App"
DEFAULT_SUBJECT = "Notification"


def _as_tuple(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


class EmailService:

    def __init__(
        self,
        template_name: str,
        *,
        provider: EmailProvider | None = None,
        renderer: EmailRenderer | None = None,
        sender: str | None = None,
    ) -> None:
        self.template_name = template_name
        self._provider = provider
        self.renderer = renderer or EmailRenderer()
        self.sender = sender or get_str("EMAIL_SENDER", "")

    @property
    def provider(self) -> EmailProvider:
        # Resolved lazily so constructing the service never touches settings
        # or network SDKs.
        if self._provider is None:
            self._provider = get_provider()
        return self._provider

    def build_message(
        self,
        to: str | Iterable[str],
        obj: Any,
        *,
        from_email: str = DEFAULT_FROM_NAME,
        other_values: Any = None,
        subject: str | None = None,
        reply_to: str | None = None,
        cc: str | Iterable[str] | None = None,
        bcc: str | Iterable[str] | None = None,
    ) -> EmailMessage:
        resolved_subject = subject if subject is not None else DEFAULT_SUBJECT
        context = self.renderer.build_context(
            obj=obj, subject=resolved_subject, other_values=other_values
        )
        body = self.renderer.render(self.template_name, context)

        # Sender composition is provider-independent, so it happens here and
        # every provider receives an identical From value.
        sender = f"{from_email} <{self.sender}>" if self.sender else from_email

        return EmailMessage(
            to=_as_tuple(to),
            subject=resolved_subject,
            html=body.html,
            text=body.text,
            from_email=sender,
            reply_to=reply_to,
            cc=_as_tuple(cc),
            bcc=_as_tuple(bcc),
        )

    def send_email(
        self,
        to: str | Iterable[str],
        obj: Any,
        from_email: str = DEFAULT_FROM_NAME,
        other_values: Any = None,
        subject: str | None = None,
        **extra: Any,
    ) -> SendResult:
        message = self.build_message(
            to,
            obj,
            from_email=from_email,
            other_values=other_values,
            subject=subject,
            **extra,
        )
        result = self.provider.send(message)
        logger.info(
            "Email '%s' sent via %s (id=%s)",
            self.template_name,
            result.provider,
            result.message_id,
        )
        return result
