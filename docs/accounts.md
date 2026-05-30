# Accounts App

The `accounts/` app owns user identity, OTP delivery, JWT issuance, device management, and profile data.

It is structured as a **services-first** Django app:

```
accounts/
├── models.py          # Postgres-backed entities
├── services/          # All business logic — the only layer views talk to
├── serializers.py     # DRF input/output shapes (no business rules)
├── views.py           # Thin HTTP adapters
├── urls.py
├── tasks.py           # Celery tasks (OTP email, OTP SMS, purge job)
├── throttles.py       # Per-endpoint rate limits
└── tests/             # pytest unit tests
```

Views never touch the ORM directly. Every endpoint instantiates a service, calls one method, and returns the result wrapped in `APIResponse`.

---

## Models

| Model         | Responsibility                                                                 |
| ------------- | ------------------------------------------------------------------------------ |
| `User`        | Auth identity (email + password). Carries `referral_code`, soft-delete flags. |
| `OTP`         | Hashed OTP codes for **existing-user** flows (login, password reset, ...).    |
| `UserDevice`  | Per-device records (fingerprint, push token, trust state, last seen).         |
| `UserLocation`| Append-only location snapshots.                                                |
| `Referral`    | Records a completed referral conversion.                                       |
| `UserProfile` | Public-facing profile (display name, bio, avatar, follower counts).            |
| `Follow`      | Directed follow graph (`pending`/`accepted`/`blocked`).                        |
| `KYC`         | KYC verification record per user.                                              |

> The **registration OTP** is *not* in the `OTP` table — it lives in Redis because no `User` row exists yet. See [`registration-flow.md`](registration-flow.md).

---

## Services

All services follow Single Responsibility. They expose a domain API (`register`, `login`, `verify`, `revoke`, ...) and raise domain exceptions from `accounts.services.exceptions`.

| Service                | Module                                              | Purpose                                                  |
| ---------------------- | --------------------------------------------------- | -------------------------------------------------------- |
| `RegistrationService`  | `accounts/services/registration.py`                 | Two-phase OTP-first signup                               |
| `OTPService`           | `accounts/services/otp.py`                          | Issue/verify OTPs for existing users                     |
| `AuthenticationService`| `accounts/services/authentication.py`               | Login, logout, brute-force lockout                       |
| `TokenService`         | `accounts/services/tokens.py`                       | JWT issue / refresh-with-rotation / blacklist            |
| `PasswordService`      | `accounts/services/password.py`                     | Reset request, reset confirm, change                     |
| `DeviceService`        | `accounts/services/device.py`                       | Register / revoke / list / trust / push-token rotation   |
| `ProfileService`       | `accounts/services/profile.py`                      | Whitelisted partial updates spanning User + UserProfile  |

Supporting modules:

| Module                                              | Purpose                                                       |
| --------------------------------------------------- | ------------------------------------------------------------- |
| `accounts/services/interfaces.py`                   | Abstract interfaces (DIP boundaries)                          |
| `accounts/services/exceptions.py`                   | Domain exceptions with `code` + HTTP `status_code`            |
| `accounts/services/rate_limiter.py`                 | `RedisRateLimiter`, `RedisDistributedLock`                    |
| `accounts/services/otp_generator.py`                | CSPRNG OTP generator + password-hash-style OTP hasher         |
| `accounts/services/pending_registration.py`         | Redis-backed pre-OTP signup store                             |
| `accounts/services/notifications.py`                | Email / SMS senders (used by Celery tasks)                    |
| `accounts/services/cache.py`                        | Versioned, hashed cache-key helpers                           |

See [`services-architecture.md`](services-architecture.md) for the layering rationale.

---

## Endpoints

All endpoints are mounted under `/api/v1/accounts/`.

### Registration

| Method | Path                  | Service call                                  |
| ------ | --------------------- | --------------------------------------------- |
| POST   | `/auth/register/`     | `RegistrationService.start_registration(...)` |
| POST   | `/auth/verify-otp/`   | `RegistrationService.complete_registration(...)` |
| POST   | `/auth/resend-otp/`   | `RegistrationService.resend_registration_otp(...)` *or* `OTPService.issue(...)` |

`POST /auth/register/` does **not** create the User. It validates input, hashes the password, stashes the payload + OTP hash in Redis (TTL = `OTP_TTL_SECONDS`), and queues `send_otp_email`. The User row is created only after `POST /auth/verify-otp/` succeeds — see [`registration-flow.md`](registration-flow.md).

### Login / logout

| Method | Path                          | Service call                                          |
| ------ | ----------------------------- | ----------------------------------------------------- |
| POST   | `/auth/login/`                | `AuthenticationService.login(...)`                    |
| POST   | `/auth/logout/`               | `AuthenticationService.logout(refresh_token=...)`     |
| POST   | `/auth/logout-everywhere/`    | `AuthenticationService.logout_everywhere(user=...)`   |
| POST   | `/auth/token/refresh/`        | `TokenService.refresh(refresh_token=...)`             |

Brute-force lockouts use a Redis counter keyed on email — failed-login attempts never touch the User row.

### Password

| Method | Path                            | Service call                                  |
| ------ | ------------------------------- | --------------------------------------------- |
| POST   | `/auth/password/reset/`         | `PasswordService.request_reset(email=...)`    |
| POST   | `/auth/password/reset/confirm/` | `PasswordService.confirm_reset(...)`          |
| POST   | `/auth/password/change/`        | `PasswordService.change_password(user=...)`   |

