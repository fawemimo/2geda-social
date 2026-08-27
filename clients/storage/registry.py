from __future__ import annotations

import logging
import os
from typing import Callable

from django.conf import settings

from clients.storage.base import StorageProvider

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[], StorageProvider]

_REGISTRY: dict[str, ProviderFactory] = {}

#: Legacy values of the older STORAGE_TYPE setting.
_ALIASES = {"aws": "s3", "amazon": "s3", "azure_blob": "azure", "blob": "azure"}


def register_provider(
    name: str, factory: ProviderFactory, *, replace: bool = False
) -> None:
    key = name.strip().lower()
    if key in _REGISTRY and not replace:
        raise ValueError(
            f"Storage provider {key!r} is already registered; pass replace=True."
        )
    _REGISTRY[key] = factory


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def configured_provider_name() -> str:
    from config import get_config

    raw = (
        get_config("STORAGE_PROVIDER")
        or getattr(settings, "STORAGE_TYPE", None)
        or os.getenv("STORAGE_TYPE")
        or "s3"
    )
    key = str(raw).strip().lower()
    return _ALIASES.get(key, key)


def get_provider(name: str | None = None) -> StorageProvider:
    key = (name or configured_provider_name()).strip().lower()
    key = _ALIASES.get(key, key)
    try:
        factory = _REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"Unknown storage provider {key!r}. "
            f"Registered: {', '.join(available_providers())}"
        ) from None
    return factory()


def _register_builtins() -> None:
    def _s3() -> StorageProvider:
        from clients.storage.providers.s3 import S3Provider

        return S3Provider()

    def _azure() -> StorageProvider:
        from clients.storage.providers.azure import AzureBlobProvider

        return AzureBlobProvider()

    def _memory() -> StorageProvider:
        from clients.storage.providers.local import MemoryProvider

        return MemoryProvider()

    for key, factory in (("s3", _s3), ("azure", _azure), ("memory", _memory)):
        _REGISTRY.setdefault(key, factory)


_register_builtins()
