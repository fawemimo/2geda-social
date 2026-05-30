#!/usr/bin/env bash
# entrypoint.sh
# ---------------------------------------------------------------------------
# Entrypoint for the Django API container (development).
#
#   1. Wait for PostgreSQL
#   2. (Optional) wait for RabbitMQ
#   3. Run makemigrations + migrate
#   4. Collect static files
#   5. Start `python manage.py runserver`  (dev)
#
# For production, replace the runserver invocation at the bottom with the
# Gunicorn command included as a comment.
# ---------------------------------------------------------------------------

set -euo pipefail

log() { echo "[api] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }

wait_for_postgres() {
    log "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT} ..."
    local retries=0
    local max_retries=30
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
        if [[ $retries -ge $max_retries ]]; then
            log "ERROR: PostgreSQL not reachable after ${max_retries} attempts."
            exit 1
        fi
        log "  PostgreSQL not ready (attempt ${retries}/${max_retries}) — retrying in 2s"
        sleep 2
    done
    log "PostgreSQL is ready."
}

wait_for_rabbitmq() {
    if [[ -z "${RABBITMQ_HOST:-}" ]]; then
        return 0
    fi
    log "Probing RabbitMQ at ${RABBITMQ_HOST}:${RABBITMQ_PORT:-5672} ..."
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
        if [[ $retries -ge 15 ]]; then
            log "WARNING: RabbitMQ not reachable yet — API will still start; OTP dispatch may be delayed."
            return 0
        fi
        sleep 2
    done
    log "RabbitMQ is ready."
}

run_migrations() {
    log "Running makemigrations ..."
    python manage.py makemigrations --noinput
    log "Running migrate ..."
    python manage.py migrate --noinput
    log "Migrations complete."
}

collect_static() {
    log "Collecting static files ..."
    python manage.py collectstatic --noinput --clear || log "  collectstatic skipped (no static configured?)"
}

start_server() {
    local bind="${API_BIND:-0.0.0.0:8000}"
    log "Starting Django dev server on ${bind}"

    # Dev (current): single-process, auto-reload, helpful tracebacks.
    exec python manage.py runserver "${bind}"

    # Prod (uncomment when ready, drop the runserver line above):
    # exec gunicorn core.wsgi:application \
    #     --bind "${bind}" \
    #     --workers "${GUNICORN_WORKERS:-4}" \
    #     --threads "${GUNICORN_THREADS:-2}" \
    #     --worker-class gthread \
    #     --timeout "${GUNICORN_TIMEOUT:-120}" \
    #     --graceful-timeout 30 \
    #     --keep-alive 5 \
    #     --max-requests 1000 \
    #     --max-requests-jitter 100 \
    #     --log-level "${GUNICORN_LOG_LEVEL:-info}" \
    #     --access-logfile "-" \
    #     --error-logfile "-" \
    #     --forwarded-allow-ips "*"
}

main() {
    wait_for_postgres
    wait_for_rabbitmq
    run_migrations
    collect_static
    start_server
}

main "$@"
