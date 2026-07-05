from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)

CACHE_POST_DETAIL_PREFIX = "social:post_detail"
CACHE_POST_LIST_PREFIX = "social:post_list"
CACHE_POST_TRENDING_PREFIX = "social:post_trending"
CACHE_POST_VERSION_KEY = "social:post_list_cache_version"

CACHE_POST_DETAIL_TTL = 300
CACHE_POST_LIST_TTL = 120
CACHE_POST_TRENDING_TTL = 60


def _redis():
    try:
        from django_redis import get_redis_connection
        return get_redis_connection("default")
    except Exception:
        return None


def _get_post_list_version() -> int:
    r = _redis()
    if r is None:
        return 1
    try:
        version = r.get(CACHE_POST_VERSION_KEY)
        if version is None:
            version = 1
            r.set(CACHE_POST_VERSION_KEY, version)
        else:
            version = int(version)
    except Exception as exc:
        logger.warning("Redis get version failed: %s", exc)
        return 1
    return version


def make_post_detail_cache_key(post_id: str) -> str:
    return f"{CACHE_POST_DETAIL_PREFIX}:{post_id}"


def make_post_list_cache_key(page: int, page_size: int, user_id: str, query_params: dict) -> str:
    canonical = json.dumps(query_params, sort_keys=True, separators=(",", ":"))
    h = hashlib.md5(canonical.encode()).hexdigest()
    return f"{CACHE_POST_LIST_PREFIX}:v{_get_post_list_version()}:p{page}:s{page_size}:{h}:u{user_id}"


def make_post_trending_cache_key(user_id: str) -> str:
    return f"{CACHE_POST_TRENDING_PREFIX}:v{_get_post_list_version()}:u{user_id}"


def bump_post_list_version() -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.incr(CACHE_POST_VERSION_KEY)
    except Exception as exc:
        logger.warning("Redis bump version failed: %s", exc)


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
