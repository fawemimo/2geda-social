"""Contract tests for clients.payments.

Paystack and Flutterwave disagree on money units, status vocabulary and webhook
authentication. The suite below asserts that both arrive at the same normalised
result — that agreement is the whole point of the abstraction.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import requests

from clients.payments import (
    InvalidWebhookSignature,
    PaymentError,
    PaymentEventType,
    PaymentGateway,
    PaymentInitialization,
    PaymentProvider,
    PaymentProviderNotConfigured,
    PaymentState,
    PaymentVerification,
    WebhookEvent,
    available_providers,
    get_provider,
    register_provider,
)
from clients.payments.providers.flutterwave import FlutterwaveProvider
from clients.payments.providers.local import FailingProvider, MemoryProvider
from clients.payments.providers.paystack import PaystackProvider

REF = "REF-2041548BCAC14A048BF1"


def response(payload: dict, status_code: int = 200):
    r = MagicMock(status_code=status_code, ok=200 <= status_code < 300)
    r.json.return_value = payload
    return r


# --------------------------------------------------------------------------
# Provider factories + canned gateway payloads
# --------------------------------------------------------------------------

PAYSTACK_INIT = {
    "status": True,
    "data": {
        "authorization_url": "https://checkout.paystack.com/0peioxfhpn",
        "access_code": "0peioxfhpn",
        "reference": REF,
    },
}
# Paystack speaks kobo: 2,000,000 kobo == NGN 20,000.
PAYSTACK_VERIFY = {
    "status": True,
    "data": {"reference": REF, "status": "success", "amount": 2_000_000, "currency": "NGN"},
}

FLUTTERWAVE_INIT = {
    "status": "success",
    "data": {"link": "https://checkout.flutterwave.com/v3/hosted/pay/abc123"},
}
# Flutterwave speaks naira directly: 20000 == NGN 20,000.
FLUTTERWAVE_VERIFY = {
    "status": "success",
    "data": {"tx_ref": REF, "status": "successful", "amount": 20000, "currency": "NGN"},
}


def _paystack():
    return PaystackProvider(secret_key="sk_test", callback_url="https://cb.test")


def _flutterwave():
    return FlutterwaveProvider(
        secret_key="FLWSECK_TEST", secret_hash="hash123",
        callback_url="https://cb.test",
    )


def _memory():
    return MemoryProvider()


def drive(provider, method, *args, **kwargs):
    """Call `provider.method` with its HTTP layer stubbed."""
    if isinstance(provider, PaystackProvider):
        target = "clients.payments.providers.paystack.requests"
        payload = PAYSTACK_INIT if method == "initialize" else PAYSTACK_VERIFY
        with patch(target) as rq:
            rq.post.return_value = response(payload)
            rq.get.return_value = response(payload)
            rq.RequestException = requests.RequestException
            return getattr(provider, method)(*args, **kwargs)
    if isinstance(provider, FlutterwaveProvider):
        payload = FLUTTERWAVE_INIT if method == "initialize" else FLUTTERWAVE_VERIFY
        with patch(
            "clients.payments.providers.flutterwave.requests.request",
            return_value=response(payload),
        ):
            return getattr(provider, method)(*args, **kwargs)
    return getattr(provider, method)(*args, **kwargs)


PROVIDERS = [
    pytest.param(_paystack, id="paystack"),
    pytest.param(_flutterwave, id="flutterwave"),
    pytest.param(_memory, id="memory"),
]


@pytest.mark.parametrize("factory", PROVIDERS)
class TestProviderContract:

    def test_is_a_payment_provider(self, factory):
        assert isinstance(factory(), PaymentProvider)

    def test_has_a_stable_name(self, factory):
        name = factory().name
        assert isinstance(name, str) and name and name != "base"

    def test_initialize_returns_a_normalised_result(self, factory):
        provider = factory()
        result = drive(
            provider, "initialize",
            email="buyer@example.com", amount=Decimal("20000"), reference=REF,
        )
        assert isinstance(result, PaymentInitialization)
        assert result.provider == provider.name
        assert result.authorization_url.startswith("http")
        assert result.reference == REF

    def test_verify_returns_a_normalised_result(self, factory):
        provider = factory()
        if isinstance(provider, MemoryProvider):
            provider.initialize(
                email="b@e.com", amount=Decimal("20000"), reference=REF
            )
        result = drive(provider, "verify", REF)
        assert isinstance(result, PaymentVerification)
        assert result.provider == provider.name
        assert result.state is PaymentState.SUCCESS
        assert result.is_successful is True

    def test_amount_is_decimal_in_major_units(self, factory):
        """The crux: kobo and naira both arrive as NGN 20,000."""
        provider = factory()
        if isinstance(provider, MemoryProvider):
            provider.initialize(
                email="b@e.com", amount=Decimal("20000"), reference=REF
            )
        result = drive(provider, "verify", REF)
        assert isinstance(result.amount, Decimal)
        assert result.amount == Decimal("20000")


class TestGatewaysAgree:
    """Same real-world transaction, two gateways, identical normalised view."""

    def test_verification_matches_across_gateways(self):
        results = {
            p.name: drive(p, "verify", REF) for p in (_paystack(), _flutterwave())
        }
        assert {r.state for r in results.values()} == {PaymentState.SUCCESS}
        assert {r.amount for r in results.values()} == {Decimal("20000")}
        assert {r.currency for r in results.values()} == {"NGN"}
        assert {r.reference for r in results.values()} == {REF}

    def test_initialization_matches_across_gateways(self):
        results = {
            p.name: drive(
                p, "initialize", email="b@e.com", amount=Decimal("20000"), reference=REF
            )
            for p in (_paystack(), _flutterwave())
        }
        for result in results.values():
            assert result.authorization_url.startswith("https://")
            assert result.reference == REF


class TestWireFormats:
    """Each gateway is driven the way its own API expects."""

    def test_paystack_converts_naira_to_kobo_on_the_way_out(self):
        provider = _paystack()
        with patch("clients.payments.providers.paystack.requests.post",
                   return_value=response(PAYSTACK_INIT)) as post:
            provider.initialize(
                email="b@e.com", amount=Decimal("20000"), reference=REF
            )
        assert post.call_args.kwargs["json"]["amount"] == 2_000_000

    def test_flutterwave_sends_naira_unchanged(self):
        provider = _flutterwave()
        with patch("clients.payments.providers.flutterwave.requests.request",
                   return_value=response(FLUTTERWAVE_INIT)) as req:
            provider.initialize(
                email="b@e.com", amount=Decimal("20000"), reference=REF
            )
        body = req.call_args.kwargs["json"]
        assert body["amount"] == "20000"
        assert body["tx_ref"] == REF
        assert body["customer"]["email"] == "b@e.com"

    def test_paystack_verify_uses_the_reference_path(self):
        provider = _paystack()
        with patch("clients.payments.providers.paystack.requests.get",
                   return_value=response(PAYSTACK_VERIFY)) as get:
            provider.verify(REF)
        assert get.call_args.args[0].endswith(f"/transaction/verify/{REF}")

    def test_flutterwave_verify_uses_tx_ref_query(self):
        provider = _flutterwave()
        with patch("clients.payments.providers.flutterwave.requests.request",
                   return_value=response(FLUTTERWAVE_VERIFY)) as req:
            provider.verify(REF)
        assert req.call_args.kwargs["params"] == {"tx_ref": REF}


# --------------------------------------------------------------------------
# Webhooks — different auth schemes, one normalised event
# --------------------------------------------------------------------------

def paystack_signed(payload: dict, secret: str = "sk_test") -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return body, {"x-paystack-signature": signature}


class TestWebhookNormalisation:

    def test_paystack_charge_success(self):
        body, headers = paystack_signed(
            {"event": "charge.success",
             "data": {"reference": REF, "amount": 2_000_000, "currency": "NGN"}}
        )
        event = _paystack().parse_webhook(body, headers)
        assert event.type is PaymentEventType.PAYMENT_SUCCEEDED
        assert event.reference == REF
        assert event.amount == Decimal("20000")

    def test_flutterwave_charge_completed_maps_to_the_same_event(self):
        """Different event name and status field — same normalised type."""
        body = json.dumps(
            {"event": "charge.completed",
             "data": {"tx_ref": REF, "status": "successful", "amount": 20000}}
        ).encode()
        event = _flutterwave().parse_webhook(body, {"verif-hash": "hash123"})
        assert event.type is PaymentEventType.PAYMENT_SUCCEEDED
        assert event.reference == REF
        assert event.amount == Decimal("20000")

    def test_both_gateways_produce_the_same_event(self):
        ps_body, ps_headers = paystack_signed(
            {"event": "charge.success",
             "data": {"reference": REF, "amount": 2_000_000}}
        )
        fw_body = json.dumps(
            {"event": "charge.completed",
             "data": {"tx_ref": REF, "status": "successful", "amount": 20000}}
        ).encode()

        a = _paystack().parse_webhook(ps_body, ps_headers)
        b = _flutterwave().parse_webhook(fw_body, {"verif-hash": "hash123"})

        assert (a.type, a.reference, a.amount) == (b.type, b.reference, b.amount)

    def test_paystack_failure_and_refund_events(self):
        for name, expected in (
            ("charge.failed", PaymentEventType.PAYMENT_FAILED),
            ("refund.processed", PaymentEventType.REFUND_PROCESSED),
        ):
            body, headers = paystack_signed({"event": name, "data": {"reference": REF}})
            assert _paystack().parse_webhook(body, headers).type is expected

    def test_flutterwave_failed_charge(self):
        body = json.dumps(
            {"event": "charge.completed",
             "data": {"tx_ref": REF, "status": "failed", "amount": 20000}}
        ).encode()
        event = _flutterwave().parse_webhook(body, {"verif-hash": "hash123"})
        assert event.type is PaymentEventType.PAYMENT_FAILED

    def test_unknown_event_is_not_an_error(self):
        body, headers = paystack_signed({"event": "customer.created", "data": {}})
        assert _paystack().parse_webhook(body, headers).type is PaymentEventType.UNKNOWN

    def test_header_lookup_is_case_insensitive(self):
        body, headers = paystack_signed({"event": "charge.success", "data": {}})
        upper = {k.upper(): v for k, v in headers.items()}
        assert _paystack().parse_webhook(body, upper).type is (
            PaymentEventType.PAYMENT_SUCCEEDED
        )


class TestWebhookAuthentication:

    def test_paystack_rejects_a_forged_signature(self):
        body = json.dumps({"event": "charge.success", "data": {}}).encode()
        with pytest.raises(InvalidWebhookSignature):
            _paystack().parse_webhook(body, {"x-paystack-signature": "forged"})

    def test_paystack_rejects_a_tampered_body(self):
        body, headers = paystack_signed(
            {"event": "charge.success", "data": {"amount": 100}}
        )
        tampered = body.replace(b'"amount": 100', b'"amount": 999')
        with pytest.raises(InvalidWebhookSignature):
            _paystack().parse_webhook(tampered, headers)

    def test_paystack_rejects_a_missing_signature(self):
        body = json.dumps({"event": "charge.success", "data": {}}).encode()
        with pytest.raises(InvalidWebhookSignature):
            _paystack().parse_webhook(body, {})

    def test_flutterwave_rejects_a_wrong_secret_hash(self):
        body = json.dumps({"event": "charge.completed", "data": {}}).encode()
        with pytest.raises(InvalidWebhookSignature):
            _flutterwave().parse_webhook(body, {"verif-hash": "wrong"})

    def test_flutterwave_refuses_webhooks_without_a_configured_hash(self):
        provider = FlutterwaveProvider(secret_key="k", secret_hash="")
        with pytest.raises(PaymentProviderNotConfigured):
            provider.parse_webhook(b"{}", {"verif-hash": "anything"})

    def test_malformed_json_is_a_payment_error_not_a_crash(self):
        signature = hmac.new(b"sk_test", b"not json", hashlib.sha512).hexdigest()
        with pytest.raises(PaymentError):
            _paystack().parse_webhook(
                b"not json", {"x-paystack-signature": signature}
            )


class TestFailureContract:

    def test_paystack_api_failure_is_wrapped(self):
        provider = _paystack()
        with patch("clients.payments.providers.paystack.requests.get",
                   return_value=response({"status": False, "message": "not found"})):
            with pytest.raises(PaymentError) as exc:
                provider.verify(REF)
        assert exc.value.provider == "paystack"
        assert "not found" in str(exc.value)

    def test_flutterwave_api_failure_is_wrapped(self):
        provider = _flutterwave()
        with patch("clients.payments.providers.flutterwave.requests.request",
                   return_value=response({"status": "error", "message": "no tx"})):
            with pytest.raises(PaymentError) as exc:
                provider.verify(REF)
        assert exc.value.provider == "flutterwave"

    def test_network_errors_are_wrapped(self):
        with patch("clients.payments.providers.paystack.requests.get",
                   side_effect=requests.ConnectionError("down")):
            with pytest.raises(PaymentError):
                _paystack().verify(REF)
        with patch("clients.payments.providers.flutterwave.requests.request",
                   side_effect=requests.ConnectionError("down")):
            with pytest.raises(PaymentError):
                _flutterwave().verify(REF)

    def test_no_gateway_exception_escapes(self):
        with patch("clients.payments.providers.paystack.requests.post",
                   side_effect=requests.Timeout("slow")):
            try:
                _paystack().initialize(
                    email="b@e.com", amount=Decimal("1"), reference=REF
                )
            except PaymentError:
                pass
            except requests.RequestException:
                pytest.fail("gateway exception leaked past the provider boundary")

    def test_unconfigured_provider_raises_before_any_call(self):
        with pytest.raises(PaymentProviderNotConfigured):
            PaystackProvider(secret_key="").verify(REF)
        with pytest.raises(PaymentProviderNotConfigured):
            FlutterwaveProvider(secret_key="").verify(REF)

    def test_is_configured_reports_honestly(self):
        assert PaystackProvider(secret_key="sk").is_configured()
        assert not PaystackProvider(secret_key="").is_configured()
        assert FlutterwaveProvider(secret_key="fk").is_configured()
        assert not FlutterwaveProvider(secret_key="").is_configured()

    def test_failed_status_maps_to_failed_not_success(self):
        provider = _paystack()
        with patch("clients.payments.providers.paystack.requests.get",
                   return_value=response(
                       {"status": True,
                        "data": {"reference": REF, "status": "abandoned", "amount": 0}})):
            result = provider.verify(REF)
        assert result.state is PaymentState.FAILED
        assert result.is_successful is False


# --------------------------------------------------------------------------
# Registry + gateway facade
# --------------------------------------------------------------------------

class TestRegistry:

    def test_builtins_registered(self):
        for name in ("paystack", "flutterwave", "memory"):
            assert name in available_providers()

    def test_unknown_provider_is_a_clear_error(self):
        with pytest.raises(ValueError, match="Unknown payment provider"):
            get_provider("stripe")

    def test_settings_select_the_gateway(self, settings):
        settings.PAYMENT_PROVIDER = "flutterwave"
        assert isinstance(get_provider(), FlutterwaveProvider)
        settings.PAYMENT_PROVIDER = "paystack"
        assert isinstance(get_provider(), PaystackProvider)

    def test_a_new_gateway_needs_no_existing_code_change(self):
        class MonnifyProvider(PaymentProvider):
            name = "monnify-test"

            def initialize(self, **kwargs) -> PaymentInitialization:
                return PaymentInitialization(
                    authorization_url="https://monnify.test/pay",
                    reference=kwargs["reference"], provider=self.name,
                )

            def verify(self, reference: str) -> PaymentVerification:
                return PaymentVerification(
                    reference=reference, state=PaymentState.SUCCESS,
                    amount=Decimal("1"), provider=self.name,
                )

            def parse_webhook(self, body, headers) -> WebhookEvent:
                return WebhookEvent(type=PaymentEventType.UNKNOWN, provider=self.name)

        register_provider("monnify-test", MonnifyProvider, replace=True)
        assert isinstance(get_provider("monnify-test"), PaymentProvider)

    def test_duplicate_registration_rejected(self):
        with pytest.raises(ValueError, match="already registered"):
            register_provider("paystack", MemoryProvider)


class TestPaymentGateway:

    def test_coerces_amount_to_decimal(self):
        provider = MemoryProvider()
        PaymentGateway(provider).initialize(
            email="b@e.com", amount=20000, reference=REF
        )
        assert provider.charges[REF]["amount"] == Decimal("20000")

    def test_exposes_the_provider_identity(self):
        gateway = PaymentGateway(_paystack())
        assert gateway.name == "paystack"
        assert gateway.signature_header == "x-paystack-signature"

    def test_failure_propagates(self):
        with pytest.raises(PaymentError):
            PaymentGateway(FailingProvider()).verify(REF)
