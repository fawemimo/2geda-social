# 2geda Social API

Backend service for the **2geda Social** platform — a Django + DRF + Channels API designed to scale from prototype to millions of daily requests without architectural rework.

The codebase follows SOLID principles, a layered service architecture, and a single unified response envelope for every endpoint.

---

## Stack

| Layer            | Tech                                                          |
| ---------------- | ------------------------------------------------------------- |
| HTTP / REST      | Django 6 · DRF · Gunicorn (gthread workers)                   |
| WebSockets       | Django Channels · Daphne                                      |
| Auth             | JWT (SimpleJWT) with refresh-token rotation + blacklist       |
| Database         | PostgreSQL 16 (GIN / BRIN indexes, partial indexes)           |
| Cache / lock     | Redis 7 (also Channels backplane + Celery result store)       |
| Message broker   | **RabbitMQ 3.13** (AMQP)                                      |
| Background work  | Celery worker + Celery Beat (`django_celery_beat`)            |
| Monitoring       | Flower (Celery UI)                                            |
| Containers       | Docker Compose (no Nginx — terminate TLS at the edge)         |
| Tests            | pytest + pytest-django + factory_boy                          |

---

## Repository layout

```
2geda-social/
├── core/                       # Django project (settings, urls, asgi, wsgi, celery)
│   ├── settings.py
│   ├── prod_settings.py        # overrides loaded when USE_SETTINGS_FILE=CUSTOM
│   ├── celery.py               # Celery app — RabbitMQ broker, queue routing
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── accounts/                   # Identity, OTP, devices, profile, JWT
│   ├── models.py               # User, OTP, UserDevice, UserProfile, Follow, KYC, ...
│   ├── services/               # SOLID service layer — see docs/services-architecture.md
│   ├── serializers.py
│   ├── views.py                # Thin DRF adapters; no business logic
│   ├── urls.py                 # /api/v1/accounts/*
│   ├── tasks.py                # Celery tasks (send_otp_email, purge_expired_otps, ...)
│   ├── throttles.py            # Scoped & burst rate limits
│   └── tests/                  # pytest unit tests
│
├── utils/                      # Cross-cutting utilities
│   ├── responses.py            # APIResponse — the unified envelope builder
│   ├── pagination.py           # StandardPagination + CursorStandardPagination
│   ├── exceptions.py           # Global DRF exception handler
│   ├── models.py               # BaseModel, mixins (UUID, Timestamps, SoftDelete)
│   └── enum.py                 # Project-wide enums (OTPPurpose, DevicePlatform, ...)
│
├── docs/                       # Architecture + how-to docs (read these next)
│   ├── accounts.md
│   ├── services-architecture.md
│   ├── registration-flow.md
│   ├── authentication.md
│   ├── devices-and-profile.md
│   └── response-format.md
│
├── docker-compose.yaml         # Local + staging stack
├── Dockerfile                  # Multi-stage build (builder → runtime)
├── entrypoint.sh               # Gunicorn API entrypoint
├── entrypoint-daphne.sh        # Daphne ASGI entrypoint
├── entrypoint-worker.sh        # Celery worker entrypoint
├── entrypoint-beat.sh          # Celery Beat scheduler entrypoint
├── pytest.ini                  # pytest configuration
├── conftest.py                 # Global test fixtures
└── requirements.txt
```

---

## Quick start (Docker)

```bash
cp .env.example .env             # then edit secrets
docker compose up --build
```

That brings up:

| Service     | Address                          | What it does                                     |
| ----------- | -------------------------------- | ------------------------------------------------ |
| `api`       | http://localhost:8000            | Django REST under Gunicorn                       |
| `daphne`    | ws://localhost:8001/ws/...       | WebSockets (Channels)                            |
| `postgres`  | localhost:5432                   | Primary DB                                       |
| `redis`     | localhost:6379                   | Cache, rate limiter, Channels backplane          |
| `rabbitmq`  | localhost:5672 / :15672 (mgmt)   | Celery broker                                    |
| `worker`    | (internal)                       | Celery worker — `default,otp,notifications,media`|
| `beat`      | (internal)                       | Celery Beat scheduler                            |
| `flower`    | http://localhost:5555            | Celery monitoring UI                             |

Tail logs:

```bash
docker compose logs -f api worker daphne
```

---

