from __future__ import annotations
import hashlib
import json
import logging

logger = logging.getLogger(__name__)
PREFIX = "accounts:phone_catalog"
TTL_SECONDS = 60


def _redis():
    try:
        from django_redis import get_redis_connection

        return get_redis_connection("default")
    except Exception as exc:
        logger.warning("Phone catalog Redis connection unavailable: %s", exc)
        return None


def _key(user_id, query_params) -> str:
    redis = _redis()
    version_key = f"{PREFIX}:version:{user_id}"
    version = 1
    if redis is not None:
        try:
            raw_version = redis.get(version_key)
            if raw_version is None:
                redis.set(version_key, 1, nx=True)
            else:
                version = int(raw_version)
                # Re-read in case another request initialized the version.
                if version == 1:
                    version = int(redis.get(version_key) or 1)
        except Exception as exc:
            logger.warning("Phone catalog cache version read failed: %s", exc)
    params = sorted((key, value) for key in query_params for value in query_params.getlist(key))
    digest = hashlib.sha256(json.dumps(params, separators=(",", ":")).encode()).hexdigest()
    return f"{PREFIX}:list:{user_id}:v{version}:{digest}"


def get_list(user_id, query_params):
    redis = _redis()
    if redis is None:
        return None
    try:
        raw = redis.get(_key(user_id, query_params))
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        logger.warning("Phone catalog Redis read failed: %s", exc)
        return None


def set_list(user_id, query_params, value) -> None:
    redis = _redis()
    if redis is None:
        return
    try:
        redis.setex(_key(user_id, query_params), TTL_SECONDS, json.dumps(value, default=str))
    except Exception as exc:
        logger.warning("Phone catalog Redis write failed: %s", exc)


def invalidate_list(user_id) -> None:
    redis = _redis()
    if redis is None:
        return
    try:
        redis.incr(f"{PREFIX}:version:{user_id}")
    except Exception as exc:
        logger.warning("Phone catalog Redis invalidation failed: %s", exc)
