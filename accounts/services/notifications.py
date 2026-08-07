from __future__ import annotations

import logging

from django.conf import settings

from clients.resend.emails import EmailService

from .interfaces import INotificationSender, NotificationPayload


logger = logging.getLogger(__name__)

# Delivered through Resend. `payload.template` names a content body in
# templates/mails/ ("otp", "welcome", ...) which is rendered into the shared
# templates/_template.html design shell. In request-path code prefer dispatching
# the matching Celery task rather than calling this inline.

class EmailNotificationSender(INotificationSender):

    from_name = "2geda Social App"
    default_template = "generic"

    def send(self, payload: NotificationPayload) -> None:
        template = payload.template or self.default_template
        
        values = dict(payload.context or {})
        values.setdefault("body", payload.body)

        response = EmailService(template).send_email(
            to=payload.to,
            obj=payload.body,
            from_email=getattr(settings, "EMAIL_FROM_NAME", self.from_name),
            other_values=values,
            subject=payload.subject,
        )

        if not response:
            raise RuntimeError(f"Resend failed to deliver '{template}'")

        logger.info("Email '%s' sent (id=%s)", template, response.get("id"))

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

