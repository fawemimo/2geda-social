#!/usr/bin/env bash
# entrypoint-beat.sh
# ---------------------------------------------------------------------------
# Entrypoint for the Celery Beat scheduler.
#
# Only one Beat process may run cluster-wide — use replicas: 1.
# Schedule lives in Postgres via django_celery_beat so it can be edited
# at runtime through the admin without redeploying.
# ---------------------------------------------------------------------------

set -euo pipefail

log() { echo "[beat] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }

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

wait_for_rabbitmq() {
    log "Waiting for RabbitMQ ..."
    local retries=0
    until python -c "
import os, sys, pika
try:
    params = pika.URLParameters(os.environ['CELERY_BROKER_URL'])
    conn = pika.BlockingConnection(params)
    conn.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
        retries=$((retries + 1))
        if [[ $retries -ge 30 ]]; then
            log "ERROR: RabbitMQ not reachable after 30 attempts."
            exit 1
        fi
        log "  Waiting for RabbitMQ (attempt ${retries}/30)"
        sleep 2
    done
    log "RabbitMQ is ready."
}

cleanup_pidfile() {
    local pidfile="/tmp/celerybeat.pid"
    if [[ -f "$pidfile" ]]; then
        log "Removing stale pidfile"
        rm -f "$pidfile"
    fi
}

start_beat() {
    local loglevel="${CELERY_LOG_LEVEL:-info}"
    local scheduler="${CELERY_BEAT_SCHEDULER:-django_celery_beat.schedulers:DatabaseScheduler}"

    log "Starting Celery Beat: scheduler=${scheduler}"

    exec celery -A core beat \
        --loglevel="${loglevel}" \
        --scheduler="${scheduler}" \
        --pidfile=/tmp/celerybeat.pid
}

wait_for_postgres
wait_for_rabbitmq
cleanup_pidfile
start_beat
