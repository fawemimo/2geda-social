#!/usr/bin/env bash
# entrypoint-daphne.sh
# ---------------------------------------------------------------------------
# Entrypoint for the Daphne ASGI server container.
#
# Owns WebSocket connections only (/ws/*). REST traffic stays on Gunicorn.
# Migrations are NOT run here — the api container owns the migration step.
# ---------------------------------------------------------------------------

set -euo pipefail

log() { echo "[daphne] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }

wait_for_postgres() {
    log "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT} ..."
    local retries=0
    until python -c "
import os, sys, psycopg2
try:
    psycopg2.connect(
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        connect_timeout=3,
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
        retries=$((retries + 1))
        if [[ $retries -ge 30 ]]; then
            log "ERROR: PostgreSQL not reachable after 30 attempts."
            exit 1
        fi
        log "  Waiting for PostgreSQL (attempt ${retries}/30)"
        sleep 2
    done
    log "PostgreSQL is ready."
}

wait_for_redis() {
    log "Waiting for Redis ..."
    local retries=0
    until python -c "
import os, sys, redis
try:
    r = redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'))
    r.ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
        retries=$((retries + 1))
        if [[ $retries -ge 20 ]]; then
            log "ERROR: Redis not reachable after 20 attempts."
            exit 1
        fi
        log "  Waiting for Redis (attempt ${retries}/20)"
        sleep 2
    done
    log "Redis is ready."
}

wait_for_migrations() {
    log "Waiting for database migrations ..."
    local retries=0
    until python manage.py migrate --check --no-input > /dev/null 2>&1; do
        retries=$((retries + 1))
        if [[ $retries -ge 20 ]]; then
            log "WARNING: migrate --check timed out — proceeding."
            return 0
        fi
        sleep 3
    done
    log "Migrations applied."
}

start_daphne() {
    local bind="${DAPHNE_BIND:-0.0.0.0}"
    local port="${DAPHNE_PORT:-8001}"
    log "Starting Daphne on ${bind}:${port}"

    exec daphne \
        --bind "${bind}" \
        --port "${port}" \
        --proxy-headers \
        --access-log "-" \
        --ping-interval 20 \
        --ping-timeout 30 \
        core.asgi:application
}

main() {
    wait_for_postgres
    wait_for_redis
    wait_for_migrations
    start_daphne
}

main "$@"
