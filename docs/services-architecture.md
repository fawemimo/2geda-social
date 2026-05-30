# Services Architecture (SOLID layering)

## Why a service layer?

Django happily lets you put business logic in views, serializers, model methods, signals, or admin actions. That spread becomes a tax the moment the same operation is invoked from two places (an API call and a Celery task, say) or needs to be tested in isolation.

We funnel **every** mutation through a service. The contract is:

- **Views** validate HTTP-shaped input, call exactly one service method, return `APIResponse`.
- **Services** validate business invariants, coordinate the ORM + cache + queues, raise `ServiceError` subclasses on failure.
- **Models** describe persistence and the small invariants the database alone enforces.

That means: any view, any task, any management command can perform the operation the same way. And every test can hit the service directly instead of going through the HTTP stack.

---

## The five SOLID principles, applied

### S — Single Responsibility

One service per use-case cluster:

| Service                  | Responsibility                                      |
| ------------------------ | --------------------------------------------------- |
| `RegistrationService`    | Pre-signup payload + OTP-gated User creation        |
| `OTPService`             | DB-backed OTPs for existing users                   |
| `AuthenticationService`  | Login / logout, brute-force lockout                 |
| `TokenService`           | JWT issue / refresh / blacklist                     |
| `PasswordService`        | Password reset + change                             |
| `DeviceService`          | Per-device session management                       |
| `ProfileService`         | Profile read + whitelisted partial update           |

Each is small enough that the test file mirrors the class structure 1:1.

### O — Open / Closed

Services compose primitives via interfaces (see below). Adding a new OTP delivery channel (push, in-app, WhatsApp) is a new `INotificationSender` implementation — no edits to `OTPService` or any view.

### L — Liskov Substitution

`RedisDistributedLock` is interchangeable with any `IDistributedLock` (in tests we pass a `FakeLock` that always acquires). Same for `RedisRateLimiter`, `EmailNotificationSender`, etc.

### I — Interface Segregation

`accounts/services/interfaces.py` defines small interfaces:

- `INotificationSender` — just `send(payload)`
- `IOTPGenerator` — just `generate(length)`
- `IOTPHasher` — `hash`, `verify`
- `IRateLimiter` — `hit`, `reset`, `cooldown`, `start_cooldown`
- `IDistributedLock` — `acquire`, `release`
- `ITokenManager` — `issue`, `refresh`, `revoke`, `revoke_all_for_user`

Nothing forces a class to implement methods it doesn't need.

### D — Dependency Inversion

Services accept their collaborators in `__init__` and default to sensible production implementations:

```python
class OTPService:
    def __init__(
        self,
        *,
        generator: IOTPGenerator | None = None,
        hasher:    IOTPHasher    | None = None,
        rate_limiter: IRateLimiter | None = None,
        lock: IDistributedLock | None = None,
    ) -> None:
        self._generator = generator or SecureOTPGenerator()
        self._hasher = hasher or DjangoOTPHasher()
        ...
```

Tests pass fakes. Production passes nothing — defaults are wired in.

---

## Module map

```
accounts/services/
├── interfaces.py           # the boundaries
├── exceptions.py           # ServiceError + subclasses
│
├── cache.py                # versioned, hashed cache-key helpers
├── rate_limiter.py         # RedisRateLimiter + RedisDistributedLock
├── otp_generator.py        # SecureOTPGenerator + DjangoOTPHasher
├── notifications.py        # EmailNotificationSender + SMSNotificationSender + Null...
├── pending_registration.py # PendingRegistrationStore (Redis-only)
│
├── otp.py                  # OTPService           ─┐
├── registration.py         # RegistrationService    │
├── authentication.py       # AuthenticationService  │  use-case services
├── tokens.py               # JWTTokenService        │
├── password.py             # PasswordService        │
├── device.py               # DeviceService          │
└── profile.py              # ProfileService        ─┘
```

The use-case services depend only on:
- ORM models from `accounts.models`
- Primitives from the upper half of the diagram
- Each other through composition (e.g. `RegistrationService` depends on `TokenService`)

They never import:
- `accounts.serializers`
- `accounts.views`
- DRF
- Django's HTTP layer

That keeps the service layer reusable from Celery tasks, management commands, websocket consumers — anywhere.

---

## Error model

Services raise `ServiceError` subclasses. Each carries:

- `message` — human-readable string
- `code` — stable machine-readable string (`otp_expired`, `account_locked`, ...)
- `status_code` — the HTTP status to use when serialised
- `context` — optional `dict` of extra fields

The global DRF exception handler (`utils.exceptions.custom_exception_handler`) maps any uncaught `ServiceError` into the unified envelope:

```json
{ "status": false, "message": "OTP has expired.", "data": {}, "code": "otp_expired" }
```

This means views don't need try/except blocks. Raise and forget.

---

## Adding a new use case

The recipe is mechanical:

1. **Define the result dataclass** in the service module.
2. **Add a method** to the relevant service (or create a new one if it doesn't fit).
3. **Wire it through a thin view** that validates input, calls the method, returns `APIResponse`.
4. **Add a route** in `accounts/urls.py`.
5. **Write a unit test** that mocks any heavy collaborator and asserts behaviour on the service directly.
6. **Document** the new endpoint in `docs/accounts.md` if it changes the public surface.

If you find yourself adding business rules inside a view, stop — they belong in the service.
