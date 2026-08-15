from __future__ import annotations

import logging
import os
from typing import Callable

from django.conf import settings

from clients.messaging.base import Channel, MessagingProvider
from clients.messaging.failover import build_chain

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[], MessagingProvider]

_REGISTRY: dict[str, ProviderFactory] = {}

DEFAULT_CHAIN = "twilio,termii,ebulksms"


def register_provider(
    name: str, factory: ProviderFactory, *, replace: bool = False
) -> None:
    key = name.strip().lower()
    if key in _REGISTRY and not replace:
        raise ValueError(
            f"Messaging provider {key!r} is already registered; pass replace=True."
        )
    _REGISTRY[key] = factory


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def get_provider(name: str) -> MessagingProvider:
    key = name.strip().lower()
    try:
        return _REGISTRY[key]()
    except KeyError:
        raise ValueError(
            f"Unknown messaging provider {key!r}. "
            f"Registered: {', '.join(available_providers())}"
        ) from None


def _setting(name: str) -> str | None:
    return getattr(settings, name, None) or os.getenv(name)


def configured_chain(channel: Channel | None = None) -> tuple[str, ...]:
    """Ordered provider names for `channel`.

    `MESSAGING_PROVIDERS` sets the default chain; `MESSAGING_PROVIDERS_SMS` and
    `MESSAGING_PROVIDERS_WHATSAPP` override it per channel.
    """
    raw = None
    if channel is not None:
        raw = _setting(f"MESSAGING_PROVIDERS_{channel.value.upper()}")
    raw = raw or _setting("MESSAGING_PROVIDERS") or DEFAULT_CHAIN
    return tuple(part.strip().lower() for part in str(raw).split(",") if part.strip())


def cooldown_seconds() -> int:
    value = _setting("MESSAGING_FAILOVER_COOLDOWN_SECONDS")
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def get_messaging_provider(channel: Channel | None = None) -> MessagingProvider:
    names = configured_chain(channel)
    providers: list[MessagingProvider] = []
    for name in names:
        try:
            providers.append(get_provider(name))
        except ValueError:
            logger.exception("Skipping unknown messaging provider %r in chain", name)
    if not providers:
        raise ValueError(
            f"No usable messaging providers in chain {names!r}. "
            f"Registered: {', '.join(available_providers())}"
        )
    return build_chain(providers, cooldown_seconds=cooldown_seconds())


def _register_builtins() -> None:
    def _twilio() -> MessagingProvider:
        from clients.messaging.providers.twilio import TwilioProvider

        return TwilioProvider()

    def _termii() -> MessagingProvider:
        from clients.messaging.providers.termii import TermiiProvider

        return TermiiProvider()

    def _ebulksms() -> MessagingProvider:
        from clients.messaging.providers.ebulksms import EBulkSMSProvider

        return EBulkSMSProvider()

    def _console() -> MessagingProvider:
        from clients.messaging.providers.local import ConsoleProvider

        return ConsoleProvider()

    def _memory() -> MessagingProvider:
        from clients.messaging.providers.local import MemoryProvider

        return MemoryProvider()

    for key, factory in (
        ("twilio", _twilio),
        ("termii", _termii),
        ("ebulksms", _ebulksms),
        ("console", _console),
        ("memory", _memory),
    ):
        _REGISTRY.setdefault(key, factory)


_register_builtins()