`request_reset` always returns 200 — the response is identical whether the email exists or not, so attackers can't enumerate accounts.

### Profile & devices

| Method        | Path                                       | Service                                                 |
| ------------- | ------------------------------------------ | ------------------------------------------------------- |
| GET           | `/me/`                                     | (`request.user`)                                        |
| GET / PATCH   | `/me/profile/`                             | `ProfileService.get` / `update_partial`                 |
| GET / POST    | `/me/devices/`                             | `DeviceService.list_for_user` / `register`              |
| DELETE        | `/me/devices/<uuid>/`                      | `DeviceService.revoke`                                  |
| POST          | `/me/devices/<uuid>/push-token/`           | `DeviceService.update_push_token`                       |
| POST          | `/me/devices/<uuid>/trust/`                | `DeviceService.trust`                                   |

See [`devices-and-profile.md`](devices-and-profile.md) for the full device lifecycle.

---

## Celery tasks

Defined in `accounts/tasks.py`, routed by queue in `core/celery.py`:

| Task                                | Queue           | Trigger                                      |
| ----------------------------------- | --------------- | -------------------------------------------- |
| `accounts.tasks.send_otp_email`     | `otp`           | Registration / login / reset OTP delivery    |
| `accounts.tasks.send_otp_sms`       | `otp`           | (Plug a vendor into `SMSNotificationSender`) |
| `accounts.tasks.send_welcome_email` | `notifications` | Post-onboarding (call from a signal)         |
| `accounts.tasks.purge_expired_otps` | `default`       | Hourly Beat job — TTL-style cleanup          |

All tasks use `autoretry_for=(Exception,)`, exponential back-off, jitter, `max_retries=5`, and `acks_late=True` so they survive worker restarts.

---

## Throttling

`accounts/throttles.py` defines scoped throttles. Rates live in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`:

| Scope         | Rate            | Applied to                                    |
| ------------- | --------------- | --------------------------------------------- |
| `anon_burst`  | 60/minute       | All anonymous traffic                         |
| `anon_sustained` | 1000/day     | All anonymous traffic                         |
| `user_burst`  | 240/minute      | All authenticated traffic                     |
| `user_sustained` | 20000/day    | All authenticated traffic                     |
| `registration`| 10/minute       | `POST /auth/register/`                        |
| `otp_request` | 5/minute        | `POST /auth/resend-otp/`, password reset req. |
| `otp_verify`  | 10/minute       | OTP verification endpoints                    |
| `login`       | 20/minute       | `POST /auth/login/`                           |

The OTP service additionally enforces:
- per-user cooldown (`OTP_RESEND_COOLDOWN_SECONDS`, default 60s)
- per-user daily quota (`OTP_DAILY_QUOTA`, default 20)
- per-OTP attempt cap (`OTP_MAX_ATTEMPTS`, default 5) — counted in Redis, not Postgres

---

## Scalability notes

| Concern                                  | Mitigation                                                                                  |
| ---------------------------------------- | ------------------------------------------------------------------------------------------- |
| Failed login attempts hammering the DB   | Counter lives in Redis, not on the User row                                                 |
| OTP verify race (parallel guesses)       | `RedisDistributedLock` around `OTPService.verify`                                            |
| Slow SMTP blocking the request           | OTP email goes through Celery (RabbitMQ queue `otp`)                                        |
| Abandoned signups polluting `accounts_user` | OTP-first flow — no User row until OTP verified                                          |
| Refresh-token replay                     | SimpleJWT rotation + blacklist (`token_blacklist`) on every refresh                          |
| Hot-pathing the same OTP row             | Attempt counter in Redis; single `UPDATE` to flip `is_used`                                  |
| Cleaning up dead OTP rows                | `purge_expired_otps` Beat job                                                                |

---

## Tests

Tests live under `accounts/tests/`. They are pure pytest functions — no `unittest.TestCase`. The structure is:

```
accounts/tests/
├── __init__.py
├── conftest.py                   # local fixtures (FakeCache, FakeNotificationSender, ...)
├── factories.py                  # factory_boy User/profile/device factories
├── test_responses.py             # APIResponse builder
├── test_pagination.py            # StandardPagination envelope
├── test_exceptions.py            # custom_exception_handler
├── test_otp_generator.py         # SecureOTPGenerator + DjangoOTPHasher
├── test_pending_registration.py  # PendingRegistrationStore
├── test_otp_service.py           # OTPService (issue + verify + lockout)
├── test_registration_service.py  # RegistrationService (start + complete + resend)
├── test_authentication_service.py# AuthenticationService (login + lockout + logout)
├── test_password_service.py      # PasswordService (request/confirm/change)
├── test_token_service.py         # JWT issue / refresh / revoke
├── test_device_service.py        # Device register / revoke / push token / trust
├── test_profile_service.py       # Profile read + whitelisted partial update
└── test_views_smoke.py           # APIClient smoke tests (mocked services)
```

Tests mark slow / DB-touching ones explicitly:

```python
@pytest.mark.unit          # no I/O — runs in milliseconds
@pytest.mark.integration   # needs DB / Redis
```

Run subsets:

```bash
pytest                                 # everything
pytest -m unit                         # unit only
pytest -m "not integration"            # skip DB tests
pytest --cov=accounts --cov=utils      # coverage
```

Heavy collaborators (cache, Celery, ORM) are replaced via fixtures and patched at the boundary, so most tests do not need Postgres or Redis to run.
