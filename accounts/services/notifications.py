from __future__ import annotations

import logging

from django.conf import settings

from clients.email import EmailProvider, EmailService

from .interfaces import INotificationSender, NotificationPayload


logger = logging.getLogger(__name__)

class EmailNotificationSender(INotificationSender):

    from_name = "2geda Social App"
    default_template = "generic"

    def __init__(self, provider: EmailProvider | None = None) -> None:
        
        self._provider = provider

    def send(self, payload: NotificationPayload) -> None:
        template = payload.template or self.default_template

        values = dict(payload.context or {})
        values.setdefault("body", payload.body)

        EmailService(template, provider=self._provider).send_email(
            to=payload.to,
            obj=payload.body,
            from_email=getattr(settings, "EMAIL_FROM_NAME", self.from_name),
            other_values=values,
            subject=payload.subject,
        )

class SMSNotificationSender(INotificationSender):

    def send(self, payload: NotificationPayload) -> None:
        logger.info("SMS dispatched (subject=%s)", payload.subject)


class WhatsAppNotificationSender(INotificationSender):

    def send(self, payload: NotificationPayload) -> None:
        from clients.whatsapp import WhatsAppService
        code = (payload.context or {}).get("code", payload.body)
        WhatsAppService().send_otp(to=payload.to, code=code)


class NullNotificationSender(INotificationSender):

    def send(self, payload: NotificationPayload) -> None:
        logger.debug("NullNotificationSender dropped message (subject=%s)", payload.subject)

