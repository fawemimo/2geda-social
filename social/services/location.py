from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from social.models import SocialLocation
from utils.enum import LocationStatus

logger = logging.getLogger(__name__)

# Geocoded addresses barely change, so cache the cell for a long time.
CACHE_TTL = 60 * 60 * 24 * 30
CACHE_PREFIX = "social:geo:"

ADDRESS_FIELDS = ("formatted_address", "city", "state", "country")


class SocialLocationService:

    @staticmethod
    def cache_key(cell_key: str) -> str:
        return f"{CACHE_PREFIX}{cell_key}"

    # Builds the snapshot row and queues resolution; returns None without coordinates.
    @staticmethod
    def capture(*, latitude, longitude, label: str = "") -> SocialLocation | None:
        if latitude is None or longitude is None:
            return None
        try:
            lat = Decimal(str(latitude))
            lng = Decimal(str(longitude))
        except (InvalidOperation, TypeError, ValueError):
            logger.warning("Discarding unusable coordinates for a social object.")
            return None
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            logger.warning("Discarding out-of-range coordinates for a social object.")
            return None

        cell_key = SocialLocation.build_cell_key(lat, lng)
        location = SocialLocation.objects.create(
            latitude=lat, longitude=lng, cell_key=cell_key, label=label or "",
        )

        # Same coordinates as something already resolved: copy it, skip Google.
        if SocialLocationService.apply_known_address(location):
            return location

        from social.tasks import resolve_social_location

        transaction.on_commit(
            lambda: resolve_social_location.delay(str(location.id))
        )
        return location

    # Fills the address from Redis, then from a sibling row at the same cell.
    @staticmethod
    def apply_known_address(location: SocialLocation) -> bool:
        address = SocialLocationService.cached_address(location.cell_key)
        if address is None:
            address = SocialLocationService.address_from_siblings(location)
        if address is None:
            return False
        SocialLocationService.apply_address(location, address)
        return True

    @staticmethod
    def cached_address(cell_key: str) -> dict | None:
        try:
            return cache.get(SocialLocationService.cache_key(cell_key))
        except Exception:
            return None

    @staticmethod
    def cache_address(cell_key: str, address: dict) -> None:
        try:
            cache.set(SocialLocationService.cache_key(cell_key), address, CACHE_TTL)
        except Exception:
            logger.warning("Could not cache a geocoded address; continuing.")

    # Reuses an address already stored against the same cell.
    @staticmethod
    def address_from_siblings(location: SocialLocation) -> dict | None:
        sibling = (
            SocialLocation.objects.filter(
                cell_key=location.cell_key, status=LocationStatus.RESOLVED.value,
            )
            .exclude(pk=location.pk)
            .values(*ADDRESS_FIELDS)
            .first()
        )
        if sibling is None:
            return None
        SocialLocationService.cache_address(location.cell_key, sibling)
        return sibling

    @staticmethod
    def apply_address(location: SocialLocation, address: dict) -> SocialLocation:
        for field in ADDRESS_FIELDS:
            setattr(location, field, address.get(field) or "")
        location.status = LocationStatus.RESOLVED.value
        location.resolved_at = timezone.now()
        location.save(update_fields=[*ADDRESS_FIELDS, "status", "resolved_at"])
        return location

    @staticmethod
    def mark_failed(location: SocialLocation) -> SocialLocation:
        location.status = LocationStatus.FAILED.value
        location.save(update_fields=["status"])
        return location
