from __future__ import annotations

import logging
import os
from typing import Callable

from django.conf import settings

from clients.payments.base import PaymentProvider

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[], PaymentProvider]

_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(
    name: str, factory: ProviderFactory, *, replace: bool = False
) -> None:
    key = name.strip().lower()
    if key in _REGISTRY and not replace:
        raise ValueError(
            f"Payment provider {key!r} is already registered; pass replace=True."
        )
    _REGISTRY[key] = factory


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def configured_provider_name() -> str:
    from config import get_config

    return str(get_config("PAYMENT_PROVIDER") or "paystack").strip().lower()


def get_provider(name: str | None = None) -> PaymentProvider:
    key = (name or configured_provider_name()).strip().lower()
    try:
        factory = _REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"Unknown payment provider {key!r}. "
            f"Registered: {', '.join(available_providers())}"
        ) from None
    return factory()


def _register_builtins() -> None:
    def _paystack() -> PaymentProvider:
        from clients.payments.providers.paystack import PaystackProvider

        return PaystackProvider()

    def _flutterwave() -> PaymentProvider:
        from clients.payments.providers.flutterwave import FlutterwaveProvider

        return FlutterwaveProvider()

    def _memory() -> PaymentProvider:
        from clients.payments.providers.local import MemoryProvider

        return MemoryProvider()

    for key, factory in (
        ("paystack", _paystack),
        ("flutterwave", _flutterwave),
        ("memory", _memory),
    ):
        _REGISTRY.setdefault(key, factory)


_register_builtins()
