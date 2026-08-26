"""Advertisement authoring, moderation and lifecycle transitions."""
from __future__ import annotations

import logging
from typing import Any, Iterable

from django.db import transaction
from django.utils import timezone

from accounts.services.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from advertisements.models import AdCreative, Advertisement, AdPlacement
from utils.enum import AdStatus

logger = logging.getLogger(__name__)

#: Transitions a human may request. Celery owns APPROVED->RUNNING->COMPLETED.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    AdStatus.DRAFT.value: {AdStatus.PENDING_REVIEW.value, AdStatus.CANCELLED.value},
    AdStatus.PENDING_REVIEW.value: {
        AdStatus.APPROVED.value,
        AdStatus.REJECTED.value,
        AdStatus.CANCELLED.value,
    },
    AdStatus.APPROVED.value: {
        AdStatus.RUNNING.value,
        AdStatus.PAUSED.value,
        AdStatus.CANCELLED.value,
    },
    AdStatus.RUNNING.value: {
        AdStatus.PAUSED.value,
        AdStatus.COMPLETED.value,
        AdStatus.CANCELLED.value,
    },
    # COMPLETED is reachable from PAUSED: an advert paused for budget or by
    # its owner must still close out when its flight window ends, otherwise the
    # expiry sweep can never retire it.
    AdStatus.PAUSED.value: {
        AdStatus.RUNNING.value,
        AdStatus.COMPLETED.value,
        AdStatus.CANCELLED.value,
    },
    AdStatus.REJECTED.value: {AdStatus.DRAFT.value},
    AdStatus.COMPLETED.value: set(),
    AdStatus.CANCELLED.value: set(),
}

#: Fields an advertiser may not edit once the advert has been reviewed.
LOCKED_AFTER_REVIEW = {"starts_at", "ends_at", "destination_url"}

EDITABLE_STATUSES = {AdStatus.DRAFT.value, AdStatus.REJECTED.value}


