from __future__ import annotations

import hashlib
from datetime import timedelta

from django.core.cache import cache


CACHE_VERSION = "v1"

# Compose a stable, collision-resistant cache key.

def make_key(*parts: str) -> str:
    raw = ":".join(p for p in parts if p)
    return f"{CACHE_VERSION}:accounts:{raw}"

# For keys that may contain PII (emails, phone) — store only the hash.

def hashed_key(*parts: str) -> str:
    raw = ":".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def get(key: str, default=None):
    return cache.get(key, default)


def set(key: str, value, ttl: timedelta | int | None = None):
    timeout = ttl.total_seconds() if isinstance(ttl, timedelta) else ttl
    cache.set(key, value, timeout=timeout)


def delete(key: str):
    cache.delete(key)

# Atomic increment with first-write TTL setup.

def incr(key: str, *, ttl: timedelta | None = None) -> int:
    try:
        value = cache.incr(key)
    except ValueError:
        # Key did not exist yet — initialise atomically.
        value = 1
        timeout = ttl.total_seconds() if ttl else None
        cache.set(key, value, timeout=timeout)
    return value

