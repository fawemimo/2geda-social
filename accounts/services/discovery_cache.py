from __future__ import annotations

import hashlib
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class DiscoveryCache:
    """
    Redis-backed cache for the ConnectDiscovery endpoint.

    Uses:
      - Geoset      ``discover:locations``  → ``GEOADD`` / ``GEORADIUS``
      - Hash        ``discover:meta:{uid}`` → lat, lon, city, state, country,
                                               username, display_name, avatar
      - Set         ``discover:conn:{uid}`` → connected/pending user ids
      - String      ``discover:result:{hash}`` → serialised JSON (TTL 60 s)
    """

    _GEO_KEY = "discover:locations"
    _META_PFX = "discover:meta:"
    _CONN_PFX = "discover:conn:"
    _RESULT_PFX = "discover:result:"
    _RESULT_TTL = 60  # seconds

    @staticmethod
    def _redis():
        try:
            from django_redis import get_redis_connection
            return get_redis_connection("default")
        except Exception:
            return None

    # ── location helpers ─────────────────────────────────────────

    @classmethod
    def set_location(cls, user_id: str, lat: float, lon: float) -> None:
        r = cls._redis()
        if r is None:
            return
        try:
            r.geoadd(cls._GEO_KEY, [lon, lat, user_id])
        except Exception as exc:
            logger.warning("Redis GEOADD failed: %s", exc)

    @classmethod
    def remove_location(cls, user_id: str) -> None:
        r = cls._redis()
        if r is None:
            return
        try:
            r.zrem(cls._GEO_KEY, user_id)
            r.delete(f"{cls._META_PFX}{user_id}")
        except Exception as exc:
            logger.warning("Redis location removal failed: %s", exc)

    # ── metadata hash helpers ────────────────────────────────────

    @classmethod
    def set_metadata(cls, user_id: str, **fields) -> None:
        r = cls._redis()
        if r is None:
            return
        try:
            r.hset(f"{cls._META_PFX}{user_id}", mapping=fields)
        except Exception as exc:
            logger.warning("Redis HSET failed: %s", exc)

    @classmethod
    def get_metadata(cls, user_id: str) -> dict | None:
        r = cls._redis()
        if r is None:
            return None
        try:
            data = r.hgetall(f"{cls._META_PFX}{user_id}")
            if data:
                return {k.decode(): v.decode() if isinstance(v, bytes) else v for k, v in data.items()}
        except Exception as exc:
            logger.warning("Redis HGETALL failed: %s", exc)
        return None

    @classmethod
    def delete_metadata(cls, user_id: str) -> None:
        r = cls._redis()
        if r is None:
            return
        try:
            r.delete(f"{cls._META_PFX}{user_id}")
        except Exception as exc:
            logger.warning("Redis meta delete failed: %s", exc)

    @classmethod
    def geo_has_data(cls) -> bool:
        """Check if the geoset has any members at all."""
        r = cls._redis()
        if r is None:
            return False
        try:
            return r.zcard(cls._GEO_KEY) > 0
        except Exception as exc:
            logger.warning("Redis ZCARD failed: %s", exc)
            return False

    # ── georadius query ──────────────────────────────────────────

    @classmethod
    def nearby_user_ids(
        cls,
        lat: float,
        lon: float,
        radius_km: float,
        exclude: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """
        Returns ``[(user_id, distance_km), …]`` sorted nearest first.
        """
        r = cls._redis()
        if r is None:
            return []

        exclude = exclude or set()
        try:
            results = r.georadius(
                cls._GEO_KEY,
                lon, lat,
                radius_km,
                unit="km",
                withdist=True,
                sort="ASC",
            )
            return [
                (uid.decode(), round(float(dist), 2))
                for uid, dist in results
                if uid.decode() not in exclude
            ]
        except Exception as exc:
            logger.warning("Redis GEORADIUS failed: %s", exc)
            return []

    # ── connection-set helpers ───────────────────────────────────

    @classmethod
    def add_connection(cls, user_a: str, user_b: str) -> None:
        r = cls._redis()
        if r is None:
            return
        try:
            r.sadd(f"{cls._CONN_PFX}{user_a}", user_b)
            r.sadd(f"{cls._CONN_PFX}{user_b}", user_a)
        except Exception as exc:
            logger.warning("Redis SADD (connection) failed: %s", exc)

    @classmethod
    def remove_connection(cls, user_a: str, user_b: str) -> None:
        r = cls._redis()
        if r is None:
            return
        try:
            r.srem(f"{cls._CONN_PFX}{user_a}", user_b)
            r.srem(f"{cls._CONN_PFX}{user_b}", user_a)
        except Exception as exc:
            logger.warning("Redis SREM (connection) failed: %s", exc)

    @classmethod
    def connected_user_ids(cls, user_id: str) -> set[str]:
        r = cls._redis()
        if r is None:
            return set()
        try:
            members = r.smembers(f"{cls._CONN_PFX}{user_id}")
            return {m.decode() for m in members}
        except Exception as exc:
            logger.warning("Redis SMEMBERS failed: %s", exc)
            return set()

    # ── result cache ─────────────────────────────────────────────

    @classmethod
    def _cache_key(cls, user_id: str, filters: dict) -> str:
        raw = json.dumps(filters, sort_keys=True)
        h = hashlib.md5(raw.encode()).hexdigest()
        return f"{cls._RESULT_PFX}{user_id}:{h}"

    @classmethod
    def get_cached(cls, user_id: str, filters: dict) -> list[dict] | None:
        r = cls._redis()
        if r is None:
            return None
        try:
            data = r.get(cls._cache_key(user_id, filters))
            if data:
                return json.loads(data)
        except Exception as exc:
            logger.warning("Redis cache get failed: %s", exc)
        return None

    @classmethod
    def set_cached(cls, user_id: str, filters: dict, results: list[dict]) -> None:
        r = cls._redis()
        if r is None:
            return
        try:
            r.setex(
                cls._cache_key(user_id, filters),
                cls._RESULT_TTL,
                json.dumps(results, default=str),
            )
        except Exception as exc:
            logger.warning("Redis cache set failed: %s", exc)

    @classmethod
    def invalidate_user(cls, user_id: str) -> None:
        """
        Call when user's location or connection set changes.
        Removes location + metadata + all cached result keys for this user.
        """
        cls.remove_location(user_id)
        r = cls._redis()
        if r is None:
            return
        try:
            for key in r.scan_iter(f"{cls._RESULT_PFX}{user_id}:*"):
                r.delete(key)
        except Exception as exc:
            logger.warning("Redis cache invalidation failed: %s", exc)
