from __future__ import annotations

import logging
import os
import re

import requests


logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "9hh9h9h9h9h9h9h9h9h9h9h9h9h")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "0909099090")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14255238886")


class WhatsAppService:

    def __init__(self) -> None:
        self.account_sid = TWILIO_ACCOUNT_SID
        self.auth_token = TWILIO_AUTH_TOKEN
        self.from_number = TWILIO_WHATSAPP_FROM

    def _normalize(self, phone: str) -> str:
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("0"):
            digits = "234" + digits[1:]
        elif not digits.startswith("+"):
            digits = "+" + digits
        return digits

    def send_otp(self, to: str, code: str) -> dict:
        if not self.account_sid or not self.auth_token:
            logger.warning(
                "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set — "
                "WhatsApp OTP not delivered."
            )
            return {"status": "not_configured"}

        normalized = self._normalize(to)
        to_whatsapp = f"whatsapp:{normalized}" if not normalized.startswith("whatsapp:") else normalized

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        payload = {
            "From": self.from_number,
            "To": to_whatsapp,
            "Body": f"{code} is your verification code. Thank you for choosing 2geda Social Network.",
        }

        try:
            resp = requests.post(
                url,
                data=payload,
                auth=(self.account_sid, self.auth_token),
                timeout=20,
            )
            content = {}
            try:
                content = resp.json()
            except Exception:
                pass
            if not resp.ok:
                # Twilio error bodies echo the recipient number, so log codes only.
                logger.error(
                    "Twilio WhatsApp error http=%s code=%s",
                    resp.status_code, content.get("code", "unknown"),
                )
                resp.raise_for_status()
            logger.info("WhatsApp OTP sent (sid=%s)", content.get("sid", "unknown"))
            return content
        except requests.exceptions.RequestException as e:
            logger.error("WhatsApp network error: %s", e)
            return {"error": str(e)}
