from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, Mapping

import requests

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

API_BASE = "https://qa.interswitchng.com/collections/api/v1/pay"

_STATE_MAP = {
    "00": PaymentState.SUCCESS,
    "10": PaymentState.PENDING,
    "09": PaymentState.FAILED,
    "Z6": PaymentState.FAILED,
}

_EVENT_MAP = {
    "SUCCESSFUL": PaymentEventType.PAYMENT_SUCCEEDED,
    "FAILED": PaymentEventType.PAYMENT_FAILED,
}


def _setting(name: str, default: str = "") -> str:
    from config import get_config

    value = get_config(name, default)
    return "" if value is None else str(value)


def _resolve(explicit: str | None, name: str, default: str = "") -> str:
    return explicit if explicit is not None else _setting(name, default)


class InterswitchProvider(PaymentProvider):

    name = "interswitch"
    signature_header = "x-interswitch-signature"

    def __init__(
        self,
        *,
        merchant_code: str | None = None,
        pay_item_id: str | None = None,
        mac_key: str | None = None,
        callback_url: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.merchant_code = _resolve(merchant_code, "INTERSWITCH_MERCHANT_CODE")
        self.pay_item_id = _resolve(pay_item_id, "INTERSWITCH_PAY_ITEM_ID")
        self.mac_key = _resolve(mac_key, "INTERSWITCH_MAC_KEY")
        self.callback_url = _resolve(callback_url, "INTERSWITCH_CALLBACK_URL")
        self.base_url = (_resolve(base_url, "INTERSWITCH_BASE_URL", API_BASE)).rstrip("/")
        self.timeout = timeout or int(_setting("INTERSWITCH_TIMEOUT", "30"))

    def is_configured(self) -> bool:
        return bool(self.merchant_code and self.mac_key)

    def _require_config(self) -> None:
        if not self.is_configured():
            raise PaymentProviderNotConfigured(
                self.name,
                "Set INTERSWITCH_MERCHANT_CODE and INTERSWITCH_MAC_KEY.",
            )

    def _generate_hash(self, reference: str, amount_minor: int) -> str:
        raw = f"{self.merchant_code}{reference}{amount_minor}{self.mac_key}"
        return hashlib.sha512(raw.encode("utf-8")).hexdigest()

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

        amount_minor = int(Decimal(amount) * 100)
        txn_hash = self._generate_hash(reference, amount_minor)

        payload: dict[str, Any] = {
            "merchant_code": self.merchant_code,
            "pay_item_id": self.pay_item_id,
            "txn_ref": reference,
            "amount": amount_minor,
            "currency": self._currency_code(currency),
            "cust_id": email,
            "site_redirect_url": callback_url or self.callback_url,
            "hash": txn_hash,
        }

        try:
            resp = requests.post(
                f"{self.base_url}/initialize",
                json=payload,
                timeout=self.timeout,
            )
            data = self._json(resp)
        except requests.RequestException as exc:
            raise PaymentInitializationFailed(
                f"Interswitch request failed: {exc}",
                provider=self.name,
                reference=reference,
            ) from exc

        if not data.get("paymentUrl"):
            raise PaymentInitializationFailed(
                data.get("message", "Interswitch initialization failed."),
                provider=self.name,
                reference=reference,
            )

        return PaymentInitialization(
            authorization_url=data.get("paymentUrl", ""),
            reference=reference,
            access_code=data.get("accessCode", ""),
            provider=self.name,
            raw=data,
        )

    def verify(self, reference: str) -> PaymentVerification:
        self._require_config()

        try:
            resp = requests.get(
                f"{self.base_url}/status",
                params={"merchantcode": self.merchant_code, "reference": reference},
                timeout=self.timeout,
            )
            data = self._json(resp)
        except requests.RequestException as exc:
            raise PaymentVerificationFailed(
                f"Interswitch request failed: {exc}",
                provider=self.name,
                reference=reference,
            ) from exc

        response_code = str(data.get("ResponseCode", ""))
        return PaymentVerification(
            reference=reference,
            state=_STATE_MAP.get(response_code, PaymentState.FAILED),
            amount=self._to_major(data.get("Amount", 0)),
            currency="NGN",
            provider=self.name,
            raw=data,
        )

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        self._require_config()

        try:
            payload = json.loads(body or b"{}")
        except ValueError as exc:
            raise PaymentError(
                "Webhook body was not valid JSON.",
                provider=self.name,
                retryable=False,
            ) from exc

        event_status = str(payload.get("status", "")).upper()
        data = payload.get("data") or payload
        return WebhookEvent(
            type=_EVENT_MAP.get(event_status, PaymentEventType.UNKNOWN),
            reference=str(data.get("txn_ref", "") or data.get("reference", "")),
            amount=self._to_major(data.get("amount", 0)),
            currency="NGN",
            reason=str(data.get("response_description", "")),
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
    def _currency_code(currency: str) -> str:
        return {"NGN": "566", "USD": "840"}.get(currency.upper(), "566")

    @staticmethod
    def _json(response) -> dict:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
