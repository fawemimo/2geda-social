from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache


class WebSocketRateLimiter:
    def __init__(self, namespace: str = "polls_ws") -> None:
        self._ns = namespace

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    def hit(self, key: str, *, limit: int, window: timedelta) -> tuple[bool, int]:
        full_key = self._key(key)
        try:
            value = cache.incr(full_key)
        except ValueError:
            value = 1
            cache.set(full_key, value, timeout=int(window.total_seconds()))
        return (value <= limit, value)

    def reset(self, key: str) -> None:
        cache.delete(self._key(key))
