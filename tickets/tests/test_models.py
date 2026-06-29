from __future__ import annotations

import pytest
from django.utils import timezone

from tickets.models import (
    Event,
    EventCategory,
    Payout,
    PriceTier,
    SellerProfile,
    Ticket,
    TicketPurchase,
)
from utils.enum import (
    EventStatus,
    PaymentStatus,
    PriceTag,
    SellerStatus,
    TicketStatus,
)

pytestmark = pytest.mark.django_db


class TestEventCategoryModel:
    def test_create(self, event_category):
        assert event_category.name == "Music Concert"
        assert event_category.is_active is True
        assert str(event_category) == "Music Concert"


class TestSellerProfileModel:
    def test_create(self, seller_profile):
        assert seller_profile.business_name == "Test Seller Inc."
        assert seller_profile.status == SellerStatus.APPROVED.value

    def test_approve(self, pending_seller, admin_user):
        pending_seller.approve(admin_user)
        assert pending_seller.status == SellerStatus.APPROVED.value
        assert pending_seller.reviewed_by == admin_user

    def test_reject(self, pending_seller, admin_user):
        pending_seller.reject(admin_user, "Incomplete documents")
        assert pending_seller.status == SellerStatus.REJECTED.value
        assert pending_seller.rejection_reason == "Incomplete documents"

    def test_suspend(self, seller_profile):
        seller_profile.suspend()
        assert seller_profile.status == SellerStatus.SUSPENDED.value

    def test_str(self, seller_profile):
        assert "Test Seller Inc." in str(seller_profile)


class TestEventModel:
    def test_create_draft(self, draft_event):
        assert draft_event.status == EventStatus.DRAFT.value
        assert draft_event.is_upcoming is True
        assert draft_event.is_live is False

    def test_price_tiers_created(self, draft_event):
        tiers = draft_event.price_tiers.all()
        assert tiers.count() == 1
        assert tiers.first().price_tag == PriceTag.GENERAL.value

    def test_published_event_categorized(self, published_event):
        tiers = published_event.price_tiers.all()
        assert tiers.count() == 2
        tags = [t.price_tag for t in tiers]
        assert PriceTag.VIP.value in tags
        assert PriceTag.REGULAR.value in tags

    def test_str(self, draft_event):
        assert "Test Concert" in str(draft_event)

    def test_categorized_pricing_mode(self, published_event):
        assert published_event.pricing_mode == "categorized"
        assert published_event.tickets_available == 200

    def test_event_link_unique(self, draft_event, published_event):
        assert draft_event.event_link != published_event.event_link


class TestPriceTierModel:
    def test_available_calculation(self, price_tier):
        assert price_tier.available == price_tier.quantity
        price_tier.quantity_sold = 10
        price_tier.quantity_reserved = 5
        assert price_tier.available == price_tier.quantity - 15

    def test_str(self, price_tier):
        assert price_tier.price_tag.upper() in str(price_tier)


class TestTicketModel:
    def test_create_reserved(self, ticket_purchase):
        tickets = ticket_purchase.tickets.all()
        assert tickets.count() == 2
        for t in tickets:
            assert t.status == TicketStatus.RESERVED.value
            assert t.ticket_code.startswith("TKT-")

    def test_sold_ticket(self, sold_ticket):
        assert sold_ticket.status == TicketStatus.SOLD.value
        assert sold_ticket.purchased_at is not None
        assert sold_ticket.qr_code_data is not None

    def test_str(self, sold_ticket):
        assert sold_ticket.ticket_code in str(sold_ticket)


class TestTicketPurchaseModel:
    def test_create_pending(self, ticket_purchase):
        assert ticket_purchase.payment_status == PaymentStatus.PENDING.value
        assert ticket_purchase.quantity == 2
        assert ticket_purchase.reserved_until is not None

    def test_str(self, ticket_purchase):
        assert ticket_purchase.transaction_ref in str(ticket_purchase)


class TestPayoutModel:
    def test_create(self, payout):
        assert payout.status == PaymentStatus.PENDING.value
        assert payout.payout_ref == "PO-TEST001"

    def test_str(self, payout):
        assert payout.payout_ref in str(payout)
