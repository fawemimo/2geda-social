# 2geda Social API

Backend service for the **2geda Social** platform — a Django + DRF + Channels API covering authentication, social feeds, real-time polls, chat, media management, and KYC verification.

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
├── polls/                     # Real-time polls (REST + WebSocket)
│   ├── services/              #   poll_service, broadcaster, rate_limiter, exceptions
│   ├── management/commands/   #   close_expired_polls (CLI)
│   ├── consumers.py           #   WebSocket vote / unvote / ping
│   ├── models.py, views.py, serializers.py, routing.py, enums.py
│   ├── tasks.py               #   Celery task — auto-close expired polls
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

| Service             | Address                            | What it does                                                |
| ------------------- | ---------------------------------- | ----------------------------------------------------------- |
| `api`               | http://localhost:8000              | Django REST under Gunicorn                                  |
| `daphne`            | ws://localhost:8001/ws/...         | WebSockets (Channels)                                       |
| `postgres`          | localhost:5432                     | Primary DB                                                  |
| `redis`             | localhost:6379                     | Cache, rate limiter, Channels backplane                     |
| `rabbitmq`          | localhost:5672 / :15672 (mgmt)     | Celery broker                                               |
| `worker`            | (internal)                         | Celery worker — `default,otp,notifications,media`           |
| `beat`              | (internal)                         | Celery Beat scheduler                                       |


Tail logs:

```bash
docker compose logs -f api worker daphne
```

---

## Polls app

Real-time polls with REST + WebSocket support.

### Features

- **Poll CRUD** — create, update, delete, close (REST API)
- **Single & multiple choice** — configurable per poll (`poll_type`)
- **Voting via WebSocket** — `vote` / `unvote` messages broadcast `poll_event` updates to all connected clients
- **Visibility controls** — per-poll: `show_results`, `show_voters`, `show_vote_counts`, `show_view_counts`
- **Race condition safe** — `select_for_update` row-level locking on all vote mutations
- **Auto-close expired** — Celery beat fires `close_expired_polls` every 5 minutes; polls past `ends_at` are closed and broadcast `poll.closed`
- **Rate limiting** — WebSocket votes capped at 30/min per user per poll; returns `rate_limited` error
- **View tracking** — authenticated deduped view counting

### WebSocket endpoint

```
ws://localhost:8001/ws/polls/<poll_id>/?token=<jwt_access_token>
```

### Management commands

```bash
python manage.py close_expired_polls              # close expired polls
python manage.py close_expired_polls --dry-run     # preview without closing
```
