from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .interfaces import INotificationSender, NotificationPayload


logger = logging.getLogger(__name__)

# Direct SMTP send. In request-path code prefer dispatching the

class EmailNotificationSender(INotificationSender):

    def send(self, payload: NotificationPayload) -> None:
        html_body = None
        text_body = payload.body

        if payload.template:
            try:
                html_body = render_to_string(payload.template, payload.context or {})
            except Exception:
                logger.exception("Failed to render email template %s", payload.template)
                html_body = None

        message = EmailMultiAlternatives(
            subject=payload.subject,
            body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=[payload.to],
        )
        if html_body:
            message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)

# Placeholder for the SMS provider (Twilio / Termii / etc). Concrete

class SMSNotificationSender(INotificationSender):

    def send(self, payload: NotificationPayload) -> None:
        logger.info("SMS to %s (subject=%s): %s", payload.to, payload.subject, payload.body)


class WhatsAppNotificationSender(INotificationSender):

    def send(self, payload: NotificationPayload) -> None:
        from clients.whatsapp import WhatsAppService
        code = (payload.context or {}).get("code", payload.body)
        WhatsAppService().send_otp(to=payload.to, code=code)

# Used by tests / dry-runs.

class NullNotificationSender(INotificationSender):

    def send(self, payload: NotificationPayload) -> None:
        logger.debug("NullNotificationSender → %s: %s", payload.to, payload.body)

