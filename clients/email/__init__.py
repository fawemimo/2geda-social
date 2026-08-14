from clients.email.base import (
    EmailDeliveryError,
    EmailMessage,
    EmailProvider,
    SendResult,
)
from clients.email.registry import (
    available_providers,
    configured_provider_name,
    get_provider,
    register_provider,
)
from clients.email.rendering import EmailRenderer, RenderedBody
from clients.email.service import EmailService

__all__ = [
    "EmailDeliveryError",
    "EmailMessage",
    "EmailProvider",
    "EmailRenderer",
    "EmailService",
    "RenderedBody",
    "SendResult",
    "available_providers",
    "configured_provider_name",
    "get_provider",
    "register_provider",
]
