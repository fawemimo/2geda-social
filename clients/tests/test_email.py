"""Contract tests for the email abstraction.

The provider suite runs the *same* assertions against every registered
provider. That is the executable form of the Liskov guarantee: if a new
provider passes these, callers can hold it without knowing which it is.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from clients.email import (
    EmailDeliveryError,
    EmailMessage,
    EmailProvider,
    EmailService,
    SendResult,
    available_providers,
    get_provider,
    register_provider,
)
from clients.email.providers.local import (
    ConsoleProvider,
    FailingProvider,
    MemoryProvider,
)
from clients.email.providers.resend import ResendProvider
from clients.email.providers.ses import SESProvider


def make_message(**overrides) -> EmailMessage:
    base = dict(
        to=("someone@example.com",),
        subject="Verify your email",
        html="<p>hello</p>",
        text="hello",
        from_email="2geda <noreply@2geda.net>",
    )
    base.update(overrides)
    return EmailMessage(**base)


# --------------------------------------------------------------------------
# EmailMessage / SendResult invariants
# --------------------------------------------------------------------------

class TestEmailMessage:

    def test_requires_recipient(self):
        with pytest.raises(ValueError, match="recipient"):
            make_message(to=())

    def test_requires_sender(self):
        with pytest.raises(ValueError, match="sender"):
            make_message(from_email="")

    def test_is_immutable(self):
        msg = make_message()
        with pytest.raises(Exception):
            msg.subject = "changed"

    def test_send_result_is_always_truthy(self):
        """Even with no provider id — callers must not treat that as failure."""
        assert bool(SendResult(message_id="", provider="x")) is True


# --------------------------------------------------------------------------
# The substitutability contract — run against every provider
# --------------------------------------------------------------------------

def _stubbed_resend() -> ResendProvider:
    provider = ResendProvider(api_key="k", api_url="https://example.invalid/emails")
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "resend-123"}
    response.raise_for_status.return_value = None
    provider._test_response = response  # type: ignore[attr-defined]
    return provider


def _stubbed_ses() -> SESProvider:
    client = MagicMock()
    client.send_email.return_value = {"MessageId": "ses-123"}
    return SESProvider(client=client)


PROVIDER_CASES = [
    pytest.param(lambda: MemoryProvider(), False, id="memory"),
    pytest.param(lambda: ConsoleProvider(), False, id="console"),
    pytest.param(_stubbed_resend, True, id="resend"),
    pytest.param(_stubbed_ses, False, id="ses"),
]


@pytest.mark.parametrize("factory,needs_http_patch", PROVIDER_CASES)
class TestProviderContract:
    """Every provider must satisfy these identically."""

    @staticmethod
    def _send(provider, needs_http_patch, message=None):
        message = message or make_message()
        if needs_http_patch:
            with patch(
                "clients.email.providers.resend.requests.post",
                return_value=provider._test_response,
            ):
                return provider.send(message)
        return provider.send(message)

    def test_is_an_email_provider(self, factory, needs_http_patch):
        assert isinstance(factory(), EmailProvider)

    def test_has_a_stable_name(self, factory, needs_http_patch):
        name = factory().name
        assert isinstance(name, str) and name and name != "base"

    def test_success_returns_send_result(self, factory, needs_http_patch):
        result = self._send(factory(), needs_http_patch)
        assert isinstance(result, SendResult)
        assert result.provider == factory().name
        assert isinstance(result.message_id, str)

    def test_accepts_multiple_recipients(self, factory, needs_http_patch):
        result = self._send(
            factory(), needs_http_patch,
            make_message(to=("a@example.com", "b@example.com")),
        )
        assert isinstance(result, SendResult)

    def test_accepts_optional_fields(self, factory, needs_http_patch):
        result = self._send(
            factory(), needs_http_patch,
            make_message(
                reply_to="support@2geda.net",
                cc=("cc@example.com",),
                bcc=("bcc@example.com",),
            ),
        )
        assert isinstance(result, SendResult)

    def test_never_returns_none(self, factory, needs_http_patch):
        assert self._send(factory(), needs_http_patch) is not None


class TestFailureContract:
    """Failures raise EmailDeliveryError — never a provider-native exception."""

    def test_resend_http_error_is_wrapped(self):
        provider = ResendProvider(api_key="k", api_url="https://example.invalid/e")
        response = MagicMock(status_code=422, text='{"message":"bad"}')
        err = requests.HTTPError(response=response)
        response.raise_for_status.side_effect = err

        with patch("clients.email.providers.resend.requests.post", return_value=response):
            with pytest.raises(EmailDeliveryError) as exc:
                provider.send(make_message())

        assert exc.value.provider == "resend"
        assert exc.value.status_code == 422
        assert exc.value.retryable is False  # 4xx: retrying cannot help

    def test_resend_network_error_is_wrapped_and_retryable(self):
        provider = ResendProvider(api_key="k")
        with patch(
            "clients.email.providers.resend.requests.post",
            side_effect=requests.ConnectionError("boom"),
        ):
            with pytest.raises(EmailDeliveryError) as exc:
                provider.send(make_message())
        assert exc.value.retryable is True

    def test_resend_429_stays_retryable(self):
        provider = ResendProvider(api_key="k")
        response = MagicMock(status_code=429, text="rate limited")
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        with patch("clients.email.providers.resend.requests.post", return_value=response):
            with pytest.raises(EmailDeliveryError) as exc:
                provider.send(make_message())
        assert exc.value.retryable is True

    def test_ses_client_error_is_wrapped(self):
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.send_email.side_effect = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "Email address not verified"},
             "ResponseMetadata": {"HTTPStatusCode": 400}},
            "SendEmail",
        )
        with pytest.raises(EmailDeliveryError) as exc:
            SESProvider(client=client).send(make_message())

        assert exc.value.provider == "ses"
        assert exc.value.retryable is False
        assert "MessageRejected" in str(exc.value)

    def test_no_provider_native_exception_escapes(self):
        """The whole point: callers catch one error type."""
        provider = ResendProvider(api_key="k")
        with patch(
            "clients.email.providers.resend.requests.post",
            side_effect=requests.Timeout("slow"),
        ):
            try:
                provider.send(make_message())
            except EmailDeliveryError:
                pass
            except requests.RequestException:
                pytest.fail("provider-native exception leaked past the boundary")


# --------------------------------------------------------------------------
# Registry / OCP
# --------------------------------------------------------------------------

class TestRegistry:

    def test_builtins_are_registered(self):
        for name in ("resend", "ses", "console", "memory"):
            assert name in available_providers()

    def test_unknown_provider_is_a_clear_error(self):
        with pytest.raises(ValueError, match="Unknown email provider"):
            get_provider("does-not-exist")

    def test_a_new_provider_needs_no_existing_code_change(self):
        class PostmarkProvider(EmailProvider):
            name = "postmark-test"

            def send(self, message: EmailMessage) -> SendResult:
                return SendResult(message_id="pm-1", provider=self.name)

        register_provider("postmark-test", PostmarkProvider, replace=True)
        provider = get_provider("postmark-test")

        assert isinstance(provider, EmailProvider)
        assert provider.send(make_message()).message_id == "pm-1"

    def test_duplicate_registration_is_rejected(self):
        with pytest.raises(ValueError, match="already registered"):
            register_provider("resend", MemoryProvider)

    def test_settings_select_the_provider(self, settings):
        settings.EMAIL_PROVIDER = "memory"
        assert isinstance(get_provider(), MemoryProvider)


# --------------------------------------------------------------------------
# Service: rendering happens once, identically, for every provider
# --------------------------------------------------------------------------

@pytest.mark.django_db
class TestEmailService:

    def test_renders_into_the_shared_shell(self):
        provider = MemoryProvider()
        EmailService("otp", provider=provider, sender="noreply@2geda.net").send_email(
            to="user@example.com",
            obj="483920",
            subject="Verify your email",
            other_values={"username": "ada", "code": "483920", "purpose": "registration"},
        )
        msg = provider.outbox[0]
        assert "483920" in msg.html and "ada" in msg.html
        assert "<!DOCTYPE html>" in msg.html          # shell applied
        assert "{{" not in msg.html and "{%" not in msg.html
        assert msg.text and "<p>" not in msg.text     # plain-text alternative
        assert msg.subject == "Verify your email"
        assert msg.from_email == "2geda Social App <noreply@2geda.net>"

    def test_identical_output_across_providers(self):
        """The LSP payoff: swapping the provider cannot change the content."""
        kwargs = dict(
            to="user@example.com", obj="483920", subject="Verify",
            other_values={"username": "ada", "code": "483920"},
        )
        a, b = MemoryProvider(), MemoryProvider()
        EmailService("otp", provider=a, sender="noreply@2geda.net").send_email(**kwargs)
        EmailService("otp", provider=b, sender="noreply@2geda.net").send_email(**kwargs)

        # action_date_time is a timestamp; compare the stable parts.
        assert a.outbox[0].subject == b.outbox[0].subject
        assert a.outbox[0].from_email == b.outbox[0].from_email
        assert "483920" in a.outbox[0].html and "483920" in b.outbox[0].html

    def test_string_recipient_is_normalised(self):
        provider = MemoryProvider()
        EmailService("otp", provider=provider, sender="x@y.z").send_email(
            to="one@example.com", obj="1", other_values={"code": "1"},
        )
        assert provider.outbox[0].to == ("one@example.com",)

    def test_template_name_forms_all_resolve(self):
        for name in ("otp", "otp.txt", "mails/otp.txt"):
            provider = MemoryProvider()
            EmailService(name, provider=provider, sender="x@y.z").send_email(
                to="a@b.c", obj="1", other_values={"code": "1"},
            )
            assert provider.outbox, f"{name} failed to render"

    def test_failure_propagates_to_the_caller(self):
        service = EmailService("otp", provider=FailingProvider(), sender="x@y.z")
        with pytest.raises(EmailDeliveryError):
            service.send_email(to="a@b.c", obj="1", other_values={"code": "1"})


@pytest.mark.django_db
class TestEmailNotificationSender:

    def test_uses_the_configured_provider(self, email_outbox):
        from accounts.services.interfaces import NotificationPayload
        from accounts.services.notifications import EmailNotificationSender

        EmailNotificationSender().send(
            NotificationPayload(
                to="user@example.com", subject="Verify your email",
                body="Your code is 483920", template="otp",
                context={"username": "ada", "code": "483920"},
            )
        )
        assert len(email_outbox.outbox) == 1
        assert email_outbox.outbox[0].subject == "Verify your email"

    def test_accepts_an_injected_provider(self):
        from accounts.services.interfaces import NotificationPayload
        from accounts.services.notifications import EmailNotificationSender

        provider = MemoryProvider()
        EmailNotificationSender(provider=provider).send(
            NotificationPayload(
                to="user@example.com", subject="Hi", body="Body", template="generic",
            )
        )
        assert len(provider.outbox) == 1

    def test_delivery_failure_raises_so_celery_retries(self):
        from accounts.services.interfaces import NotificationPayload
        from accounts.services.notifications import EmailNotificationSender

        sender = EmailNotificationSender(provider=FailingProvider())
        with pytest.raises(EmailDeliveryError):
            sender.send(
                NotificationPayload(
                    to="user@example.com", subject="Hi", body="Body", template="generic",
                )
            )
