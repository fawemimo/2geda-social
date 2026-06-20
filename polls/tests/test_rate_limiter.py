from __future__ import annotations

from datetime import timedelta

import pytest

from polls.services.rate_limiter import WebSocketRateLimiter


class TestWebSocketRateLimiter:
    def test_hit_within_limit(self):
        limiter = WebSocketRateLimiter(namespace="test")
        key = "user:1:poll:abc"
        allowed, count = limiter.hit(key, limit=5, window=timedelta(minutes=1))
        assert allowed is True
        assert count == 1

        allowed, count = limiter.hit(key, limit=5, window=timedelta(minutes=1))
        assert allowed is True
        assert count == 2

    def test_hit_exceeds_limit(self):
        limiter = WebSocketRateLimiter(namespace="test")
        key = "user:2:poll:xyz"
        for _ in range(3):
            limiter.hit(key, limit=3, window=timedelta(minutes=1))

        allowed, count = limiter.hit(key, limit=3, window=timedelta(minutes=1))
        assert allowed is False
        assert count == 4

    def test_reset_clears_counter(self):
        limiter = WebSocketRateLimiter(namespace="test")
        key = "user:3:poll:reset"
        limiter.hit(key, limit=1, window=timedelta(minutes=1))
        limiter.reset(key)

        allowed, count = limiter.hit(key, limit=1, window=timedelta(minutes=1))
        assert allowed is True
        assert count == 1

    def test_different_keys_are_independent(self):
        limiter = WebSocketRateLimiter(namespace="test")
        limiter.hit("key-a", limit=1, window=timedelta(minutes=1))

        allowed, _ = limiter.hit("key-b", limit=1, window=timedelta(minutes=1))
        assert allowed is True
