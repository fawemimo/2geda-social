# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Multi-stage build for the 2geda Social API.
#   builder  → installs Python deps into a virtualenv
#   runtime  → lean final image with the venv + source code
# ---------------------------------------------------------------------------

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install -r requirements.txt \
 && pip install gunicorn pika


# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE="core.settings" \
    APP_HOME=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        gettext \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1001 appgroup \
 && useradd  --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR ${APP_HOME}

COPY --chown=appuser:appgroup . .

# Entry-point scripts (kept at project root).
RUN chmod +x ${APP_HOME}/entrypoint.sh \
              ${APP_HOME}/entrypoint-worker.sh \
              ${APP_HOME}/entrypoint-beat.sh \
              ${APP_HOME}/entrypoint-daphne.sh

RUN mkdir -p ${APP_HOME}/staticfiles ${APP_HOME}/mediafiles \
 && chown -R appuser:appgroup ${APP_HOME}/staticfiles ${APP_HOME}/mediafiles

USER appuser

EXPOSE 8000 8001

ENTRYPOINT ["/app/entrypoint.sh"]
