"""Short-lived blob staging for hand-off between the web tier and Celery.

Celery messages should stay small: the broker fans every message out to workers
and holds it in memory, so putting a multi-megabyte (base64-inflated) payload on
the queue costs throughput for every consumer, not just the one that needs it.

Instead the web tier parks the raw bytes in Redis under a TTL and enqueues only
the key. The worker claims the blob, and the TTL guarantees the bytes are
reclaimed even if the task is lost.
"""

from __future__ import annotations

import logging
import uuid

from django.core.cache import cache

logger = logging.getLogger(__name__)

STAGING_PREFIX = "staging:blob:"

# Comfortably longer than a retrying upload task will take, short enough that
# abandoned blobs do not accumulate.
STAGING_TTL_SECONDS = 60 * 30


def stage_blob(raw: bytes, *, ttl: int = STAGING_TTL_SECONDS) -> str:
    """Park bytes and return the claim key."""
    key = f"{STAGING_PREFIX}{uuid.uuid4()}"
    cache.set(key, raw, timeout=ttl)
    return key


def claim_blob(key: str) -> bytes | None:
    """Fetch and delete a staged blob. Returns None if it expired or was taken.

    Deleting on read keeps a retrying task from processing the same bytes twice
    after it has already succeeded past this point.
    """
    raw = cache.get(key)
    if raw is None:
        return None
    cache.delete(key)
    return raw


def peek_blob(key: str) -> bytes | None:
    """Fetch without consuming — used where the caller retries on failure."""
    return cache.get(key)


def drop_blob(key: str) -> None:
    cache.delete(key)
