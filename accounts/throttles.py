from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle


class BurstAnonThrottle(AnonRateThrottle):
    scope = "anon_burst"


class SustainedAnonThrottle(AnonRateThrottle):
    scope = "anon_sustained"


class BurstUserThrottle(UserRateThrottle):
    scope = "user_burst"


class SustainedUserThrottle(UserRateThrottle):
    scope = "user_sustained"


class OTPRequestThrottle(ScopedRateThrottle):
    scope_attr = "throttle_scope"


class OTPVerifyThrottle(ScopedRateThrottle):
    scope_attr = "throttle_scope"


class LoginThrottle(ScopedRateThrottle):
    scope_attr = "throttle_scope"


class RegistrationThrottle(ScopedRateThrottle):
    scope_attr = "throttle_scope"

