import hashlib

from rest_framework.throttling import ScopedRateThrottle


class DeviceScopedRateThrottle(ScopedRateThrottle):
    scope_attr = "throttle_scope"

    def get_cache_key(self, request, view):
        if view.action != "create":
            return None
        if not request.user.is_authenticated:
            return None
        self.scope = getattr(view, self.scope_attr, None)
        if not self.scope:
            return None
        device_id = request.headers.get("X-Device-ID", "") or request.META.get("HTTP_USER_AGENT", "")
        ident = hashlib.md5(f"{request.user.pk}:{device_id}".encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}
