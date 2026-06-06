# Registration Flow (OTP-first)

The registration endpoint **does not** create a `User` row. Instead, the candidate signup payload is staged in Redis with a TTL, and the User is persisted only after the email OTP has been verified.

This prevents three classes of bug:

1. **Abandoned signups** never pollute the `accounts_user` table.
2. **Enumeration** of half-created accounts becomes impossible — there is no row to query.
3. **Unique-constraint contention** on Postgres for failed signups disappears.

---

## Sequence

```
client                          API                                Redis                Postgres                Celery → RabbitMQ → SMTP
  │                              │                                   │                     │                              │
  │  POST /auth/register/        │                                   │                     │                              │
  │ ───────────────────────────▶ │                                   │                     │                              │
  │                              │  validate payload                 │                     │                              │
  │                              │  hash password                    │                     │                              │
  │                              │  generate OTP, hash it            │                     │                              │
  │                              │  store {email, username, …,       │                     │                              │
  │                              │         password_hash, code_hash} │                     │                              │
  │                              │  with TTL = OTP_TTL_SECONDS       │                     │                              │
  │                              │ ────────────────────────────────▶ │                     │                              │
  │                              │  start_cooldown(email)            │                     │                              │
  │                              │ ────────────────────────────────▶ │                     │                              │
  │                              │  send_otp_email.delay(...)        │                     │                              │
  │                              │ ─────────────────────────────────────────────────────────────────────────────────────▶ │
  │  202 { otp_expires_at }      │                                   │                     │                              │
  │ ◀─────────────────────────── │                                   │                     │                              │
  │                              │                                   │                     │             (worker delivers OTP email)
  │                              │                                   │                     │                              │
  │  POST /auth/verify-otp/      │                                   │                     │                              │
  │ ───────────────────────────▶ │                                   │                     │                              │
  │                              │  load pending payload by email    │                     │                              │
  │                              │ ────────────────────────────────▶ │                     │                              │
  │                              │  check attempt count              │                     │                              │
  │                              │  hasher.verify(code, code_hash)   │                     │                              │
  │                              │  ─ success ─                      │                     │                              │
  │                              │  CREATE User + UserProfile        │                     │                              │
  │                              │ ─────────────────────────────────────────────────────▶ │                              │
  │                              │  delete pending payload           │                     │                              │
  │                              │ ────────────────────────────────▶ │                     │                              │
  │                              │  TokenService.issue(user)         │                     │                              │
  │  201 { access, refresh, user_id } │                              │                     │                              │
  │ ◀─────────────────────────── │                                   │                     │                              │
```

---

## Pending payload shape (Redis)

Key: `v1:accounts:pending_registration:<sha256(email)>`
TTL: `OTP_TTL_SECONDS` (default 600s)

```json
{
  "email": "smithEze@example.com",
  "username": "smithEze",
  "phone_number": "+2348012345678",
  "password_hash": "pbkdf2_sha256$...",
  "referral_code": "A3GX91KZ",
  "code_hash": "pbkdf2_sha256$...",   // hashed OTP — never plaintext
  "attempts": 0,
  "issued_at": "2026-05-23T10:00:00+00:00",
  "ip_address": "203.0.113.42"
}
```

A bumped `attempts` count is written back on each failed verify so brute-force is bounded by `OTP_MAX_ATTEMPTS` (default 5). Hitting the cap deletes the payload — the user must restart.

---

## Cooldown and quota (Redis, hashed-email-keyed)

- `cooldown:<sha256(email)>` — TTL = `OTP_RESEND_COOLDOWN_SECONDS` (60s). Prevents OTP flooding.
- `quota:<sha256(email)>` — TTL = 1 day. Counts OTP issuances against `OTP_DAILY_QUOTA` (20).

These are separate from the DRF throttle scopes which sit one layer above (per-IP / per-user). Both layers must pass.

---

## Resend

`POST /auth/resend-otp/` with `purpose=registration` calls `RegistrationService.resend_registration_otp(email=...)`. The pending payload must still exist in Redis (i.e. the user is still inside the TTL window). The OTP is regenerated and stored; the cooldown restarts.

For non-registration purposes (login OTP, password reset), the same endpoint dispatches to `OTPService.issue(...)` against the existing `User` row.

---

## Failure modes & responses

| Condition                                       | `code`                          | HTTP |
| ----------------------------------------------- | ------------------------------- | ---- |
| Email / username / phone already taken          | `account_exists`                | 409  |
| OTP cooldown active                             | `otp_cooldown`                  | 429  |
| Daily OTP quota exceeded                        | `otp_quota_exceeded`            | 429  |
| Pending payload expired or never created        | `pending_registration_missing`  | 404  |
| Wrong OTP code (under attempts cap)             | `otp_invalid`                   | 400  |
| Max attempts hit — payload purged               | `otp_max_attempts`              | 429  |
| TTL elapsed mid-flow                            | `otp_expired`                   | 400  |
| Referrer code does not resolve                  | `referrer_not_found`            | 404  |
| Password fails Django validators                | `password_weak`                 | 400  |

---

## Why not store the pending OTP in Postgres?

The existing `OTP` table requires a `user_id` FK and a `User` row. Creating that row before verification would defeat the purpose. The alternative — a separate `PendingRegistration` Postgres table — would work but:

- Adds two writes per signup (insert + delete).
- Adds an extra cleanup cron.
- Adds index pressure on a high-churn table.

Redis with TTL handles all of that for free, and `django_redis` is already a runtime dependency for caching + Channels.

---

## Operational knobs

All overridable via env (defaults shown):

| Env var                          | Default | Purpose                                |
| -------------------------------- | ------- | -------------------------------------- |
| `OTP_CODE_LENGTH`                | 6       | Digits in the OTP                      |
| `OTP_TTL_SECONDS`                | 600     | Pending payload lifetime in Redis      |
| `OTP_MAX_ATTEMPTS`               | 5       | Failed-verify cap per pending payload  |
| `OTP_RESEND_COOLDOWN_SECONDS`    | 60      | Min gap between OTP sends per email    |
| `OTP_DAILY_QUOTA`                | 20      | Max OTPs per email per day             |
