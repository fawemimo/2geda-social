"""Provider-agnostic SMS and WhatsApp delivery with automatic failover.

    from clients.messaging import MessagingService, Channel

    MessagingService().send_sms(to="08012345678", body="hi")
    MessagingService().send_otp(to="08012345678", code="483920",
                                channel=Channel.WHATSAPP)

Which vendors run, and in what order, comes from configuration:

    MESSAGING_PROVIDERS=twilio,termii,ebulksms
    MESSAGING_PROVIDERS_WHATSAPP=twilio,termii     # optional per-channel order
    MESSAGING_FAILOVER_COOLDOWN_SECONDS=60         # optional

If the first provider fails with a retryable error the next is tried
immediately. Providers that do not serve the requested channel, or that have no
credentials, are skipped rather than attempted.

To add a vendor, subclass `MessagingProvider` and register a factory — no
existing module changes:

    from clients.messaging import MessagingProvider, Channel, register_provider

    class KudiSMSProvider(MessagingProvider):
        name = "kudisms"
        channels = frozenset({Channel.SMS})
        def send(self, message): ...

    register_provider("kudisms", KudiSMSProvider)
"""

from clients.messaging.base import (
    AllChannelsFailed,
    AllProvidersFailed,
    Channel,
    ChannelNotSupported,
    Message,
    MessagingError,
    MessagingProvider,
    SendResult,
)
from clients.messaging.failover import FailoverProvider, build_chain
from clients.messaging.phone import InvalidPhoneNumber, normalize
from clients.messaging.registry import (
    available_providers,
    configured_chain,
    get_messaging_provider,
    get_provider,
    register_provider,
)
from clients.messaging.service import (
    DEFAULT_OTP_CHANNEL_ORDER,
    MessagingService,
    resolve_channel_order,
)

__all__ = [
    "DEFAULT_OTP_CHANNEL_ORDER",
    "AllChannelsFailed",
    "AllProvidersFailed",
    "Channel",
    "ChannelNotSupported",
    "FailoverProvider",
    "InvalidPhoneNumber",
    "Message",
    "MessagingError",
    "MessagingProvider",
    "MessagingService",
    "SendResult",
    "available_providers",
    "build_chain",
    "configured_chain",
    "get_messaging_provider",
    "get_provider",
    "normalize",
    "register_provider",
    "resolve_channel_order",
]
