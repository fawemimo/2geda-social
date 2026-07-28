import hashlib
import logging
import re
import time

from django.core.cache import cache
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle


logger = logging.getLogger(__name__)

_RATE_RE = re.compile(r"(\d+)/(\d+)([smhd])")

_redis_client: object | None = None
_lua_check_quota: object | None = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = cache.client.get_client()
        except Exception:
            return None
    return _redis_client


CHECK_QUOTA_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local current = redis.call('GET', key)
if current then
    current = tonumber(current)
    if current >= limit then
        return {0, current, redis.call('TTL', key)}
    end
    local new = redis.call('INCR', key)
    return {1, new, redis.call('TTL', key)}
else
    redis.call('SET', key, 1, 'EX', window)
    return {1, 1, window}
end
"""


def _load_lua_quota():
    global _lua_check_quota
    if _lua_check_quota is not None:
        return _lua_check_quota
    client = _get_redis()
    if client is not None:
        try:
            _lua_check_quota = client.register_script(CHECK_QUOTA_SCRIPT)
        except Exception as exc:
            logger.warning("Failed to register Lua throttle script: %s", exc)
    return _lua_check_quota


def _parse_rate(rate: str) -> tuple[int, int]:
    match = _RATE_RE.match(rate)
    if not match:
        raise ValueError(f"Invalid rate format: {rate!r}")
    count = int(match.group(1))
    window_value = int(match.group(2))
    unit = match.group(3)
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return count, window_value * multiplier


def _throttle_key(request, scope: str) -> str:
    ident = _throttle_ident(request)
    raw = f"throttle:{scope}:{ident}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _throttle_ident(request):
    xfwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if xfwd:
        return xfwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class PipelineScopedThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        scope = getattr(view, self.scope_attr, None) or getattr(self, "scope", None)
        if scope is None:
            return True

        try:
            rate = self.get_rate()
        except Exception:
            return True
        if rate is None:
            return True

        limit, window = _parse_rate(rate)
        key = _throttle_key(request, scope)

        lua = _load_lua_quota()
        if lua is not None:
            try:
                now = int(time.time())
                allowed, count, ttl = lua(keys=[key], args=[limit, window, now])
                if not allowed:
                    self._throttle_denied(request, view, key, limit, window)
                    return False
                self._throttle_allowed(request, view, key, limit, window)
                return True
            except Exception as exc:
                logger.warning("Lua throttle failed, falling back: %s", exc)

        return super().allow_request(request, view)

    def wait(self):
        return int(super().wait() or 0)


class BurstAnonThrottle(AnonRateThrottle):
    scope = "anon_burst"


class SustainedAnonThrottle(AnonRateThrottle):
    scope = "anon_sustained"


class BurstUserThrottle(UserRateThrottle):
    scope = "user_burst"


class SustainedUserThrottle(UserRateThrottle):
    scope = "user_sustained"


class OTPRequestThrottle(PipelineScopedThrottle):
    scope_attr = "throttle_scope"


class OTPVerifyThrottle(PipelineScopedThrottle):
    scope_attr = "throttle_scope"


class LoginThrottle(PipelineScopedThrottle):
    scope_attr = "throttle_scope"


class RegistrationThrottle(PipelineScopedThrottle):
    scope_attr = "throttle_scope"

