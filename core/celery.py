import os

from celery import Celery
from kombu import Queue


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.conf.task_queues = (
    Queue("default"),
    Queue("otp"),
    Queue("notifications"),
    Queue("media"),
)
app.conf.task_default_queue = "default"

# Route OTP / notification work to dedicated queues so a slow SMTP server
# cannot back-pressure the rest of the system.
app.conf.task_routes = {
    "accounts.tasks.send_otp_email": {"queue": "otp"},
    "accounts.tasks.send_otp_sms": {"queue": "otp"},
    "accounts.tasks.send_otp_message": {"queue": "otp"},
    "accounts.tasks.send_welcome_email": {"queue": "notifications"},
    "accounts.tasks.send_user_push_notification": {"queue": "notifications"},
    "accounts.tasks.cleanup_old_profile_image": {"queue": "media"},
    # Image decode/resize is CPU-bound — keep it off the queues that carry
    # latency-sensitive OTP and notification work.
    "accounts.tasks.process_profile_image": {"queue": "media"},
    "accounts.tasks.purge_expired_otps": {"queue": "default"},
}

app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
app.conf.worker_prefetch_multiplier = 1
app.conf.broker_connection_retry_on_startup = True
app.conf.result_expires = 3600

app.autodiscover_tasks()

