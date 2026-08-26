from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    name="advertisements.tasks.attach_ad_creatives",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def attach_ad_creatives(advertisement_id: str, media_ids: list[str]) -> dict:
    
    from advertisements.models import AdCreative, Advertisement
    from medias.models import Media

    if not media_ids:
        return {"attached": 0, "skipped": []}

    advert = (
        Advertisement.objects.filter(pk=advertisement_id)
        .only("pk", "advertiser_id")
        .first()
    )
    if advert is None:
        logger.warning("Advertisement %s not found; nothing to attach", advertisement_id)
        return {"attached": 0, "skipped": [str(m) for m in media_ids]}

    owned = {
        str(pk): pk
        for pk in Media.objects.filter(
            pk__in=media_ids, owner_id=advert.advertiser_id, is_deleted=False
        ).values_list("pk", flat=True)
    }

    rows, skipped = [], []
    for position, media_id in enumerate(media_ids):
        key = str(media_id)
        if key not in owned:
            skipped.append(key)
            continue
        rows.append(
            AdCreative(advertisement_id=advert.pk, media_id=owned[key], position=position)
        )

    if skipped:
        logger.warning(
            "Advertisement %s: %d media skipped (missing, deleted, or not owned)",
            advertisement_id, len(skipped),
        )

    if rows:
        with transaction.atomic():
            AdCreative.objects.bulk_create(rows, ignore_conflicts=True)

    logger.info("Advertisement %s: attached %d creative(s)", advertisement_id, len(rows))
    return {"attached": len(rows), "skipped": skipped}


@shared_task(
    name="advertisements.tasks.activate_due_advertisements",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def activate_due_advertisements() -> dict:
    """APPROVED adverts whose start time has arrived go live.

    Runs every minute from beat. Each advert is transitioned in its own
    transaction so one bad row cannot stall the whole sweep.
    """
    from advertisements.models import Advertisement
    from advertisements.services import AdvertisementService
    from utils.enum import AdStatus

    now = timezone.now()
    due_ids = list(
        Advertisement.objects.filter(
            status=AdStatus.APPROVED.value,
            is_deleted=False,
            starts_at__lte=now,
            ends_at__gt=now,
        ).values_list("pk", flat=True)[:500]
    )

    activated = 0
    for advert_id in due_ids:
        try:
            with transaction.atomic():
                advert = (
                    Advertisement.objects.select_for_update(skip_locked=True)
                    .filter(pk=advert_id, status=AdStatus.APPROVED.value)
                    .first()
                )
                if advert is None:
                    continue
                AdvertisementService.activate(advert=advert)
                activated += 1
        except Exception:
            logger.exception("Failed to activate advertisement %s", advert_id)

    if activated:
        logger.info("Activated %d advertisement(s)", activated)
    return {"activated": activated}


@shared_task(
    name="advertisements.tasks.complete_expired_advertisements",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def complete_expired_advertisements() -> dict:
    """RUNNING or PAUSED adverts past their end time are closed out."""
    from advertisements.models import Advertisement
    from advertisements.services import AdvertisementService
    from utils.enum import AdStatus

    now = timezone.now()
    expired_ids = list(
        Advertisement.objects.filter(
            status__in=[AdStatus.RUNNING.value, AdStatus.PAUSED.value],
            is_deleted=False,
            ends_at__lte=now,
        ).values_list("pk", flat=True)[:500]
    )

    completed = 0
    for advert_id in expired_ids:
        try:
            with transaction.atomic():
                advert = (
                    Advertisement.objects.select_for_update(skip_locked=True)
                    .filter(
                        pk=advert_id,
                        status__in=[AdStatus.RUNNING.value, AdStatus.PAUSED.value],
                    )
                    .first()
                )
                if advert is None:
                    continue
                AdvertisementService.complete(advert=advert)
                completed += 1
        except Exception:
            logger.exception("Failed to complete advertisement %s", advert_id)

    if completed:
        logger.info("Completed %d expired advertisement(s)", completed)
    return {"completed": completed}


@shared_task(
    name="advertisements.tasks.pause_exhausted_advertisements",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def pause_exhausted_advertisements() -> dict:
    """Stop delivery once the total impression cap or budget is spent.

    Without this an advert keeps serving after the advertiser has been fully
    billed — the delivery query filters on status, not on spend.
    """
    from advertisements.models import Advertisement
    from advertisements.services import AdEventService, AdvertisementService
    from utils.enum import AdStatus

    running = Advertisement.objects.filter(
        status=AdStatus.RUNNING.value, is_deleted=False,
    ).only(
        "pk", "status", "impressions_count", "total_impression_cap",
        "budget_amount", "amount_spent",
    )

    paused = 0
    for advert in running.iterator():
        if not (advert.is_exhausted or AdEventService.budget_exhausted(advert)):
            continue
        try:
            AdvertisementService.pause(advert=advert)
            paused += 1
            logger.info("Paused advertisement %s (cap or budget reached)", advert.pk)
        except Exception:
            logger.exception("Failed to pause advertisement %s", advert.pk)

    return {"paused": paused}


@shared_task(
    name="advertisements.tasks.record_ad_event",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def record_ad_event(
    *,
    advertisement_id: str,
    event_type: str,
    user_id: str | None = None,
    placement_id: str | None = None,
    device_id: str = "",
    dedupe_key: str = "",
    metadata: dict | None = None,
) -> dict:
    """Persist a delivery beacon off the request path."""
    from accounts.models import User
    from advertisements.services import AdEventService

    user = User.objects.filter(pk=user_id).first() if user_id else None
    event = AdEventService.record(
        advertisement_id=advertisement_id,
        event_type=event_type,
        user=user,
        placement_id=placement_id,
        device_id=device_id,
        dedupe_key=dedupe_key,
        metadata=metadata,
    )
    return {"recorded": event is not None}
