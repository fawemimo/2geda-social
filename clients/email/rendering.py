from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe

# The single design shell every mail is rendered into.
BASE_TEMPLATE = "_template.html"
# Where the per-mail content bodies live.
CONTENT_DIR = "mails"

SITE_URL = "https://2geda.net/"


@dataclass(frozen=True, slots=True)
class RenderedBody:
    html: str
    text: str


def resolve_template(template_name: str) -> str:
    """Accept "otp", "otp.txt" or "mails/otp.txt" and normalise to a path."""
    name = str(template_name).strip().lstrip("/")
    if "/" in name:
        return name
    if not name.endswith(".txt"):
        name = f"{name}.txt"
    return f"{CONTENT_DIR}/{name}"


def to_plain_text(html_content: str) -> str:
    """Best-effort plain-text alternative, for clients that refuse HTML."""
    # Keep line structure that strip_tags would otherwise collapse.
    text = re.sub(r"<br\s*/?>", "\n", html_content, flags=re.I)
    text = re.sub(r"</(?:p|div|h[1-6]|tr|li|table)>", "\n\n", text, flags=re.I)
    text = html_module.unescape(strip_tags(text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class EmailRenderer:

    def __init__(
        self,
        *,
        base_template: str = BASE_TEMPLATE,
        site_url: str = SITE_URL,
    ) -> None:
        self.base_template = base_template
        self.site_url = site_url

    def build_context(
        self,
        *,
        obj: Any,
        subject: str,
        other_values: Any = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "obj": obj,
            "site": self.site_url,
            "other_values": other_values if other_values else "None",
            "action_date_time": datetime.now().strftime("%a, %b %d, %Y - %I:%M %p"),
            "subject": subject,
            "MEDIA_URL": settings.MEDIA_URL,
        }
        if isinstance(other_values, dict):
            context.update(other_values)
        return context

    def render(self, template_name: str, context: dict[str, Any]) -> RenderedBody:
        content = render_to_string(
            template_name=resolve_template(template_name),
            context=context,
        )
        html = render_to_string(
            template_name=self.base_template,
            context={**context, "content": mark_safe(content)},
        )
        # Derive text from the body, not the shell — the shell is chrome.
        return RenderedBody(html=html, text=to_plain_text(content))
