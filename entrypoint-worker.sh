#!/usr/bin/env bash
# entrypoint-worker.sh
# ---------------------------------------------------------------------------
# Entrypoint for the Celery worker container.
# Waits for PostgreSQL + RabbitMQ, then runs a worker with concurrency
# and queue settings from environment.
# ---------------------------------------------------------------------------

set -euo pipefail

log() { echo "[worker] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }

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

start_worker() {
    local queues="${CELERY_QUEUES:-default,otp,notifications,media}"
    local concurrency="${CELERY_CONCURRENCY:-4}"
    local loglevel="${CELERY_LOG_LEVEL:-info}"
    local hostname="${CELERY_HOSTNAME:-worker@%h}"
    local max_tasks="${CELERY_MAX_TASKS_PER_CHILD:-500}"

    log "Starting Celery worker: queues=${queues} concurrency=${concurrency}"

    exec celery -A core worker \
        --queues="${queues}" \
        --concurrency="${concurrency}" \
        --hostname="${hostname}" \
        --loglevel="${loglevel}" \
        --max-tasks-per-child="${max_tasks}" \
        --without-gossip \
        --without-mingle \
        --without-heartbeat \
        -Ofair
}

wait_for_postgres
wait_for_rabbitmq
start_worker
