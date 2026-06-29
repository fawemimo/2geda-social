from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from tickets.models import Event, PriceTier, SellerProfile, Ticket
from tickets.services.dispute_service import DisputeService
from tickets.services.event_service import EventService
from tickets.services.exceptions import (
    InsufficientTickets,
    InvalidEventStatus,
    SellerNotApproved,
    SellerSuspended,
)
from tickets.services.report_service import ReportService
from tickets.services.seller_service import SellerService
from utils.enum import (
    DisputeStatus,
    EventStatus,
    PriceTag,
    PricingMode,
    SellerStatus,
    TicketStatus,
)

pytestmark = pytest.mark.django_db


class TestSellerService:
    def test_apply_creates_profile(self, user):
        profile = SellerService.apply(
            user=user,
            business_name="New Seller",
            business_email="new@test.com",
        )
        assert profile.business_name == "New Seller"
        assert profile.status == SellerStatus.PENDING.value
        assert profile.user == user

    def test_apply_updates_existing(self, pending_seller):
        profile = SellerService.apply(
            user=pending_seller.user,
            business_name="Updated Name",
        )
        assert profile.id == pending_seller.id
        assert profile.business_name == "Updated Name"

    def test_approve(self, pending_seller, admin_user):
        profile = SellerService.approve(pending_seller, admin_user)
        assert profile.status == SellerStatus.APPROVED.value
        assert profile.reviewed_by == admin_user

    def test_reject(self, pending_seller, admin_user):
        profile = SellerService.reject(pending_seller, admin_user, "Bad docs")
        assert profile.status == SellerStatus.REJECTED.value
        assert profile.rejection_reason == "Bad docs"

    def test_suspend(self, seller_profile):
        profile = SellerService.suspend(seller_profile)
        assert profile.status == SellerStatus.SUSPENDED.value

    def test_get_for_user(self, seller_profile, seller_user):
        profile = SellerService.get_for_user(seller_user)
        assert profile == seller_profile

    def test_require_approved_ok(self, seller_profile):
        assert SellerService.require_approved(seller_profile) == seller_profile

    def test_require_approved_none(self):
        with pytest.raises(SellerNotApproved):
            SellerService.require_approved(None)

    def test_require_approved_pending(self, pending_seller):
        with pytest.raises(SellerNotApproved):
            SellerService.require_approved(pending_seller)

    def test_require_approved_suspended(self, seller_profile):
        seller_profile.suspend()
        with pytest.raises(SellerSuspended):
            SellerService.require_approved(seller_profile)


class TestEventService:
    def test_create_flat_pricing(self, seller_profile, event_category):
        event = EventService.create(
            seller=seller_profile,
            title="New Event",
            description="Desc",
            platform_name="Zoom",
            category=event_category,
            starts_at=timezone.now() + timedelta(days=10),
            ends_at=timezone.now() + timedelta(days=10, hours=2),
        )
        assert event.title == "New Event"
        assert event.pricing_mode == PricingMode.FLAT.value
        assert event.price_tiers.count() == 1
        assert event.price_tiers.first().price_tag == PriceTag.GENERAL.value
        assert event.tickets_available == 0

    def test_create_categorized_pricing(self, seller_profile, event_category):
        event = EventService.create(
            seller=seller_profile,
            title="Categorized Event",
            description="Desc",
            platform_name="Venue",
            category=event_category,
            starts_at=timezone.now() + timedelta(days=10),
            ends_at=timezone.now() + timedelta(days=10, hours=2),
            pricing_mode=PricingMode.CATEGORIZED.value,
            price_tiers=[
                {"price_tag": PriceTag.VIP.value, "price": 10000, "quantity": 50},
                {"price_tag": PriceTag.REGULAR.value, "price": 3000, "quantity": 200},
            ],
        )
        assert event.price_tiers.count() == 2
        assert event.tickets_available == 250

    def test_create_rejects_unapproved(self, pending_seller, event_category):
        with pytest.raises(SellerNotApproved):
            EventService.create(
                seller=pending_seller,
                title="Bad",
                description="Bad",
                platform_name="X",
                category=event_category,
                starts_at=timezone.now() + timedelta(days=10),
                ends_at=timezone.now() + timedelta(days=10, hours=2),
            )

    def test_publish(self, draft_event, seller_profile):
        event = EventService.publish(draft_event, seller_profile)
        assert event.status == EventStatus.PUBLISHED.value

    def test_publish_not_owner(self, draft_event, other_user):
        other_seller = SellerProfile.objects.create(
            user=other_user,
            business_name="Other",
            status=SellerStatus.APPROVED.value,
        )
        with pytest.raises(InvalidEventStatus):
            EventService.publish(draft_event, other_seller)

    def test_cancel(self, published_event, seller_profile):
        event = EventService.cancel(published_event, seller_profile)
        assert event.status == EventStatus.CANCELLED.value

    def test_cancel_not_published_fails(self, draft_event, seller_profile):
        with pytest.raises(InvalidEventStatus):
            EventService.cancel(draft_event, seller_profile)

    def test_mark_completed(self, published_event):
        event = EventService.mark_completed(published_event)
        assert event.status == EventStatus.COMPLETED.value


class TestDisputeService:
    def test_open_dispute(self, dispute):
        assert dispute.status == DisputeStatus.OPEN.value
        assert dispute.conversation is not None
        assert dispute.conversation.members.count() == 2

    def test_assign_moderator(self, dispute, admin_user):
        d = DisputeService.assign_moderator(dispute, admin_user)
        assert d.assigned_moderator == admin_user
        assert d.status == DisputeStatus.UNDER_REVIEW.value
        assert d.conversation.members.count() == 3

    def test_resolve_dispute(self, dispute, admin_user):
        d = DisputeService.resolve(
            dispute, admin_user, resolution=DisputeStatus.RESOLVED_BUYER.value,
            notes="Refund issued",
        )
        assert d.status == DisputeStatus.RESOLVED_BUYER.value
        assert d.resolved_at is not None
        assert d.conversation.is_locked is True


class TestReportService:
    def test_event_sales_report(self, published_event, sold_ticket):
        report = ReportService.event_sales_report(published_event)
        assert report["event_title"] == "Published Concert"
        assert report["total_sold"] == 1
        assert float(report["total_revenue"]) > 0

    def test_seller_aggregate_report(self, seller_profile, published_event):
        report = ReportService.seller_aggregate_report(seller_profile)
        assert report["business_name"] == "Test Seller Inc."
        assert "financials" in report
        assert "events" in report

    def test_download_event_csv(self, published_event, sold_ticket):
        csv_file = ReportService.download_event_csv(published_event)
        content = csv_file.getvalue()
        assert sold_ticket.ticket_code in content
        assert "Ticket Code" in content

    def test_download_full_transaction_report(self, seller_profile):
        csv_file = ReportService.download_full_transaction_report(seller_profile)
        content = csv_file.getvalue()
        assert "Reference" in content
