from datetime import datetime
import html
import os
import re
import requests
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_API_URL = os.getenv("RESEND_EMAIL_URL") or "https://api.resend.com/emails"
RESEND_TIMEOUT = int(os.getenv("RESEND_TIMEOUT", "15"))
BASE_TEMPLATE = "_template.html"
CONTENT_DIR = "mails"


class EmailService:

    def __init__(self, template_name):
        self.template_name = self._resolve_template(template_name)
        self.sender = os.getenv("EMAIL_SENDER")
        self.api_key = RESEND_API_KEY

    @staticmethod
    def _resolve_template(template_name):
        name = str(template_name).strip().lstrip("/")
        if "/" in name:
            return name
        if not name.endswith(".txt"):
            name = f"{name}.txt"
        return f"{CONTENT_DIR}/{name}"

    @staticmethod
    def _to_plain_text(html_content):
        # Keep line structure that strip_tags would otherwise collapse.
        text = re.sub(r"<br\s*/?>", "\n", html_content, flags=re.I)
        text = re.sub(r"</(?:p|div|h[1-6]|tr|li|table)>", "\n\n", text, flags=re.I)
        text = html.unescape(strip_tags(text))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def send_email(self, *args, **kwargs):
        return self._send_email(*args, **kwargs)

    def _send_email(
        self,
        to: list[str],
        obj,
        from_email: str = "2geda Social App",
        other_values=None,
        subject=None,
    ):

        try:
            current_datetime = datetime.now()
            action_date_time = current_datetime.strftime("%a, %b %d, %Y - %I:%M %p")
            site = "https://2geda.net/"
            subject = subject if subject is not None else "Notification"

            context = {
                "obj": obj,
                "site": site,
                "other_values": other_values if other_values else "None",
                "action_date_time": action_date_time,
                "subject": subject,
                "MEDIA_URL": settings.MEDIA_URL,
            }

            if isinstance(other_values, dict):
                context.update(other_values)

            content = render_to_string(
                template_name=self.template_name,
                context=context,
            )

            html_content = render_to_string(
                template_name=BASE_TEMPLATE,
                context={**context, "content": mark_safe(content)},
            )

            if isinstance(to, str):
                to = [to]

            payload = {
                "from": f"{from_email} <{self.sender}>",
                "to": to,
                "subject": subject,
                "html": html_content,
                "text": self._to_plain_text(content),
            }

            response = requests.post(
                RESEND_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=RESEND_TIMEOUT,
            )
            response.raise_for_status()

            data = response.json()
            logger.info(f"Email sent successfully: {data}")
            return data

        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else ""
            logger.exception(f"Failed to send email: {e} - {body}")

        except requests.RequestException as e:
            logger.exception(f"Failed to send email: {e}")

        except Exception as e:
            logger.exception(f"Failed to send email: {e}")
