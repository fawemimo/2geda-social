from __future__ import annotations

# Base class for all service-layer errors.

class ServiceError(Exception):

    default_message = "A service error occurred."
    code = "service_error"
    status_code = 400

    def __init__(self, message: str | None = None, *, code: str | None = None, **context):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.code = code or self.code
        self.context = context


class ValidationError(ServiceError):
    default_message = "Invalid input."
    code = "validation_error"
    status_code = 400


class NotFoundError(ServiceError):
    default_message = "Resource not found."
    code = "not_found"
    status_code = 404


class ConflictError(ServiceError):
    default_message = "Resource conflict."
    code = "conflict"
    status_code = 409


class AuthenticationError(ServiceError):
    default_message = "Authentication failed."
    code = "authentication_failed"
    status_code = 401


class PermissionDeniedError(ServiceError):
    default_message = "Permission denied."
    code = "permission_denied"
    status_code = 403


class RateLimitedError(ServiceError):
    default_message = "Too many requests. Please slow down."
    code = "rate_limited"
    status_code = 429


class AccountLockedError(AuthenticationError):
    default_message = "Account temporarily locked due to failed login attempts."
    code = "account_locked"
    status_code = 423


class AccountInactiveError(AuthenticationError):
    default_message = "This account is inactive. Verify your email first."
    code = "account_inactive"
    status_code = 403



class OTPError(ServiceError):
    default_message = "OTP error."
    code = "otp_error"
    status_code = 400


class OTPExpiredError(OTPError):
    default_message = "This OTP has expired. Request a new one."
    code = "otp_expired"


class OTPInvalidError(OTPError):
    default_message = "Invalid OTP code."
    code = "otp_invalid"


class OTPMaxAttemptsError(OTPError):
    default_message = "Maximum OTP verification attempts exceeded."
    code = "otp_max_attempts"
    status_code = 429


class OTPCooldownError(OTPError):
    default_message = "Please wait before requesting another OTP."
    code = "otp_cooldown"
    status_code = 429


class OTPQuotaExceededError(OTPError):
    default_message = "Daily OTP quota exceeded for this account."
    code = "otp_quota_exceeded"
    status_code = 429

