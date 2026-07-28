from __future__ import annotations

import hashlib
import json
import logging
import threading

logger = logging.getLogger(__name__)

CACHE_POST_DETAIL_PREFIX = "social:post_detail"
CACHE_POST_FEED_PREFIX = "social:post_feed"
CACHE_POST_TRENDING_PREFIX = "social:post_trending"

CACHE_POST_DETAIL_TTL = 300
CACHE_POST_FEED_TTL = 120
CACHE_POST_TRENDING_TTL = 60

_thread_local = threading.local()


def _redis():
    try:
        if getattr(_thread_local, "redis", None) is None:
            from django_redis import get_redis_connection
            _thread_local.redis = get_redis_connection("default")
        return _thread_local.redis
    except Exception:
        return None


def make_post_detail_cache_key(post_id: str) -> str:
    return f"{CACHE_POST_DETAIL_PREFIX}:{post_id}"


def make_post_feed_cache_key(cursor: str, page_size: int, user_id: str) -> str:
    raw = f"{cursor}:{page_size}:{user_id}"
    h = hashlib.md5(raw.encode()).hexdigest()
    return f"{CACHE_POST_FEED_PREFIX}:{h}"


def make_post_trending_cache_key(user_id: str) -> str:
    return f"{CACHE_POST_TRENDING_PREFIX}:{user_id}"


def delete_post_cache(post_id: str) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.delete(make_post_detail_cache_key(post_id))
    except Exception as exc:
        logger.warning("Redis delete post cache failed: %s", exc)


def get_cached(key: str):
    r = _redis()
    if r is None:
        return None
    try:
        data = r.get(key)
        if data is not None:
            return json.loads(data)
    except Exception as exc:
        logger.warning("Redis get failed: %s", exc)
    return None


def set_cached(key: str, value, ttl: int | None = None) -> None:
    r = _redis()
    if r is None:
        return
    try:
        serialized = json.dumps(value, default=str)
        if ttl is not None:
            r.setex(key, ttl, serialized)
        else:
            r.set(key, serialized)
    except Exception as exc:
        logger.warning("Redis set failed: %s", exc)
