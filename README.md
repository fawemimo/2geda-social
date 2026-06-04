# 2geda Social API

Backend service for the **2geda Social** platform — a Django + DRF + Channels API covering authentication, social feeds, real-time chat, media management, and KYC verification.

---

## Folder structure

```
2geda-social/
├── core/                      # Django project (settings, urls, asgi, wsgi, celery)
│
├── accounts/                  # Identity, auth, profiles, follows, KYC, referrals
│   ├── services/              #   SOLID service layer
│   ├── models.py, views.py, serializers.py, urls.py
│   ├── tasks.py               #   Celery tasks (email OTP, purge, …)
│   ├── throttles.py
│   └── tests/
│
├── chats/                     # Real-time chat (WebSocket)
│   ├── services/
│   ├── consumers.py, models.py, routing.py
│   └── tests/
│
├── social/                    # Social feed — posts, comments, likes, notifications
│   ├── models.py, views.py, signals.py
│   └── tests.py
│
├── medias/                    # Media assets, variants, collections
│   ├── models.py, views.py
│   └── tests/
│
├── clients/                   # Third-party API wrappers
│   ├── aws/                   #   SES (email), S3 (storage)
│   └── google/                #   Firebase (push), Distance, Location
│
├── utils/                     # Cross-cutting utilities
│   ├── responses.py, pagination.py, exceptions.py
│   ├── models.py, enum.py
│   └── push.py, caches.py, encoders.py
│
├── templates/                 # HTML email templates (OTP, welcome)
│   └── accounts/emails/
│
├── archive/                   # Decommissioned Docker configs + notifications app
│
├── docker-compose.yaml
├── Dockerfile
├── entrypoint.sh              # Gunicorn REST API
├── entrypoint-daphne.sh       # Daphne WebSocket
├── entrypoint-worker.sh       # Celery worker
├── entrypoint-beat.sh         # Celery Beat scheduler
├── pytest.ini
├── conftest.py
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
