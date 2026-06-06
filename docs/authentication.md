# Authentication

Authentication is JWT-based, backed by `djangorestframework-simplejwt` with refresh-token rotation and the blacklist app enabled.

```python
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":  timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS":  True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    ...
}
```

`rest_framework_simplejwt.token_blacklist` is in `INSTALLED_APPS`, so every refresh creates one new pair *and* blacklists the previous refresh. Stolen refresh tokens are valid for at most one extra rotation before they are rejected.

---

## Login

```
POST /api/v1/accounts/auth/login/
{ "email": "smithEze@example.com", "password": "...", "device": { ... }? }
```

Flow (`AuthenticationService.login`):

1. Lower-case + trim `email`.
2. Check Redis `auth:cooldown:<email>` — short-circuit with 423 if locked out.
3. Call Django `authenticate(email, password)`.
   - On failure: increment Redis counter `auth:login:<email>` (TTL = lockout window). Hitting `LOGIN_MAX_FAILED_ATTEMPTS` (default 10) flips the cooldown for `LOGIN_LOCKOUT_SECONDS` (default 900s).
4. On success: reset the counter, register/update the device (if a `device` payload was sent), issue tokens.

Response:

```json
{
  "status": true,
  "message": "Logged in successfully.",
  "data": {
    "user_id":    "uuid",
    "access":     "eyJ...",
    "refresh":    "eyJ...",
    "token_type": "Bearer",
    "device_id":  "uuid|null"
  }
}
```

> The brute-force counter intentionally lives in Redis. Hot-updating the `User` row on every wrong guess would serialize writes to a single row at high traffic.

---

## Refresh

```
POST /api/v1/accounts/auth/token/refresh/
{ "refresh": "eyJ..." }
```

`TokenService.refresh`:

1. Validate the refresh JWT.
2. Blacklist it (rotation).
3. Look up the user.
4. Issue a brand-new access + refresh pair, copying the `device_id` claim if present.

Response is the same shape as the login `data` minus `user_id`/`device_id`:

```json
{ "access": "eyJ...", "refresh": "eyJ...", "token_type": "Bearer" }
```

---

## Logout

| Endpoint                                           | Effect                                                            |
| -------------------------------------------------- | ----------------------------------------------------------------- |
| `POST /auth/logout/`                               | Blacklists the supplied `refresh` token (current session)         |
| `POST /auth/logout-everywhere/`                    | Blacklists every outstanding refresh + soft-deletes user devices  |

Logout-everywhere uses `iterator(chunk_size=500)` over outstanding tokens so the operation stays bounded in memory even for users with hundreds of devices.

---

## Password reset (OTP-gated)

```
POST /auth/password/reset/         { "email": "..." }
POST /auth/password/reset/confirm/ { "email": "...", "code": "123456", "new_password": "..." }
```

`PasswordService.request_reset` always returns the same 200 response whether the email exists or not:

```json
{ "status": true, "message": "If that email is registered, an OTP has been sent.", "data": {} }
```

`confirm_reset` verifies the OTP (via `OTPService`), sets the new password, and **revokes every refresh token** for that user so any device that knew the old password is signed out.

`change_password` (authenticated) does the same — verifies the current password, sets the new one, blacklists every refresh token.

---

## Token claims

Custom claims are added by `accounts.serializers.UserTokenObtainPairSerializer`:

```python
class UserTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["username"] = user.username
        token["email"] = user.email
        return token
```

Tokens issued via `TokenService.issue` additionally carry a `device_id` claim when a device was registered, so server-side code can correlate sessions to devices without an extra DB lookup.

---

## Authentication header

```
Authorization: JWT <access_token>
```

(`AUTH_HEADERS_TYPES = ("JWT",)` in `SIMPLE_JWT`.) `Bearer` is **not** accepted — change `AUTH_HEADERS_TYPES` if your client requires it.

---

## Failure modes

| Condition                                | `code`                  | HTTP |
| ---------------------------------------- | ----------------------- | ---- |
| Missing email/password                   | `credentials_required`  | 400  |
| Wrong credentials (under cap)            | `authentication_failed` | 401  |
| Login lockout window active              | `account_locked`        | 423  |
| User exists but is inactive              | `account_inactive`      | 403  |
| User has been soft-deleted               | `authentication_failed` | 401  |
| Refresh token invalid / blacklisted      | `authentication_failed` | 401  |
| Inactive user given a token by mistake   | `authentication_failed` | 401  |
