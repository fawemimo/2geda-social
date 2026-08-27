from __future__ import annotations

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

API_BASE = "https://api.flutterwave.com/v3"

_STATE_MAP = {
    "successful": PaymentState.SUCCESS,
    "completed": PaymentState.SUCCESS,
    "failed": PaymentState.FAILED,
    "cancelled": PaymentState.FAILED,
    "pending": PaymentState.PENDING,
}


def _setting(name: str, default: str = "") -> str:
    from config import get_config

    value = get_config(name, default)
    return "" if value is None else str(value)


def _resolve(explicit: str | None, name: str, default: str = "") -> str:
    return explicit if explicit is not None else _setting(name, default)


class FlutterwaveProvider(PaymentProvider):

    name = "flutterwave"
    signature_header = "verif-hash"

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        secret_hash: str | None = None,
        callback_url: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.secret_key = _resolve(secret_key, "FLUTTERWAVE_SECRET_KEY")
        # Separate credential: the value configured in the Flutterwave dashboard
        # and echoed back in the verif-hash header.
        self.secret_hash = _resolve(secret_hash, "FLUTTERWAVE_SECRET_HASH")
        self.callback_url = _resolve(callback_url, "FLUTTERWAVE_CALLBACK_URL")
        self.base_url = (_resolve(base_url, "FLUTTERWAVE_BASE_URL", API_BASE)).rstrip("/")
        self.timeout = timeout or int(_setting("FLUTTERWAVE_TIMEOUT", "30"))

    def is_configured(self) -> bool:
        return bool(self.secret_key)

    def _require_config(self) -> None:
        if not self.is_configured():
            raise PaymentProviderNotConfigured(
                self.name, "Set FLUTTERWAVE_SECRET_KEY."
            )

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
            "tx_ref": reference,
            "amount": str(Decimal(amount)),
            "currency": currency,
            "redirect_url": callback_url or self.callback_url,
            "customer": {"email": email},
        }
        if metadata:
            payload["meta"] = dict(metadata)

        data = self._request("post", "/payments", reference, json=payload)
        if str(data.get("status", "")).lower() != "success":
            raise PaymentInitializationFailed(
                data.get("message", "Flutterwave initialization failed."),
                provider=self.name,
                reference=reference,
            )

        body = data.get("data") or {}
        return PaymentInitialization(
            authorization_url=body.get("link", ""),
            reference=reference,
            access_code="",
            provider=self.name,
            raw=body,
        )

    def verify(self, reference: str) -> PaymentVerification:
        self._require_config()

        data = self._request(
            "get",
            "/transactions/verify_by_reference",
            reference,
            params={"tx_ref": reference},
        )
        if str(data.get("status", "")).lower() != "success":
            raise PaymentVerificationFailed(
                data.get("message", "Flutterwave verification failed."),
                provider=self.name,
                reference=reference,
            )

        body = data.get("data") or {}
        return PaymentVerification(
            reference=str(body.get("tx_ref", reference)),
            state=_STATE_MAP.get(
                str(body.get("status", "")).lower(), PaymentState.FAILED
            ),
            amount=self._to_major(body.get("amount", 0)),
            currency=body.get("currency", "NGN"),
            provider=self.name,
            raw=body,
        )

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        if not self.secret_hash:
            raise PaymentProviderNotConfigured(
                self.name, "Set FLUTTERWAVE_SECRET_HASH to accept webhooks."
            )

        supplied = self._header(headers, self.signature_header)
        if not hmac.compare_digest(self.secret_hash, supplied or ""):
            raise InvalidWebhookSignature(self.name)

        try:
            payload = json.loads(body or b"{}")
        except ValueError as exc:
            raise PaymentError(
                "Webhook body was not valid JSON.",
                provider=self.name,
                retryable=False,
            ) from exc

        data = payload.get("data") or {}
        return WebhookEvent(
            type=self._event_type(payload, data),
            reference=str(data.get("tx_ref", "") or payload.get("txRef", "")),
            amount=self._to_major(data.get("amount", 0)),
            currency=data.get("currency", "NGN"),
            reason=str(data.get("processor_response", "") or data.get("narration", "")),
            provider=self.name,
            raw=payload,
        )

    @staticmethod
    def _event_type(payload: dict, data: dict) -> PaymentEventType:
        event = str(payload.get("event", "")).lower()
        status = str(data.get("status", "")).lower()

        if "refund" in event:
            return PaymentEventType.REFUND_PROCESSED
        if event.startswith("charge"):
            if status in ("successful", "completed"):
                return PaymentEventType.PAYMENT_SUCCEEDED
            if status in ("failed", "cancelled"):
                return PaymentEventType.PAYMENT_FAILED
        return PaymentEventType.UNKNOWN

    @staticmethod
    def _to_major(amount: Any) -> Decimal:
        try:
            return Decimal(str(amount or 0))
        except Exception:
            return Decimal("0")

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str:
        for key, value in headers.items():
            if key.lower() == name.lower():
                return value
        return ""

    def _request(self, method: str, path: str, reference: str, **kwargs) -> dict:
        failure = (
            PaymentInitializationFailed if method == "post" else PaymentVerificationFailed
        )
        try:
            resp = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                timeout=self.timeout,
                **kwargs,
            )
            try:
                data = resp.json()
            except ValueError:
                data = {}
            return data if isinstance(data, dict) else {}
        except requests.RequestException as exc:
            raise failure(
                f"Flutterwave request failed: {exc}",
                provider=self.name,
                reference=reference,
            ) from exc
