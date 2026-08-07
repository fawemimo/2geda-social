"""Ensure the Celery app is loaded when Django starts.

Without this import, @shared_task binds to Celery's *default* app instead of
the one in core/celery.py — so task_routes/task_queues are never applied and
every .delay() publishes to the default "celery" queue that no worker consumes.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
