from __future__ import annotations

import hashlib
import json

from django.core.cache import cache

CACHE_LIST_PREFIX = "user_list"
CACHE_DETAIL_PREFIX = "user_detail"
CACHE_VERSION_KEY = "user_list_cache_version"
CACHE_LIST_TTL = 3600
CACHE_DETAIL_TTL = 3600


def _get_list_version() -> int:
    version = cache.get(CACHE_VERSION_KEY)
    if version is None:
        version = 1
        cache.set(CACHE_VERSION_KEY, version, timeout=None)
    return version


def make_user_list_cache_key(query_params: dict) -> str:
    canonical = json.dumps(query_params, sort_keys=True, separators=(",", ":"))
    h = hashlib.md5(canonical.encode()).hexdigest()
    return f"{CACHE_LIST_PREFIX}:v{_get_list_version()}:{h}"


def make_user_detail_cache_key(user_id: str) -> str:
    return f"{CACHE_DETAIL_PREFIX}:{user_id}"


def bump_list_version() -> None:
    try:
        cache.incr(CACHE_VERSION_KEY)
    except ValueError:
        cache.set(CACHE_VERSION_KEY, 2, timeout=None)
