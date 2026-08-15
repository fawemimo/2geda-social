from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from decimal import Decimal
from typing import Any, Mapping

import requests
from django.conf import settings

from clients.payments.base import (
    InvalidWebhookSignature,
    PaymentError,
    PaymentEventType,
    PaymentInitialization,
    PaymentInitializationFailed,
    PaymentProvider,
    PaymentProviderNotConfigured,
    PaymentState,
    PaymentVerification,
    PaymentVerificationFailed,
    WebhookEvent,
)

logger = logging.getLogger(__name__)

API_BASE = "https://api.paystack.co"

_STATE_MAP = {
    "success": PaymentState.SUCCESS,
    "failed": PaymentState.FAILED,
    "abandoned": PaymentState.FAILED,
    "reversed": PaymentState.FAILED,
    "pending": PaymentState.PENDING,
    "ongoing": PaymentState.PENDING,
}

_EVENT_MAP = {
    "charge.success": PaymentEventType.PAYMENT_SUCCEEDED,
    "charge.failed": PaymentEventType.PAYMENT_FAILED,
    "refund.processed": PaymentEventType.REFUND_PROCESSED,
}


def _setting(name: str, default: str = "") -> str:
    return getattr(settings, name, None) or os.getenv(name, default) or ""


def _resolve(explicit: str | None, name: str, default: str = "") -> str:
    """Explicit wins, including an explicit empty string."""
    return explicit if explicit is not None else _setting(name, default)


class PaystackProvider(PaymentProvider):

    name = "paystack"
    signature_header = "x-paystack-signature"

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        callback_url: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.secret_key = _resolve(secret_key, "PAYSTACK_SECRET_KEY")
        self.callback_url = _resolve(callback_url, "PAYSTACK_CALLBACK_URL")
        self.base_url = (_resolve(base_url, "PAYSTACK_BASE_URL", API_BASE)).rstrip("/")
        self.timeout = timeout or int(_setting("PAYSTACK_TIMEOUT", "30"))

    def is_configured(self) -> bool:
        return bool(self.secret_key)

    def _require_config(self) -> None:
        if not self.is_configured():
            raise PaymentProviderNotConfigured(self.name, "Set PAYSTACK_SECRET_KEY.")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def initialize(
        self,
        *,
        email: str,
        amount: Decimal,
        reference: str,
        currency: str = "NGN",
        callback_url: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> PaymentInitialization:
        self._require_config()

        payload: dict[str, Any] = {
            "email": email,
            "amount": int(Decimal(amount) * 100),
            "reference": reference,
            "currency": currency,
            "callback_url": callback_url or self.callback_url,
        }
        if metadata:
            payload["metadata"] = dict(metadata)

        data = self._post("/transaction/initialize", payload, reference)
        if not data.get("status"):
            raise PaymentInitializationFailed(
                data.get("message", "Paystack initialization failed."),
                provider=self.name,
                reference=reference,
            )

        body = data.get("data") or {}
        return PaymentInitialization(
            authorization_url=body.get("authorization_url", ""),
            reference=body.get("reference", reference),
            access_code=body.get("access_code", ""),
            provider=self.name,
            raw=body,
        )

    def verify(self, reference: str) -> PaymentVerification:
        self._require_config()

        data = self._get(f"/transaction/verify/{reference}", reference)
        if not data.get("status"):
            raise PaymentVerificationFailed(
                data.get("message", "Paystack verification failed."),
                provider=self.name,
                reference=reference,
            )

        body = data.get("data") or {}
        return PaymentVerification(
            reference=body.get("reference", reference),
            state=_STATE_MAP.get(str(body.get("status", "")).lower(), PaymentState.FAILED),
            amount=self._to_major(body.get("amount", 0)),
            currency=body.get("currency", "NGN"),
            provider=self.name,
            raw=body,
        )

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        self._require_config()

        signature = self._header(headers, self.signature_header)
        expected = hmac.new(
            self.secret_key.encode("utf-8"), body, hashlib.sha512
        ).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            raise InvalidWebhookSignature(self.name)

        try:
            payload = json.loads(body or b"{}")
        except ValueError as exc:
            raise PaymentError(
                "Webhook body was not valid JSON.",
                provider=self.name,
                retryable=False,
            ) from exc

        event_name = str(payload.get("event", ""))
        data = payload.get("data") or {}
        return WebhookEvent(
            type=_EVENT_MAP.get(event_name, PaymentEventType.UNKNOWN),
            reference=str(data.get("reference", "")),
            amount=self._to_major(data.get("amount", 0)),
            currency=data.get("currency", "NGN"),
            reason=str(data.get("reason", "") or data.get("gateway_response", "")),
            provider=self.name,
            raw=payload,
        )

    @staticmethod
    def _to_major(minor: Any) -> Decimal:
        try:
            return Decimal(str(minor or 0)) / Decimal("100")
        except Exception:
            return Decimal("0")

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str:
        for key, value in headers.items():
            if key.lower() == name.lower():
                return value
        return ""

    def _post(self, path: str, payload: dict, reference: str) -> dict:
        try:
            resp = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            return self._json(resp)
        except requests.RequestException as exc:
            raise PaymentInitializationFailed(
                f"Paystack request failed: {exc}",
                provider=self.name,
                reference=reference,
            ) from exc

    def _get(self, path: str, reference: str) -> dict:
        try:
            resp = requests.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            return self._json(resp)
        except requests.RequestException as exc:
            raise PaymentVerificationFailed(
                f"Paystack request failed: {exc}",
                provider=self.name,
                reference=reference,
            ) from exc

    @staticmethod
    def _json(response) -> dict:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
