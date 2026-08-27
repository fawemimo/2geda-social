from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from config.registry import REGISTRY, spec_for

logger = logging.getLogger(__name__)

CACHE_KEY = "config:settings:v1"
CACHE_TTL = 300  # seconds

_UNAVAILABLE_BACKOFF = 30.0
_unavailable_until = 0.0
_lock = threading.Lock()
_MISSING_SENTINEL = object()


def _db_values() -> dict[str, str]:
    if time.monotonic() < _unavailable_until:
        return {}

    try:
        from django.core.cache import cache
    except Exception:  # pragma: no cover - Django not configured yet
        return {}

    try:
        cached = cache.get(CACHE_KEY)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    try:
        from config.models import Setting

        values = {
            key: value
            for key, value in Setting.objects.filter(is_active=True).values_list(
                "key", "value"
            )
            if str(value).strip()
        }
    except Exception as exc:
        _mark_unavailable()
        logger.warning(
            "config: settings table unavailable (%s); falling back to environment.",
            exc.__class__.__name__,
        )
        return {}

    try:
        cache.set(CACHE_KEY, values, CACHE_TTL)
    except Exception:
        pass
    return values


def _mark_unavailable() -> None:
    global _unavailable_until
    with _lock:
        _unavailable_until = time.monotonic() + _UNAVAILABLE_BACKOFF


def _django_setting(key: str) -> Any:
    try:
        from django.conf import settings as django_settings

        if not django_settings.configured:
            return None
        return getattr(django_settings, key, None)
    except Exception:
        return None


def invalidate_cache() -> None:
    global _unavailable_until
    with _lock:
        _unavailable_until = 0.0
    try:
        from django.core.cache import cache

        cache.delete(CACHE_KEY)
    except Exception:
        pass


def get_config(key: str, default: Any = _MISSING_SENTINEL, *, cast: bool = True) -> Any:
    key = key.strip().upper()
    spec = spec_for(key)

    raw: Any = None

    if spec is None or not spec.env_only:
        try:
            db_value = _db_values().get(key)
        except Exception:
            _mark_unavailable()
            db_value = None
        if db_value is not None and str(db_value).strip():
            raw = db_value

    if raw is None:
        setting_value = _django_setting(key)
        if setting_value is not None:
            if not str(setting_value).strip():
                return default if default is not _MISSING_SENTINEL else setting_value
            raw = setting_value

    # 3. Environment.
    if raw is None:
        env_value = os.getenv(key)
        if env_value is not None and str(env_value).strip():
            raw = env_value

    if raw is None or not str(raw).strip():
        if default is not _MISSING_SENTINEL:
            return default
        return spec.default if spec else ""

    if not cast or spec is None:
        return raw

    from config.models import Setting

    try:
        return Setting.cast(raw, spec.value_type)
    except Exception:
        logger.warning(
            "config: %s=%r is not a valid %s; using the default.",
            key, raw, spec.value_type,
        )
        if default is not _MISSING_SENTINEL:
            return default
        return spec.default


def get_int(key: str, default: int | None = None) -> int:
    value = get_config(key, default if default is not None else _MISSING_SENTINEL)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default if default is not None else 0


def get_bool(key: str, default: bool = False) -> bool:
    value = get_config(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_str(key: str, default: str = "") -> str:
    value = get_config(key, default)
    return "" if value is None else str(value)


def all_effective() -> dict[str, dict[str, Any]]:
    overrides = _db_values()
    report: dict[str, dict[str, Any]] = {}
    for key, spec in REGISTRY.items():
        if not spec.env_only and key in overrides:
            source = "database"
            raw = overrides[key]
        elif os.getenv(key) not in (None, ""):
            source = "environment"
            raw = os.getenv(key)
        else:
            source = "default"
            raw = spec.default
        report[key] = {
            "value": "********" if spec.env_only and raw else raw,
            "source": source,
            "category": spec.category,
            "env_only": spec.env_only,
        }
    return report
