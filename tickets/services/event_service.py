from django.db import transaction
from django.utils import timezone

from tickets.models import Event, PriceTier, SellerProfile
from tickets.services.exceptions import InvalidEventStatus
from tickets.services.seller_service import SellerService
from utils.enum import EventStatus, PriceTag, PricingMode


class EventService:

    @staticmethod
    def create(seller: SellerProfile, **data) -> Event:
        SellerService.require_approved(seller)

        pricing_mode = data.pop("pricing_mode", PricingMode.FLAT.value)
        price_tiers_data = data.pop("price_tiers", [])

        with transaction.atomic():
            event = Event.objects.create(
                seller=seller,
                pricing_mode=pricing_mode,
                **data,
            )
            if pricing_mode == PricingMode.FLAT.value or not price_tiers_data:
                PriceTier.objects.create(
                    event=event,
                    price_tag=PriceTag.GENERAL.value,
                    price=data.get("price", 0),
                    quantity=data.get("quantity", 0),
                )
            else:
                for tier_data in price_tiers_data:
                    PriceTier.objects.create(event=event, **tier_data)

            event.tickets_available = sum(
                t.quantity for t in event.price_tiers.all()
            )
            event.save(update_fields=["tickets_available"])

        return event

    @staticmethod
    def update(event: Event, seller: SellerProfile, **data) -> Event:
        if event.status not in (EventStatus.DRAFT.value,):
            raise InvalidEventStatus("Can only edit events in draft status.")

        price_tiers_data = data.pop("price_tiers", None)

        with transaction.atomic():
            for attr, value in data.items():
                setattr(event, attr, value)
            event.save()

            if price_tiers_data is not None:
                event.price_tiers.all().delete()
                for tier_data in price_tiers_data:
                    PriceTier.objects.create(event=event, **tier_data)

                event.tickets_available = sum(
                    t.quantity for t in event.price_tiers.all()
                )
                event.save(update_fields=["tickets_available"])

        return event

    @staticmethod
    def publish(event: Event, seller: SellerProfile) -> Event:
        if event.seller_id != seller.id:
            raise InvalidEventStatus("You do not own this event.")
        if event.status != EventStatus.DRAFT.value:
            raise InvalidEventStatus("Event is already published or cancelled.")

        with transaction.atomic():
            event.status = EventStatus.PUBLISHED.value
            event.save(update_fields=["status"])

        return event

    @staticmethod
    def cancel(event: Event, seller: SellerProfile) -> Event:
        if event.seller_id != seller.id:
            raise InvalidEventStatus("You do not own this event.")
        if event.status != EventStatus.PUBLISHED.value:
            raise InvalidEventStatus("Only published events can be cancelled.")

        with transaction.atomic():
            event.status = EventStatus.CANCELLED.value
            event.save(update_fields=["status"])

        return event

    @staticmethod
    def mark_completed(event: Event) -> Event:
        event.status = EventStatus.COMPLETED.value
        event.save(update_fields=["status"])
        return event

    @staticmethod
    def get_public_events():
        now = timezone.now()
        return Event.objects.filter(
            status=EventStatus.PUBLISHED.value,
            is_deleted=False,
            starts_at__gt=now,
            visibility="public",
        ).select_related("seller", "category")

    @staticmethod
    def get_by_link(link: str) -> Event | None:
        return Event.objects.filter(
            event_link=link,
            is_deleted=False,
        ).select_related("seller", "category").first()