## Quick start (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Start Postgres, Redis, RabbitMQ yourself
# 2. Export env vars (see .env.example)

python manage.py migrate
python manage.py createsuperuser

# REST API
gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 4 --threads 2 --worker-class gthread

# WebSockets
daphne -b 0.0.0.0 -p 8001 core.asgi:application

# Celery
celery -A core worker -Q default,otp,notifications,media --concurrency 4 -l info
celery -A core beat   -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

## API base & response envelope

All endpoints sit under `/api/v1/`. Every response — success or error, paginated or not — uses the same envelope. Full spec in [`docs/response-format.md`](docs/response-format.md).

**Success:**
```json
{ "status": true, "message": "Profile fetched successfully.", "data": { "...": "..." } }
```

**Error:**
```json
{ "status": false, "message": "OTP has expired.", "data": {}, "code": "otp_expired" }
```

**Paginated:**
```json
{
  "status": true,
  "message": "Items fetched successfully.",
  "data": [ /* ... */ ],
  "currentPage": 1, "nextPage": 2, "previousPage": null,
  "totalPages": 10, "totalItem": 200, "totalPerPage": 20
}
```

---

## Accounts endpoints (cheat-sheet)

| Method | Path                                                   | Purpose                                    |
| ------ | ------------------------------------------------------ | ------------------------------------------ |
| POST   | `/api/v1/accounts/auth/register/`                      | Stage signup + send OTP (no User created)  |
| POST   | `/api/v1/accounts/auth/verify-otp/`                    | Verify OTP → create User + issue tokens    |
| POST   | `/api/v1/accounts/auth/resend-otp/`                    | Resend OTP (pending or existing user)      |
| POST   | `/api/v1/accounts/auth/login/`                         | Login → JWT pair                           |
| POST   | `/api/v1/accounts/auth/logout/`                        | Blacklist a refresh token                  |
| POST   | `/api/v1/accounts/auth/logout-everywhere/`             | Blacklist every refresh + revoke devices   |
| POST   | `/api/v1/accounts/auth/token/refresh/`                 | Rotate refresh → new access + refresh      |
| POST   | `/api/v1/accounts/auth/password/reset/`                | Request password-reset OTP                 |
| POST   | `/api/v1/accounts/auth/password/reset/confirm/`        | Set new password with OTP                  |
| POST   | `/api/v1/accounts/auth/password/change/`               | Change password (authenticated)            |
| GET    | `/api/v1/accounts/me/`                                 | Current user                               |
| GET/PATCH | `/api/v1/accounts/me/profile/`                      | Profile read / partial update              |
| GET/POST | `/api/v1/accounts/me/devices/`                       | List / register device                     |
| DELETE | `/api/v1/accounts/me/devices/<uuid>/`                  | Revoke device (clears push token)          |
| POST   | `/api/v1/accounts/me/devices/<uuid>/push-token/`       | Rotate the FCM/APNs push token             |
| POST   | `/api/v1/accounts/me/devices/<uuid>/trust/`            | Mark device as trusted (skip 2FA)          |

Deeper walk-throughs live in [`docs/accounts.md`](docs/accounts.md).

---

## Tests

```bash
pytest                                  # full suite
pytest -m "not integration"             # unit-only
pytest accounts/tests/test_otp_service.py -k expired
pytest --cov=accounts --cov=utils       # with coverage
```

Test config is in `pytest.ini`; global fixtures live in `conftest.py`. See [`docs/accounts.md`](docs/accounts.md#tests) for the test layout.

---

## Documentation index

| File                                                        | Topic                                                       |
| ----------------------------------------------------------- | ----------------------------------------------------------- |
| [`docs/accounts.md`](docs/accounts.md)                      | Full accounts app walkthrough (models, services, endpoints) |
| [`docs/services-architecture.md`](docs/services-architecture.md) | SOLID layering, interfaces, dependency injection            |
| [`docs/registration-flow.md`](docs/registration-flow.md)    | OTP-first signup (no Postgres write until OTP verified)     |
| [`docs/authentication.md`](docs/authentication.md)          | Login, JWT issue/refresh/blacklist, brute-force lockout     |
| [`docs/devices-and-profile.md`](docs/devices-and-profile.md)| Device registration, trust, push tokens, profile updates    |
| [`docs/response-format.md`](docs/response-format.md)        | Unified envelope + global error handler                     |
