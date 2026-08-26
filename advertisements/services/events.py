
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from advertisements.models import AdDailyMetric, AdEvent, Advertisement, AdPlacement
from utils.enum import AdEventType, AdPricingModel

logger = logging.getLogger(__name__)

#: Events that also move money and denormalised counters.
_COUNTER_FIELD = {
    AdEventType.IMPRESSION.value: "impressions_count",
    AdEventType.CLICK.value: "clicks_count",
    AdEventType.CONVERSION.value: "conversions_count",
}
_METRIC_FIELD = {
    AdEventType.IMPRESSION.value: "impressions",
    AdEventType.CLICK.value: "clicks",
    AdEventType.CONVERSION.value: "conversions",
}


class AdEventService:

    @staticmethod
    def _billable_amount(advert: Advertisement, event_type: str) -> Decimal:
        """What this single event costs the advertiser."""
        bid = Decimal(advert.bid_amount or 0)
        if not bid:
            return Decimal("0")
        if (
            advert.pricing_model == AdPricingModel.CPM.value
            and event_type == AdEventType.IMPRESSION.value
        ):
            return bid / Decimal("1000")
        if (
            advert.pricing_model == AdPricingModel.CPC.value
            and event_type == AdEventType.CLICK.value
        ):
            return bid
        if (
            advert.pricing_model == AdPricingModel.CPA.value
            and event_type == AdEventType.CONVERSION.value
        ):
            return bid
        return Decimal("0")

    @staticmethod
    @transaction.atomic
    def record(
        *,
        advertisement_id: str,
        event_type: str,
        user=None,
        placement_id: str | None = None,
        device_id: str = "",
        dedupe_key: str = "",
        metadata: dict | None = None,
    ) -> AdEvent | None:
        """Log one delivery event.

        Returns None when the event is a duplicate — beacons get retried by
        flaky mobile networks, and a replayed impression must not be billed or
        counted twice.
        """
        advert = (
            Advertisement.objects.select_for_update()
            .filter(pk=advertisement_id, is_deleted=False)
            .first()
        )
        if advert is None:
            logger.warning("Ad event for unknown advertisement %s", advertisement_id)
            return None

        placement = None
        if placement_id:
            placement = AdPlacement.objects.filter(
                pk=placement_id, advertisement=advert
            ).first()

        try:
            with transaction.atomic():
                event = AdEvent.objects.create(
                    advertisement=advert,
                    placement=placement,
                    user=user if user and user.is_authenticated else None,
                    event_type=event_type,
                    device_id=device_id[:128],
                    dedupe_key=dedupe_key[:64],
                    metadata=metadata or {},
                )
        except IntegrityError:
            logger.info(
                "Duplicate ad event ignored (advert=%s key=%s)",
                advertisement_id, dedupe_key,
            )
            return None

        AdEventService._apply_counters(advert, event_type)
        return event

    @staticmethod
    def _apply_counters(advert: Advertisement, event_type: str) -> None:
        counter = _COUNTER_FIELD.get(event_type)
        spend = AdEventService._billable_amount(advert, event_type)

        updates = {}
        if counter:
            updates[counter] = F(counter) + 1
        if spend:
            updates["amount_spent"] = F("amount_spent") + spend
        if updates:
            Advertisement.objects.filter(pk=advert.pk).update(**updates)

        metric_field = _METRIC_FIELD.get(event_type)
        if metric_field or spend:
            today = timezone.localdate()
            AdDailyMetric.objects.get_or_create(
                advertisement=advert, date=today,
            )
            metric_updates = {}
            if metric_field:
                metric_updates[metric_field] = F(metric_field) + 1
            if spend:
                metric_updates["spend"] = F("spend") + spend
            AdDailyMetric.objects.filter(
                advertisement=advert, date=today
            ).update(**metric_updates)

    @staticmethod
    def budget_exhausted(advert: Advertisement) -> bool:
        budget = Decimal(advert.budget_amount or 0)
        return bool(budget) and Decimal(advert.amount_spent or 0) >= budget