class AdvertisementService:

    # ---- authoring ---------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create(*, advertiser, validated_data: dict[str, Any]) -> Advertisement:
        data = dict(validated_data)
        media_ids = data.pop("media_ids", []) or []
        placements = data.pop("placements", []) or []

        AdvertisementService._validate_window(
            data.get("starts_at"), data.get("ends_at")
        )

        advert = Advertisement.objects.create(
            advertiser=advertiser,
            status=AdStatus.DRAFT.value,
            **data,
        )

        AdvertisementService._replace_placements(advert, placements)

        if media_ids:
            from advertisements.tasks import attach_ad_creatives

            media_id_strs = [str(m) for m in media_ids]
            transaction.on_commit(
                lambda: attach_ad_creatives.delay(str(advert.id), media_id_strs)
            )

        logger.info("Advertisement %s created by %s", advert.id, advertiser.pk)
        return advert

    @staticmethod
    @transaction.atomic
    def update(*, advert: Advertisement, validated_data: dict[str, Any]) -> Advertisement:
        if advert.status not in EDITABLE_STATUSES:
            locked = LOCKED_AFTER_REVIEW & set(validated_data)
            if locked:
                raise ConflictError(
                    f"Cannot change {', '.join(sorted(locked))} once an advert "
                    f"has been reviewed. Current status: {advert.status}.",
                    code="advert_locked",
                )

        data = dict(validated_data)
        media_ids = data.pop("media_ids", None)
        placements = data.pop("placements", None)

        starts_at = data.get("starts_at", advert.starts_at)
        ends_at = data.get("ends_at", advert.ends_at)
        AdvertisementService._validate_window(starts_at, ends_at)

        for field, value in data.items():
            setattr(advert, field, value)
        advert.save()

        if placements is not None:
            AdvertisementService._replace_placements(advert, placements)

        if media_ids is not None:
            from advertisements.tasks import attach_ad_creatives

            advert.creatives.all().delete()
            media_id_strs = [str(m) for m in media_ids]
            transaction.on_commit(
                lambda: attach_ad_creatives.delay(str(advert.id), media_id_strs)
            )

        return advert

    @staticmethod
    def delete(*, advert: Advertisement) -> None:
        advert.delete()  # soft delete
        logger.info("Advertisement %s deleted", advert.id)

    # ---- lifecycle ---------------------------------------------------------

    @staticmethod
    def _transition(advert: Advertisement, target: str, **extra) -> Advertisement:
        allowed = ALLOWED_TRANSITIONS.get(advert.status, set())
        if target not in allowed:
            raise ConflictError(
                f"Cannot move an advert from {advert.status} to {target}.",
                code="invalid_ad_transition",
            )
        advert.status = target
        fields = ["status", "updated_at"]
        for key, value in extra.items():
            setattr(advert, key, value)
            fields.append(key)
        advert.save(update_fields=fields)
        logger.info("Advertisement %s -> %s", advert.id, target)
        return advert

    @staticmethod
    @transaction.atomic
    def submit_for_review(*, advert: Advertisement) -> Advertisement:
        if not advert.creatives.exists():
            raise ValidationError(
                "Add at least one image before submitting for review.",
                code="advert_needs_creative",
            )
        if not advert.placements.exists():
            raise ValidationError(
                "Choose at least one advert mode before submitting for review.",
                code="advert_needs_placement",
            )
        if advert.ends_at <= timezone.now():
            raise ValidationError(
                "The flight window has already ended.", code="advert_window_past",
            )
        return AdvertisementService._transition(advert, AdStatus.PENDING_REVIEW.value)

    @staticmethod
    @transaction.atomic
    def approve(*, advert: Advertisement, reviewer) -> Advertisement:
        advert = AdvertisementService._transition(
            advert,
            AdStatus.APPROVED.value,
            reviewed_by=reviewer,
            reviewed_at=timezone.now(),
            rejection_reason="",
        )
        # Already inside its window? Go live now rather than waiting for the
        # next beat tick.
        if advert.starts_at <= timezone.now() < advert.ends_at:
            AdvertisementService.activate(advert=advert)
        return advert

    @staticmethod
    @transaction.atomic
    def reject(*, advert: Advertisement, reviewer, reason: str) -> Advertisement:
        if not reason.strip():
            raise ValidationError(
                "A rejection reason is required.", code="rejection_reason_required",
            )
        return AdvertisementService._transition(
            advert,
            AdStatus.REJECTED.value,
            reviewed_by=reviewer,
            reviewed_at=timezone.now(),
            rejection_reason=reason.strip(),
        )

    @staticmethod
    def activate(*, advert: Advertisement) -> Advertisement:
        """APPROVED/PAUSED -> RUNNING. Called by the beat sweep and on approval."""
        return AdvertisementService._transition(
            advert, AdStatus.RUNNING.value, activated_at=timezone.now(),
        )

    @staticmethod
    def pause(*, advert: Advertisement) -> Advertisement:
        return AdvertisementService._transition(advert, AdStatus.PAUSED.value)

    @staticmethod
    def resume(*, advert: Advertisement) -> Advertisement:
        if advert.ends_at <= timezone.now():
            raise ConflictError(
                "The flight window has ended; this advert cannot resume.",
                code="advert_window_past",
            )
        return AdvertisementService._transition(advert, AdStatus.RUNNING.value)

    @staticmethod
    def complete(*, advert: Advertisement) -> Advertisement:
        return AdvertisementService._transition(
            advert, AdStatus.COMPLETED.value, completed_at=timezone.now(),
        )

    @staticmethod
    def cancel(*, advert: Advertisement) -> Advertisement:
        return AdvertisementService._transition(advert, AdStatus.CANCELLED.value)

    
    @staticmethod
    def _validate_window(starts_at, ends_at) -> None:
        if not starts_at or not ends_at:
            raise ValidationError(
                "Both starts_at and ends_at are required.", code="advert_window_required",
            )
        if ends_at <= starts_at:
            raise ValidationError(
                "ends_at must be after starts_at.", code="advert_window_invalid",
            )

    @staticmethod
    def _replace_placements(
        advert: Advertisement, placements: Iterable[dict[str, Any]]
    ) -> None:
        advert.placements.all().delete()
        rows = [
            AdPlacement(
                advertisement=advert,
                mode=item["mode"],
                screen_position=item.get("screen_position")
                or AdPlacement._meta.get_field("screen_position").default,
                display_seconds=item.get("display_seconds", 0),
                is_skippable=item.get("is_skippable", True),
                skip_after_seconds=item.get("skip_after_seconds", 5),
                show_every_n=item.get("show_every_n", 1),
            )
            for item in placements
        ]
        if rows:
            AdPlacement.objects.bulk_create(rows, ignore_conflicts=True)

    @staticmethod
    def get_for_advertiser(*, advert_id: str, user) -> Advertisement:
        advert = Advertisement.objects.filter(
            pk=advert_id, is_deleted=False
        ).first()
        if advert is None:
            raise NotFoundError("Advertisement not found.", code="advert_not_found")
        if advert.advertiser_id != user.pk and not user.is_staff:
            raise PermissionDeniedError(
                "You do not own this advertisement.", code="advert_forbidden",
            )
        return advert
