"""Contract, failover and provider tests for clients.messaging."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from clients.messaging import (
    AllChannelsFailed,
    AllProvidersFailed,
    Channel,
    ChannelNotSupported,
    FailoverProvider,
    InvalidPhoneNumber,
    Message,
    MessagingError,
    MessagingProvider,
    MessagingService,
    SendResult,
    available_providers,
    build_chain,
    configured_chain,
    get_provider,
    normalize,
    register_provider,
    resolve_channel_order,
)
from clients.messaging.providers.ebulksms import EBulkSMSProvider
from clients.messaging.providers.local import (
    ConsoleProvider,
    FailingProvider,
    MemoryProvider,
)
from clients.messaging.providers.termii import TermiiProvider
from clients.messaging.providers.twilio import TwilioProvider


def msg(**overrides) -> Message:
    base = dict(to="+2348012345678", body="483920 is your code", channel=Channel.SMS)
    base.update(overrides)
    return Message(**base)


def ok_response(payload: dict, status: int = 200):
    r = MagicMock(status_code=status, ok=200 <= status < 300)
    r.json.return_value = payload
    return r


# --------------------------------------------------------------------------
# Phone normalisation — canonical E.164 for every input shape
# --------------------------------------------------------------------------

class TestPhoneNormalisation:

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("08012345678", "+2348012345678"),      # NG national
            ("0801 234 5678", "+2348012345678"),    # spaced
            ("+2348012345678", "+2348012345678"),   # already E.164
            ("2348012345678", "+2348012345678"),    # missing plus
            ("002348012345678", "+2348012345678"),  # 00 international prefix
            ("+234 801-234-5678", "+2348012345678"),
            ("8012345678", "+2348012345678"),       # bare subscriber
        ],
    )
    def test_every_shape_reaches_the_same_e164(self, raw, expected):
        assert normalize(raw) == expected

    def test_regression_local_numbers_keep_the_plus(self):
        """The old clients/whatsapp.py dropped the + for national numbers."""
        assert normalize("08012345678").startswith("+")

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "+", "12"])
    def test_rejects_unusable_input(self, bad):
        with pytest.raises(InvalidPhoneNumber):
            normalize(bad)

    def test_honours_another_country_code(self):
        assert normalize("07700900123", country_code="44") == "+447700900123"


# --------------------------------------------------------------------------
# Message / SendResult invariants
# --------------------------------------------------------------------------

class TestMessage:

    def test_requires_recipient_and_body(self):
        with pytest.raises(ValueError, match="recipient"):
            msg(to="")
        with pytest.raises(ValueError, match="body"):
            msg(body="")

    def test_rejects_unknown_channel(self):
        with pytest.raises(ValueError, match="channel"):
            msg(channel="carrier-pigeon")

    def test_send_result_is_always_truthy(self):
        assert bool(SendResult(message_id="", provider="x", channel=Channel.SMS)) is True


# --------------------------------------------------------------------------
# The substitutability contract — same assertions for every provider
# --------------------------------------------------------------------------

def _twilio():
    p = TwilioProvider(account_sid="AC1", auth_token="t", sms_from="+15550001111",
                       whatsapp_from="whatsapp:+15550002222")
    p._resp = ok_response({"sid": "SM123"})
    return p, "clients.messaging.providers.twilio.requests.post"


def _termii():
    p = TermiiProvider(api_key="k", sender_id="2geda")
    p._resp = ok_response({"message_id": "TM123", "code": "ok"})
    return p, "clients.messaging.providers.termii.requests.post"


def _ebulk():
    p = EBulkSMSProvider(username="u", api_key="k")
    p._resp = ok_response({"response": {"status": "SUCCESS"}})
    return p, "clients.messaging.providers.ebulksms.requests.post"


def _memory():
    return MemoryProvider(), None


def _console():
    return ConsoleProvider(), None


PROVIDERS = [
    pytest.param(_twilio, id="twilio"),
    pytest.param(_termii, id="termii"),
    pytest.param(_ebulk, id="ebulksms"),
    pytest.param(_memory, id="memory"),
    pytest.param(_console, id="console"),
]


@pytest.mark.parametrize("factory", PROVIDERS)
class TestProviderContract:

    @staticmethod
    def _send(factory, message):
        provider, patch_target = factory()
        if patch_target:
            with patch(patch_target, return_value=provider._resp):
                return provider, provider.send(message)
        return provider, provider.send(message)

    def test_is_a_messaging_provider(self, factory):
        provider, _ = factory()
        assert isinstance(provider, MessagingProvider)

    def test_declares_a_name_and_channels(self, factory):
        provider, _ = factory()
        assert provider.name not in ("", "base")
        assert provider.channels, "provider must advertise at least one channel"
        assert all(isinstance(c, Channel) for c in provider.channels)

    def test_sms_returns_send_result(self, factory):
        provider, result = self._send(factory, msg())
        assert isinstance(result, SendResult)
        assert result.provider == provider.name
        assert result.channel is Channel.SMS
        assert isinstance(result.message_id, str)

    def test_advertised_channels_all_work(self, factory):
        provider, _ = factory()
        for channel in provider.channels:
            _, result = self._send(factory, msg(channel=channel))
            assert result.channel is channel

    def test_unadvertised_channel_is_refused_consistently(self, factory):
        provider, _ = factory()
        missing = set(Channel) - set(provider.channels)
        for channel in missing:
            with pytest.raises(ChannelNotSupported):
                provider.send(msg(channel=channel))


class TestProviderWireFormats:
    """Each vendor gets the address shape it expects — from one canonical input."""

    def test_twilio_sms_uses_plain_e164(self):
        p = TwilioProvider(account_sid="AC1", auth_token="t", sms_from="+15550001111")
        with patch("clients.messaging.providers.twilio.requests.post",
                   return_value=ok_response({"sid": "SM1"})) as post:
            p.send(msg())
        assert post.call_args.kwargs["data"]["To"] == "+2348012345678"

    def test_twilio_whatsapp_uses_the_whatsapp_prefix(self):
        p = TwilioProvider(account_sid="AC1", auth_token="t",
                           whatsapp_from="whatsapp:+15550002222")
        with patch("clients.messaging.providers.twilio.requests.post",
                   return_value=ok_response({"sid": "SM1"})) as post:
            p.send(msg(channel=Channel.WHATSAPP))
        data = post.call_args.kwargs["data"]
        assert data["To"] == "whatsapp:+2348012345678"
        assert data["From"] == "whatsapp:+15550002222"

    def test_termii_strips_the_plus_and_maps_the_channel(self):
        p = TermiiProvider(api_key="k")
        with patch("clients.messaging.providers.termii.requests.post",
                   return_value=ok_response({"message_id": "1", "code": "ok"})) as post:
            p.send(msg())
            assert post.call_args.kwargs["json"]["to"] == "2348012345678"
            assert post.call_args.kwargs["json"]["channel"] == "generic"
            p.send(msg(channel=Channel.WHATSAPP))
            assert post.call_args.kwargs["json"]["channel"] == "whatsapp"

    def test_ebulksms_builds_the_nested_sms_envelope(self):
        p = EBulkSMSProvider(username="u", api_key="k", sender_id="2geda")
        with patch("clients.messaging.providers.ebulksms.requests.post",
                   return_value=ok_response({"response": {"status": "SUCCESS"}})) as post:
            p.send(msg())
        body = post.call_args.kwargs["json"]["SMS"]
        assert body["auth"] == {"username": "u", "apikey": "k"}
        assert body["recipients"]["gsm"][0]["msidn"] == "2348012345678"
        assert body["message"]["sender"] == "2geda"

    def test_ebulksms_is_sms_only_until_whatsapp_is_configured(self):
        assert EBulkSMSProvider(username="u", api_key="k").channels == frozenset(
            {Channel.SMS}
        )
        enabled = EBulkSMSProvider(
            username="u", api_key="k", whatsapp_url="https://example.invalid/wa"
        )
        assert Channel.WHATSAPP in enabled.channels


class TestFailureContract:
    """Failures raise MessagingError — never a vendor-native exception."""

    def test_twilio_permanent_code_is_not_retryable(self):
        p = TwilioProvider(account_sid="AC1", auth_token="t", sms_from="+1555")
        with patch("clients.messaging.providers.twilio.requests.post",
                   return_value=ok_response({"code": 21211}, status=400)):
            with pytest.raises(MessagingError) as exc:
                p.send(msg())
        assert exc.value.retryable is False  # invalid number

    def test_twilio_transient_code_is_retryable(self):
        p = TwilioProvider(account_sid="AC1", auth_token="t", sms_from="+1555")
        with patch("clients.messaging.providers.twilio.requests.post",
                   return_value=ok_response({"code": 30001}, status=500)):
            with pytest.raises(MessagingError) as exc:
                p.send(msg())
        assert exc.value.retryable is True

    def test_network_errors_are_wrapped(self):
        for provider, target in (
            (TwilioProvider(account_sid="A", auth_token="t", sms_from="+1"),
             "clients.messaging.providers.twilio.requests.post"),
            (TermiiProvider(api_key="k"),
             "clients.messaging.providers.termii.requests.post"),
            (EBulkSMSProvider(username="u", api_key="k"),
             "clients.messaging.providers.ebulksms.requests.post"),
        ):
            with patch(target, side_effect=requests.ConnectionError("down")):
                with pytest.raises(MessagingError) as exc:
                    provider.send(msg())
            assert exc.value.retryable is True
            assert exc.value.provider == provider.name

    def test_ebulksms_reports_body_level_failure_despite_http_200(self):
        p = EBulkSMSProvider(username="u", api_key="k")
        with patch("clients.messaging.providers.ebulksms.requests.post",
                   return_value=ok_response({"response": {"status": "INSUFFICIENT_BALANCE"}})):
            with pytest.raises(MessagingError) as exc:
                p.send(msg())
        assert exc.value.retryable is False  # topping up is a human action

    def test_termii_reports_body_level_failure_despite_http_200(self):
        p = TermiiProvider(api_key="k")
        with patch("clients.messaging.providers.termii.requests.post",
                   return_value=ok_response({"code": "invalid_sender", "message": "bad"})):
            with pytest.raises(MessagingError):
                p.send(msg())

    def test_no_vendor_exception_escapes(self):
        p = TermiiProvider(api_key="k")
        with patch("clients.messaging.providers.termii.requests.post",
                   side_effect=requests.Timeout("slow")):
            try:
                p.send(msg())
            except MessagingError:
                pass
            except requests.RequestException:
                pytest.fail("vendor exception leaked past the provider boundary")


# --------------------------------------------------------------------------
# Failover — the behaviour that was actually asked for
# --------------------------------------------------------------------------

class TestFailover:

    def test_switches_to_the_next_provider_on_failure(self):
        first = FailingProvider(name="first")
        second = MemoryProvider()
        chain = FailoverProvider([first, second])

        result = chain.send(msg())

        assert len(first.calls) == 1          # tried
        assert len(second.outbox) == 1        # delivered
        assert result.provider == "memory"
        assert result.attempts == ("first",)  # records who failed

    def test_walks_the_whole_chain(self):
        a, b = FailingProvider(name="a"), FailingProvider(name="b")
        third = MemoryProvider()
        result = FailoverProvider([a, b, third]).send(msg())
        assert result.attempts == ("a", "b")
        assert len(third.outbox) == 1

    def test_all_failing_raises_with_every_error(self):
        chain = FailoverProvider([
            FailingProvider(name="a", detail="a down"),
            FailingProvider(name="b", detail="b down"),
        ])
        with pytest.raises(AllProvidersFailed) as exc:
            chain.send(msg())
        assert set(exc.value.failures) == {"a", "b"}
        assert "a down" in str(exc.value) and "b down" in str(exc.value)

    def test_permanent_failure_stops_the_chain(self):
        """A bad number will fail on every vendor — do not burn all three."""
        first = FailingProvider(name="first", retryable=False, detail="invalid number")
        second = MemoryProvider()
        chain = FailoverProvider([first, second])

        with pytest.raises(MessagingError):
            chain.send(msg())

        assert len(second.outbox) == 0, "must not fail over on a permanent fault"

    def test_skips_providers_that_do_not_serve_the_channel(self):
        sms_only = MemoryProvider(channels=frozenset({Channel.SMS}))
        both = MemoryProvider()
        chain = FailoverProvider([sms_only, both])

        chain.send(msg(channel=Channel.WHATSAPP))

        assert len(sms_only.outbox) == 0, "unsupported channel must not be attempted"
        assert len(both.outbox) == 1

    def test_skips_unconfigured_providers(self):
        unconfigured = TwilioProvider(account_sid="", auth_token="")
        working = MemoryProvider()
        chain = FailoverProvider([unconfigured, working])

        chain.send(msg())

        assert len(working.outbox) == 1
        assert chain.candidates(Channel.SMS) == [working]

    def test_no_eligible_provider_raises_channel_not_supported(self):
        chain = FailoverProvider([MemoryProvider(channels=frozenset({Channel.SMS}))])
        with pytest.raises(ChannelNotSupported):
            chain.send(msg(channel=Channel.WHATSAPP))

    def test_chain_channels_are_the_union(self):
        chain = FailoverProvider([
            MemoryProvider(channels=frozenset({Channel.SMS})),
            MemoryProvider(channels=frozenset({Channel.WHATSAPP})),
        ])
        assert chain.channels == frozenset({Channel.SMS, Channel.WHATSAPP})

    def test_chain_is_itself_a_provider(self):
        """Composite: a chain substitutes anywhere a single provider does."""
        chain = FailoverProvider([MemoryProvider(), MemoryProvider()])
        assert isinstance(chain, MessagingProvider)
        nested = FailoverProvider([chain, MemoryProvider()])
        assert isinstance(nested.send(msg()), SendResult)

    def test_build_chain_unwraps_a_single_provider(self):
        only = MemoryProvider()
        assert build_chain([only]) is only
        assert isinstance(build_chain([only, MemoryProvider()]), FailoverProvider)

    def test_requires_at_least_one_provider(self):
        with pytest.raises(ValueError):
            FailoverProvider([])


# --------------------------------------------------------------------------
# Registry / configuration
# --------------------------------------------------------------------------

class TestRegistry:

    def test_builtins_registered(self):
        for name in ("twilio", "termii", "ebulksms", "console", "memory"):
            assert name in available_providers()

    def test_unknown_provider_is_a_clear_error(self):
        with pytest.raises(ValueError, match="Unknown messaging provider"):
            get_provider("carrier-pigeon")

    def test_chain_order_comes_from_settings(self, settings):
        settings.MESSAGING_PROVIDERS = "termii,twilio"
        assert configured_chain() == ("termii", "twilio")

    def test_per_channel_override(self, settings):
        settings.MESSAGING_PROVIDERS = "ebulksms,termii"
        # "" means "no override for this channel" -> inherit the default chain.
        settings.MESSAGING_PROVIDERS_SMS = ""
        settings.MESSAGING_PROVIDERS_WHATSAPP = "twilio,termii"
        assert configured_chain(Channel.SMS) == ("ebulksms", "termii")
        assert configured_chain(Channel.WHATSAPP) == ("twilio", "termii")

    def test_new_vendor_needs_no_existing_code_change(self):
        class KudiSMSProvider(MessagingProvider):
            name = "kudisms-test"
            channels = frozenset({Channel.SMS})

            def send(self, message: Message) -> SendResult:
                return SendResult(message_id="k1", provider=self.name,
                                  channel=message.channel)

        register_provider("kudisms-test", KudiSMSProvider, replace=True)
        provider = get_provider("kudisms-test")
        assert isinstance(provider, MessagingProvider)
        assert provider.send(msg()).message_id == "k1"

    def test_duplicate_registration_rejected(self):
        with pytest.raises(ValueError, match="already registered"):
            register_provider("twilio", MemoryProvider)


# --------------------------------------------------------------------------
# Service + notification senders
# --------------------------------------------------------------------------

class TestChannelPreference:
    """WhatsApp leads; SMS is the fallback; an explicit choice wins."""

    def test_no_preference_puts_whatsapp_first(self):
        assert resolve_channel_order(None) == (Channel.WHATSAPP, Channel.SMS)

    def test_explicit_choice_leads_but_still_falls_back(self):
        assert resolve_channel_order(Channel.SMS) == (Channel.SMS, Channel.WHATSAPP)
        assert resolve_channel_order("sms") == (Channel.SMS, Channel.WHATSAPP)
        assert resolve_channel_order("whatsapp") == (Channel.WHATSAPP, Channel.SMS)

    def test_unknown_choice_is_rejected(self):
        with pytest.raises(ValueError):
            resolve_channel_order("telegram")


class TestChannelFallback:

    def test_default_otp_goes_out_on_whatsapp(self):
        provider = MemoryProvider()
        MessagingService(provider=provider).send_otp(to="08012345678", code="483920")
        assert provider.outbox[0].channel is Channel.WHATSAPP

    def test_falls_back_to_sms_when_whatsapp_fails(self):
        """The headline behaviour: WhatsApp down -> SMS carries the OTP."""
        class WhatsAppDown(MemoryProvider):
            name = "partial"

            def send(self, message):
                if message.channel is Channel.WHATSAPP:
                    raise MessagingError(
                        "WhatsApp unavailable", provider=self.name,
                        channel=message.channel,
                    )
                return super().send(message)

        provider = WhatsAppDown()
        result = MessagingService(provider=provider).send_otp(
            to="08012345678", code="483920"
        )

        assert result.channel is Channel.SMS
        assert [m.channel for m in provider.outbox] == [Channel.SMS]
        assert "483920" in provider.outbox[0].body

    def test_falls_back_when_no_provider_serves_whatsapp(self):
        """Exactly the real deployment case: only an SMS-only vendor is live."""
        sms_only = MemoryProvider(channels=frozenset({Channel.SMS}))
        result = MessagingService(provider=sms_only).send_otp(
            to="08012345678", code="483920"
        )
        assert result.channel is Channel.SMS

    def test_permanent_whatsapp_error_still_falls_back_to_sms(self):
        """'Recipient is not on WhatsApp' is precisely when SMS should be used."""
        class NotOnWhatsApp(MemoryProvider):
            name = "partial"

            def send(self, message):
                if message.channel is Channel.WHATSAPP:
                    raise MessagingError(
                        "63003 recipient not on WhatsApp", provider=self.name,
                        channel=message.channel, retryable=False,
                    )
                return super().send(message)

        result = MessagingService(provider=NotOnWhatsApp()).send_otp(
            to="08012345678", code="483920"
        )
        assert result.channel is Channel.SMS

    def test_explicit_sms_choice_is_honoured_first(self):
        provider = MemoryProvider()
        result = MessagingService(provider=provider).send_otp(
            to="08012345678", code="483920", channel="sms"
        )
        assert result.channel is Channel.SMS

    def test_explicit_sms_still_falls_back_to_whatsapp(self):
        class SmsDown(MemoryProvider):
            name = "partial"

            def send(self, message):
                if message.channel is Channel.SMS:
                    raise MessagingError(
                        "SMS gateway down", provider=self.name, channel=message.channel
                    )
                return super().send(message)

        result = MessagingService(provider=SmsDown()).send_otp(
            to="08012345678", code="483920", channel="sms"
        )
        assert result.channel is Channel.WHATSAPP

    def test_fallback_can_be_disabled(self):
        service = MessagingService(provider=FailingProvider())
        with pytest.raises(MessagingError):
            service.send_otp(to="08012345678", code="1", fallback=False)

    def test_no_fallback_only_tries_the_preferred_channel(self):
        provider = MemoryProvider(channels=frozenset({Channel.SMS}))
        with pytest.raises(MessagingError):
            MessagingService(provider=provider).send_otp(
                to="08012345678", code="1", channel="whatsapp", fallback=False
            )
        assert provider.outbox == []

    def test_every_channel_failing_raises_with_both_errors(self):
        service = MessagingService(provider=FailingProvider(detail="vendor down"))
        with pytest.raises(AllChannelsFailed) as exc:
            service.send_otp(to="08012345678", code="483920")

        assert set(exc.value.failures) == {"whatsapp", "sms"}
        assert exc.value.channels == (Channel.WHATSAPP, Channel.SMS)
        assert exc.value.retryable is True  # Celery should retry the ladder

    def test_whatsapp_is_not_retried_after_it_succeeds(self):
        provider = MemoryProvider()
        MessagingService(provider=provider).send_otp(to="08012345678", code="1")
        assert len(provider.outbox) == 1, "must not also send over SMS"


class TestMessagingService:

    def test_normalises_before_dispatch(self):
        provider = MemoryProvider()
        MessagingService(provider=provider).send_sms(to="08012345678", body="hi")
        assert provider.outbox[0].to == "+2348012345678"

    def test_send_otp_formats_the_body(self):
        provider = MemoryProvider()
        MessagingService(provider=provider).send_otp(to="08012345678", code="483920")
        assert "483920" in provider.outbox[0].body

    def test_channel_helpers_route_correctly(self):
        provider = MemoryProvider()
        svc = MessagingService(provider=provider)
        svc.send_sms(to="08012345678", body="a")
        svc.send_whatsapp(to="08012345678", body="b")
        assert [m.channel for m in provider.outbox] == [Channel.SMS, Channel.WHATSAPP]

    def test_invalid_number_fails_before_any_provider_call(self):
        provider = MemoryProvider()
        with pytest.raises(InvalidPhoneNumber):
            MessagingService(provider=provider).send_sms(to="abc", body="hi")
        assert provider.outbox == []


@pytest.mark.django_db
class TestNotificationSenders:

    def test_sms_sender_uses_the_chain(self, sms_outbox):
        from accounts.services.interfaces import NotificationPayload
        from accounts.services.notifications import SMSNotificationSender

        SMSNotificationSender().send(
            NotificationPayload(to="08012345678", subject="Code",
                                body="483920 is your code")
        )
        assert len(sms_outbox.outbox) == 1
        assert sms_outbox.outbox[0].channel is Channel.SMS
        assert sms_outbox.outbox[0].to == "+2348012345678"

    def test_whatsapp_sender_uses_the_chain(self, sms_outbox):
        from accounts.services.interfaces import NotificationPayload
        from accounts.services.notifications import WhatsAppNotificationSender

        WhatsAppNotificationSender().send(
            NotificationPayload(to="08012345678", subject="Code",
                                body="483920 is your code")
        )
        assert sms_outbox.outbox[0].channel is Channel.WHATSAPP

    def test_failure_propagates_so_celery_retries(self):
        from accounts.services.interfaces import NotificationPayload
        from accounts.services.notifications import SMSNotificationSender

        sender = SMSNotificationSender(provider=FailingProvider())
        with pytest.raises(MessagingError):
            sender.send(
                NotificationPayload(to="08012345678", subject="s", body="b")
            )

    def test_otp_tasks_go_through_the_chain(self, sms_outbox):
        from accounts.tasks import send_otp_message, send_otp_sms

        send_otp_sms(to="08012345678", code="111111", purpose="registration")
        send_otp_message(to="08012345678", code="222222", purpose="registration")

        # send_otp_sms prefers SMS; send_otp_message defaults to WhatsApp.
        assert [m.channel for m in sms_outbox.outbox] == [
            Channel.SMS, Channel.WHATSAPP
        ]
        assert "111111" in sms_outbox.outbox[0].body
        assert "222222" in sms_outbox.outbox[1].body

    def test_otp_task_honours_an_explicit_channel(self, sms_outbox):
        from accounts.tasks import send_otp_message

        send_otp_message(
            to="08012345678", code="333333", purpose="registration", channel="sms"
        )
        assert sms_outbox.outbox[0].channel is Channel.SMS
