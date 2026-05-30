from __future__ import annotations

import uuid
from datetime import timedelta

from django.core.cache import cache

from .cache import make_key
from .interfaces import IDistributedLock, IRateLimiter


class RedisRateLimiter(IRateLimiter):
    def __init__(self, namespace: str = "rl") -> None:
        self._ns = namespace

    def _key(self, key: str) -> str:
        return make_key(self._ns, key)

    def _cooldown_key(self, key: str) -> str:
        return make_key(self._ns, "cooldown", key)

    def hit(self, key: str, *, limit: int, window: timedelta) -> tuple[bool, int]:
        full_key = self._key(key)
        try:
            value = cache.incr(full_key)
        except ValueError:
            value = 1
            cache.set(full_key, value, timeout=window.total_seconds())
        return (value <= limit, value)

    def reset(self, key: str) -> None:
        cache.delete(self._key(key))

    def cooldown(self, key: str, *, ttl: timedelta) -> bool:
        return cache.get(self._cooldown_key(key)) is not None

    def start_cooldown(self, key: str, *, ttl: timedelta) -> None:
        cache.set(self._cooldown_key(key), 1, timeout=ttl.total_seconds())

# SET NX EX-style lock. Holder identity is tracked so a process can

class RedisDistributedLock(IDistributedLock):

    def __init__(self, namespace: str = "lock") -> None:
        self._ns = namespace
        self._token = uuid.uuid4().hex

    def _key(self, key: str) -> str:
        return make_key(self._ns, key)

    def acquire(self, key: str, *, ttl: timedelta) -> bool:
        # Django's add() is SET NX — atomic acquisition.
        return cache.add(self._key(key), self._token, timeout=ttl.total_seconds())

    def release(self, key: str) -> None:
        full_key = self._key(key)
        if cache.get(full_key) == self._token:
            cache.delete(full_key)

