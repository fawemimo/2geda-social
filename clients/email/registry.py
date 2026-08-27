from __future__ import annotations

import logging
import os
from typing import Callable

from django.conf import settings

from clients.email.base import EmailProvider

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[], EmailProvider]

_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory, *, replace: bool = False) -> None:
    key = name.strip().lower()
    if key in _REGISTRY and not replace:
        raise ValueError(
            f"Email provider {key!r} is already registered; pass replace=True to override."
        )
    _REGISTRY[key] = factory


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def configured_provider_name() -> str:
    from config import get_config

    return str(get_config("EMAIL_PROVIDER") or "resend").strip().lower()


def get_provider(name: str | None = None) -> EmailProvider:
    key = (name or configured_provider_name()).strip().lower()
    try:
        factory = _REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"Unknown email provider {key!r}. Registered: {', '.join(available_providers())}"
        ) from None
    return factory()


def _register_builtins() -> None:
    
    def _resend() -> EmailProvider:
        from clients.email.providers.resend import ResendProvider

        return ResendProvider()

    def _ses() -> EmailProvider:
        from clients.email.providers.ses import SESProvider

        return SESProvider()

    def _console() -> EmailProvider:
        from clients.email.providers.local import ConsoleProvider

        return ConsoleProvider()

    def _memory() -> EmailProvider:
        from clients.email.providers.local import MemoryProvider

        return MemoryProvider()

    for key, factory in (
        ("resend", _resend),
        ("ses", _ses),
        ("console", _console),
        ("memory", _memory),
    ):
        _REGISTRY.setdefault(key, factory)


_register_builtins()
