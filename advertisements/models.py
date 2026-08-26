from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from utils.enum import (
    AdAudienceGender,
    AdCallToAction,
    AdEventType,
    AdMode,
    AdObjective,
    AdPricingModel,
    AdScreenPosition,
    AdStatus,
)
from utils.models import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin


class Advertisement(BaseModel):
    """A campaign flight: creatives + schedule + placements + targeting."""

    advertiser = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="advertisements",
        db_index=True,
    )

    # ---- Content -----------------------------------------------------------
    title = models.CharField(max_length=140)
    # Captions are optional by design — an advert may be image-only.
    caption = models.TextField(max_length=1000, blank=True)
    call_to_action = models.CharField(
        max_length=20,
        choices=AdCallToAction.choices(),
        default=AdCallToAction.LEARN_MORE.value,
    )
    destination_url = models.URLField(blank=True)

    # ---- Lifecycle ---------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=AdStatus.choices(),
        default=AdStatus.DRAFT.value,
        db_index=True,
    )
    objective = models.CharField(
        max_length=20,
        choices=AdObjective.choices(),
        default=AdObjective.BRAND_AWARENESS.value,
    )

    # ---- Flight window -----------------------------------------------------
    # Celery flips status at these boundaries; both are indexed because the
    # beat sweeps range-query them every minute.
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # ---- Delivery ----------------------------------------------------------
    priority = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        help_text=_("1-10. Higher wins when several adverts fit one slot."),
    )
    daily_impression_cap = models.PositiveIntegerField(
        default=0, help_text=_("0 = uncapped."),
    )
    total_impression_cap = models.PositiveIntegerField(
        default=0, help_text=_("0 = uncapped."),
    )
    frequency_cap_per_user = models.PositiveSmallIntegerField(
        default=0,
        help_text=_("Max impressions per user per day. 0 = uncapped."),
    )

    # ---- Targeting ---------------------------------------------------------
    target_gender = models.CharField(
        max_length=10,
        choices=AdAudienceGender.choices(),
        default=AdAudienceGender.ALL.value,
    )
    target_min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    target_max_age = models.PositiveSmallIntegerField(null=True, blank=True)
    target_countries = models.JSONField(
        default=list, blank=True, help_text=_("ISO country codes; empty = everywhere."),
    )
    target_cities = models.JSONField(default=list, blank=True)
    target_interests = models.JSONField(default=list, blank=True)

    # ---- Commercials -------------------------------------------------------
    pricing_model = models.CharField(
        max_length=10,
        choices=AdPricingModel.choices(),
        default=AdPricingModel.CPM.value,
    )
    currency = models.CharField(max_length=3, default="NGN")
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ---- Moderation --------------------------------------------------------
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_advertisements",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # ---- Denormalised counters --------------------------------------------
    impressions_count = models.PositiveBigIntegerField(default=0)
    clicks_count = models.PositiveBigIntegerField(default=0)
    conversions_count = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "advertisements_advertisement"
        ordering = ["-created_at"]
        indexes = [
            # The serving query: live adverts inside their flight window.
            models.Index(
                fields=["status", "starts_at", "ends_at"],
                name="ad_serving_window_idx",
            ),
            models.Index(
                fields=["advertiser", "-created_at"], name="ad_advertiser_idx",
            ),
            models.Index(fields=["status", "-priority"], name="ad_status_priority_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="ad_ends_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.status})"

    # ---- Derived state -----------------------------------------------------

    @property
    def is_live(self) -> bool:
        now = timezone.now()
        return (
            self.status == AdStatus.RUNNING.value
            and not self.is_deleted
            and self.starts_at <= now < self.ends_at
        )

    @property
    def click_through_rate(self) -> float:
        if not self.impressions_count:
            return 0.0
        return round((self.clicks_count / self.impressions_count) * 100, 4)

    @property
    def is_exhausted(self) -> bool:
        """Total impression cap reached."""
        return bool(
            self.total_impression_cap
            and self.impressions_count >= self.total_impression_cap
        )


class AdCreative(BaseModel):
    advertisement = models.ForeignKey(
        Advertisement, on_delete=models.CASCADE, related_name="creatives",
    )
    media = models.ForeignKey(
        "medias.Media", on_delete=models.CASCADE, related_name="ad_creatives",
    )
    headline = models.CharField(max_length=140, blank=True)
    # Per-creative caption, also optional.
    caption = models.TextField(max_length=500, blank=True)
    alt_text = models.CharField(max_length=250, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "advertisements_ad_creative"
        unique_together = [("advertisement", "media")]
        ordering = ["position"]
        indexes = [
            models.Index(
                fields=["advertisement", "position"], name="ad_creative_order_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Creative {self.position} of {self.advertisement_id}"


class AdPlacement(BaseModel):
    advertisement = models.ForeignKey(
        Advertisement, on_delete=models.CASCADE, related_name="placements",
    )
    mode = models.CharField(max_length=30, choices=AdMode.choices(), db_index=True)
    screen_position = models.CharField(
        max_length=20,
        choices=AdScreenPosition.choices(),
        default=AdScreenPosition.INLINE.value,
    )
    #: How long the creative stays on screen; 0 = until dismissed.
    display_seconds = models.PositiveSmallIntegerField(default=0)
    is_skippable = models.BooleanField(default=True)
    skip_after_seconds = models.PositiveSmallIntegerField(default=5)
    #: Show once every N eligible opportunities (1 = every time).
    show_every_n = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "advertisements_ad_placement"
        unique_together = [("advertisement", "mode")]
        ordering = ["mode"]
        indexes = [
            models.Index(fields=["mode", "screen_position"], name="ad_placement_mode_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.mode} @ {self.screen_position}"


class AdEvent(UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only delivery log. High volume: no soft-delete, no updates."""

    advertisement = models.ForeignKey(
        Advertisement, on_delete=models.CASCADE, related_name="events",
    )
    placement = models.ForeignKey(
        AdPlacement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ad_events",
    )
    event_type = models.CharField(
        max_length=25, choices=AdEventType.choices(), db_index=True,
    )
    #: Opaque client identifier so anonymous frequency capping still works.
    device_id = models.CharField(max_length=128, blank=True, db_index=True)
    #: Client-supplied idempotency key — replayed beacons must not double-count.
    dedupe_key = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "advertisements_ad_event"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["advertisement", "event_type", "-created_at"],
                name="ad_event_lookup_idx",
            ),
            models.Index(
                fields=["advertisement", "user", "-created_at"],
                name="ad_event_user_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["advertisement", "dedupe_key"],
                condition=models.Q(dedupe_key__gt=""),
                name="ad_event_dedupe_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} on {self.advertisement_id}"


class AdDailyMetric(UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-day rollup. Backs the daily impression cap without scanning AdEvent."""

    advertisement = models.ForeignKey(
        Advertisement, on_delete=models.CASCADE, related_name="daily_metrics",
    )
    date = models.DateField(db_index=True)
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "advertisements_ad_daily_metric"
        unique_together = [("advertisement", "date")]
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["advertisement", "-date"], name="ad_metric_ad_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.advertisement_id} {self.date}"

    @property
    def click_through_rate(self) -> float:
        if not self.impressions:
            return 0.0
        return round((self.clicks / self.impressions) * 100, 4)
