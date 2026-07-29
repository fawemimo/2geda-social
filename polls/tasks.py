from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from polls.enums import PollStatus

logger = logging.getLogger(__name__)


@shared_task(
    name="polls.tasks.close_expired_polls",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def close_expired_polls() -> dict:
    now = timezone.now()

    from polls.models import Poll
    from polls.services.broadcaster import broadcast_poll_event
    from polls.services.poll_service import PollService

    with transaction.atomic():
        expired_qs = Poll.objects.filter(
            ends_at__lte=now,
            status=PollStatus.ACTIVE.value,
            is_deleted=False,
        ).select_for_update(skip_locked=True)

        poll_ids = list(expired_qs.values_list("pk", flat=True))
        total = len(poll_ids)

        if total == 0:
            logger.info("No expired polls to close.")
            return {"closed_count": 0}

        logger.info("Closing %d expired poll(s).", total)

        for poll in expired_qs:
            PollService.close(instance=poll)
            broadcast_poll_event(str(poll.pk), {
                "event": "poll.closed",
                "poll_id": str(poll.pk),
            })

    logger.info("Successfully closed %d expired poll(s).", total)
    return {"closed_count": total}
