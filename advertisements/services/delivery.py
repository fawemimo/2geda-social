from __future__ import annotations

import logging
import random
from datetime import date

from django.db.models import Q
from django.utils import timezone

from advertisements.models import Advertisement, AdPlacement
from utils.enum import AdAudienceGender, AdStatus

logger = logging.getLogger(__name__)


class AdDeliveryService:

    @staticmethod
    def eligible_placements(*, mode: str, now=None):
        """Placements whose advert is live in `mode` right now.

        Hits `ad_serving_window_idx` and `ad_placement_mode_idx`; caps and
        targeting are applied afterwards in Python because they depend on the
        viewer.
        """
        now = now or timezone.now()
        return (
            AdPlacement.objects.filter(
                mode=mode,
                is_deleted=False,
                advertisement__is_deleted=False,
                advertisement__status=AdStatus.RUNNING.value,
                advertisement__starts_at__lte=now,
                advertisement__ends_at__gt=now,
            )
            .select_related("advertisement")
            .prefetch_related("advertisement__creatives__media")
        )

    @staticmethod
    def _matches_targeting(advert: Advertisement, viewer) -> bool:
        """Empty targeting means "everyone" — never exclude on missing data."""
        if viewer is None or not getattr(viewer, "is_authenticated", False):
            # Anonymous viewers only see untargeted adverts.
            return not (
                advert.target_countries
                or advert.target_cities
                or advert.target_min_age
                or advert.target_max_age
                or advert.target_gender != AdAudienceGender.ALL.value
            )

        profile = getattr(viewer, "profile", None)

        if advert.target_gender != AdAudienceGender.ALL.value:
            gender = (getattr(profile, "gender", "") or "").lower()
            if gender != advert.target_gender:
                return False

        if advert.target_min_age or advert.target_max_age:
            age = AdDeliveryService._age_of(profile)
            if age is None:
                return False
            if advert.target_min_age and age < advert.target_min_age:
                return False
            if advert.target_max_age and age > advert.target_max_age:
                return False

        if advert.target_cities:
            city = (getattr(profile, "current_city", "") or "").strip().lower()
            wanted = {str(c).strip().lower() for c in advert.target_cities}
            if city not in wanted:
                return False

        return True

    @staticmethod
    def _age_of(profile) -> int | None:
        dob = getattr(profile, "date_of_birth", None)
        if not dob:
            return None
        today = timezone.now().date()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @staticmethod
    def _within_caps(advert: Advertisement, viewer, today: date) -> bool:
        if advert.is_exhausted:
            return False

        if advert.daily_impression_cap:
            from advertisements.models import AdDailyMetric

            served = (
                AdDailyMetric.objects.filter(advertisement=advert, date=today)
                .values_list("impressions", flat=True)
                .first()
                or 0
            )
            if served >= advert.daily_impression_cap:
                return False

        if advert.frequency_cap_per_user and viewer is not None and getattr(
            viewer, "is_authenticated", False
        ):
            from advertisements.models import AdEvent
            from utils.enum import AdEventType

            seen = AdEvent.objects.filter(
                advertisement=advert,
                user=viewer,
                event_type=AdEventType.IMPRESSION.value,
                created_at__date=today,
            ).count()
            if seen >= advert.frequency_cap_per_user:
                return False

        return True

    @staticmethod
    def select(
        *,
        mode: str,
        viewer=None,
        screen_position: str | None = None,
        limit: int = 1,
    ) -> list[AdPlacement]:
        """Pick up to `limit` placements to fill a slot.

        Selection is priority-weighted rather than strictly highest-priority, so
        a priority-10 advert does not starve everything else — it just wins more
        often.
        """
        now = timezone.now()
        today = timezone.localdate()

        queryset = AdDeliveryService.eligible_placements(mode=mode, now=now)
        if screen_position:
            queryset = queryset.filter(screen_position=screen_position)

        candidates = [
            placement
            for placement in queryset
            if placement.advertisement.creatives.exists()
            and AdDeliveryService._matches_targeting(placement.advertisement, viewer)
            and AdDeliveryService._within_caps(placement.advertisement, viewer, today)
        ]

        if not candidates:
            return []

        chosen: list[AdPlacement] = []
        pool = list(candidates)
        for _ in range(min(limit, len(pool))):
            weights = [max(1, p.advertisement.priority) for p in pool]
            pick = random.choices(pool, weights=weights, k=1)[0]
            chosen.append(pick)
            pool.remove(pick)

        return chosen
