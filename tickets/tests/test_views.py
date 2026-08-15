from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import ANY, patch

import pytest
from django.utils import timezone
from rest_framework import status

from clients.payments import (
    PaymentEventType,
    PaymentInitialization,
    PaymentState,
    PaymentVerification,
    WebhookEvent,
)
from tickets.models import (
    Dispute,
    Event,
    EventCategory,
    Payout,
    PaymentTransaction,
    PriceTier,
    SellerProfile,
    Ticket,
    TicketPurchase,
)
from utils.enum import (
    DisputeStatus,
    EventStatus,
    PaymentStatus,
    PriceTag,
    SellerStatus,
    TicketStatus,
)

pytestmark = pytest.mark.django_db

API_ROOT = "/api/v2/tickets/"


# ── Event Categories ───────────────────────────────────────────────────────


class TestEventCategoryViews:
    def test_list_categories(self, api_client, event_category):
        resp = api_client.get(f"{API_ROOT}categories/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["status"] is True
        names = [c["name"] for c in resp.data["data"]]
        assert "Music Concert" in names

    def test_create_category_as_user(self, auth_client):
        resp = auth_client.post(
            f"{API_ROOT}categories/",
            {"name": "Sports", "description": "Sports events"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["name"] == "Sports"


# ── Seller Application ─────────────────────────────────────────────────────


class TestSellerApplyView:
    url = f"{API_ROOT}sellers/apply/"

    def test_apply_success(self, auth_client):
        resp = auth_client.post(
            self.url,
            {"business_name": "My Business"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["data"]["business_name"] == "My Business"
        assert resp.data["data"]["status"] == SellerStatus.PENDING.value

    def test_apply_unauthenticated(self, api_client):
        resp = api_client.post(
            self.url,
            {"business_name": "Hacker"},
            format="json",
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ── Seller Profile ─────────────────────────────────────────────────────────


class TestSellerProfileView:
    url = f"{API_ROOT}sellers/me/"

    def test_retrieve(self, seller_auth_client, seller_profile):
        resp = seller_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["business_name"] == "Test Seller Inc."

    def test_retrieve_no_profile(self, auth_client):
        resp = auth_client.get(self.url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_update(self, seller_auth_client, seller_profile):
        resp = seller_auth_client.patch(
            self.url,
            {"business_name": "Updated Inc."},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        seller_profile.refresh_from_db()
        assert seller_profile.business_name == "Updated Inc."


# ── Seller Approval (Admin) ────────────────────────────────────────────────


class TestSellerApprovalView:
    def test_approve(self, admin_auth_client, pending_seller):
        resp = admin_auth_client.post(
            f"{API_ROOT}admin/sellers/{pending_seller.id}/review/",
            {"action": "approve"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        pending_seller.refresh_from_db()
        assert pending_seller.status == SellerStatus.APPROVED.value

    def test_reject(self, admin_auth_client, pending_seller):
        resp = admin_auth_client.post(
            f"{API_ROOT}admin/sellers/{pending_seller.id}/review/",
            {"action": "reject", "rejection_reason": "Bad docs"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        pending_seller.refresh_from_db()
        assert pending_seller.status == SellerStatus.REJECTED.value

    def test_non_admin_forbidden(self, seller_auth_client, pending_seller):
        resp = seller_auth_client.post(
            f"{API_ROOT}admin/sellers/{pending_seller.id}/review/",
            {"action": "approve"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ── Event CRUD ─────────────────────────────────────────────────────────────


class TestEventCreateView:
    url = f"{API_ROOT}events/"

    def test_create_as_seller(self, seller_auth_client, seller_profile, event_category):
        resp = seller_auth_client.post(
            self.url,
            {
                "title": "My Event",
                "description": "Desc",
                "platform_name": "Venue",
                "category": str(event_category.id),
                "starts_at": (timezone.now() + timedelta(days=10)).isoformat(),
                "ends_at": (timezone.now() + timedelta(days=10, hours=3)).isoformat(),
                "visibility": "public",
                "fee_bearer": "buyer",
                "pricing_mode": "flat",
                "price_tiers": [
                    {"price_tag": "general", "price": "5000.00", "quantity": 100},
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["data"]["title"] == "My Event"
        assert resp.data["data"]["status"] == EventStatus.DRAFT.value
        assert Event.objects.count() == 1

    def test_create_unapproved_seller(self, auth_client):
        resp = auth_client.post(
            self.url,
            {"title": "Bad", "platform_name": "X", "starts_at": (timezone.now() + timedelta(days=10)).isoformat()},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_create_unauthenticated(self, api_client):
        resp = api_client.post(self.url, {"title": "X"}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestEventListView:
    url = f"{API_ROOT}events/"

    def test_list_seller_events(self, seller_auth_client, draft_event):
        resp = seller_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) >= 1

    def test_list_public_events(self, api_client, published_event):
        resp = api_client.get(f"{API_ROOT}events/public/")
        assert resp.status_code == status.HTTP_200_OK
        titles = [e["title"] for e in resp.data["data"]]
        assert "Published Concert" in titles


class TestEventRetrieveView:
    def test_retrieve(self, seller_auth_client, draft_event):
        resp = seller_auth_client.get(f"{API_ROOT}events/{draft_event.id}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["title"] == "Test Concert"


class TestEventUpdateView:
    def test_update_draft(self, seller_auth_client, draft_event):
        resp = seller_auth_client.patch(
            f"{API_ROOT}events/{draft_event.id}/",
            {"title": "Updated Title"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        draft_event.refresh_from_db()
        assert draft_event.title == "Updated Title"

    def test_update_other_seller_forbidden(self, other_auth_client, draft_event):
        resp = other_auth_client.patch(
            f"{API_ROOT}events/{draft_event.id}/",
            {"title": "Hacked"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_update_published_fails(self, seller_auth_client, published_event):
        resp = seller_auth_client.patch(
            f"{API_ROOT}events/{published_event.id}/",
            {"title": "Nope"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestEventPublishView:
    def test_publish(self, seller_auth_client, draft_event):
        resp = seller_auth_client.post(
            f"{API_ROOT}events/{draft_event.id}/publish/",
        )
        assert resp.status_code == status.HTTP_200_OK
        draft_event.refresh_from_db()
        assert draft_event.status == EventStatus.PUBLISHED.value

    def test_publish_other_seller(self, other_auth_client, draft_event):
        resp = other_auth_client.post(
            f"{API_ROOT}events/{draft_event.id}/publish/",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


class TestEventCancelView:
    def test_cancel_published(self, seller_auth_client, published_event):
        resp = seller_auth_client.post(
            f"{API_ROOT}events/{published_event.id}/cancel/",
        )
        assert resp.status_code == status.HTTP_200_OK
        published_event.refresh_from_db()
        assert published_event.status == EventStatus.CANCELLED.value

    def test_cancel_draft_fails(self, seller_auth_client, draft_event):
        resp = seller_auth_client.post(
            f"{API_ROOT}events/{draft_event.id}/cancel/",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestEventByLinkView:
    def test_by_link(self, api_client, published_event):
        resp = api_client.get(
            f"{API_ROOT}events/by_link/?link={published_event.event_link}"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["title"] == "Published Concert"

    def test_by_link_not_found(self, api_client):
        resp = api_client.get(
            f"{API_ROOT}events/by_link/?link=nonexistent"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestEventPriceTiersView:
    def test_list_tiers(self, api_client, published_event):
        resp = api_client.get(
            f"{API_ROOT}events/{published_event.id}/price_tiers/"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) == 2


# ── Ticket Purchase ────────────────────────────────────────────────────────


class TestTicketPurchaseInitializeView:
    url = f"{API_ROOT}buy/initialize/"

    @patch("tickets.services.ticket_service.PaymentService.initialize_transaction")
    def test_initialize_success(
        self, mock_paystack, auth_client, published_event, price_tier
    ):
        mock_paystack.return_value = PaymentInitialization(
            authorization_url="https://checkout.gateway.test/abc",
            reference="REF-TEST",
            access_code="test_access_code",
            provider="memory",
            raw={"reference": "REF-TEST"},
        )

        with patch("redis.from_url") as mock_redis:
            mock_redis.return_value.set.return_value = True
            mock_redis.return_value.delete.return_value = True
            resp = auth_client.post(
                self.url,
                {
                    "event_id": str(published_event.id),
                    "price_tier_id": str(price_tier.id),
                    "quantity": 2,
                },
                format="json",
            )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["data"]["authorization_url"] is not None
        assert resp.data["data"]["transaction_ref"] is not None
        assert TicketPurchase.objects.count() == 1

    def test_initialize_unauthenticated(self, api_client, published_event, price_tier):
        resp = api_client.post(
            self.url,
            {
                "event_id": str(published_event.id),
                "price_tier_id": str(price_tier.id),
                "quantity": 1,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_initialize_insufficient_tickets(
        self, auth_client, published_event, price_tier
    ):
        price_tier.quantity = 0
        price_tier.save()

        with patch("redis.from_url") as mock_redis:
            mock_redis.return_value.set.return_value = True
            mock_redis.return_value.delete.return_value = True
            resp = auth_client.post(
                self.url,
                {
                    "event_id": str(published_event.id),
                    "price_tier_id": str(price_tier.id),
                    "quantity": 5,
                },
                format="json",
            )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestTicketPurchaseVerifyView:
    url = f"{API_ROOT}buy/verify/"

    @patch("tickets.services.ticket_service.PaymentService.verify_transaction")
    def test_verify_success(self, mock_verify, auth_client, ticket_purchase):
        # Normalised: Decimal in MAJOR units, not gateway-native kobo.
        mock_verify.return_value = PaymentVerification(
            reference=ticket_purchase.transaction_ref,
            state=PaymentState.SUCCESS,
            amount=Decimal(str(ticket_purchase.total_amount)),
            provider="memory",
        )

        resp = auth_client.post(
            self.url,
            {"reference": ticket_purchase.transaction_ref},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["data"]["status"] == "confirmed"

    @patch("tickets.services.ticket_service.PaymentService.verify_transaction")
    def test_verify_failed_payment(self, mock_verify, auth_client, ticket_purchase):
        mock_verify.return_value = PaymentVerification(
            reference=ticket_purchase.transaction_ref,
            state=PaymentState.FAILED,
            amount=Decimal("0"),
            provider="memory",
        )

        resp = auth_client.post(
            self.url,
            {"reference": ticket_purchase.transaction_ref},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── My Tickets ─────────────────────────────────────────────────────────────


class TestMyTicketsView:
    url = f"{API_ROOT}buy/my-tickets/"

    def test_list_tickets(self, auth_client, sold_ticket):
        resp = auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        codes = [t["ticket_code"] for t in resp.data["data"]]
        assert "TKT-SOLD-001" in codes

    def test_empty_for_other_user(self, other_auth_client):
        resp = other_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) == 0


# ── Ticket Code Verify ─────────────────────────────────────────────────────


class TestTicketCodeVerifyView:
    def test_verify_valid(self, api_client, sold_ticket):
        resp = api_client.get(
            f"{API_ROOT}tickets/verify/{sold_ticket.ticket_code}/"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["ticket_code"] == "TKT-SOLD-001"
        assert resp.data["data"]["status"] == TicketStatus.SOLD.value

    def test_verify_invalid(self, api_client):
        resp = api_client.get(f"{API_ROOT}tickets/verify/INVALID-CODE/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ── Disputes ───────────────────────────────────────────────────────────────


class TestDisputeCreateView:
    url = f"{API_ROOT}disputes/"

    def test_open_dispute(self, auth_client, sold_ticket):
        resp = auth_client.post(
            self.url,
            {
                "ticket_id": str(sold_ticket.id),
                "reason": "refund_request",
                "description": "Want a refund",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["data"]["status"] == DisputeStatus.OPEN.value
        assert Dispute.objects.count() == 1

    def test_open_dispute_unauthenticated(self, api_client, sold_ticket):
        resp = api_client.post(
            self.url,
            {"ticket_id": str(sold_ticket.id), "reason": "other", "description": "X"},
            format="json",
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_open_dispute_not_owner(self, other_auth_client, sold_ticket):
        resp = other_auth_client.post(
            self.url,
            {"ticket_id": str(sold_ticket.id), "reason": "other", "description": "X"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestDisputeListView:
    url = f"{API_ROOT}disputes/"

    def test_list_buyer_disputes(self, auth_client, dispute):
        resp = auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) >= 1

    def test_list_seller_disputes(self, seller_auth_client, dispute):
        resp = seller_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) >= 1

    def test_list_admin_disputes(self, admin_auth_client, dispute):
        resp = admin_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) >= 1


class TestDisputeAssignModeratorView:
    def test_assign_moderator(self, admin_auth_client, dispute):
        resp = admin_auth_client.post(
            f"{API_ROOT}disputes/{dispute.id}/assign_moderator/",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        dispute.refresh_from_db()
        assert dispute.status == DisputeStatus.UNDER_REVIEW.value

    def test_assign_non_admin_forbidden(self, seller_auth_client, dispute):
        resp = seller_auth_client.post(
            f"{API_ROOT}disputes/{dispute.id}/assign_moderator/",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


class TestDisputeResolveView:
    def test_resolve(self, admin_auth_client, dispute):
        resp = admin_auth_client.post(
            f"{API_ROOT}disputes/{dispute.id}/resolve/",
            {"resolution": "resolved_buyer", "notes": "Refund issued"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        dispute.refresh_from_db()
        assert dispute.status == DisputeStatus.RESOLVED_BUYER.value

    def test_resolve_non_admin_forbidden(self, seller_auth_client, dispute):
        resp = seller_auth_client.post(
            f"{API_ROOT}disputes/{dispute.id}/resolve/",
            {"resolution": "resolved_buyer"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ── Reports ────────────────────────────────────────────────────────────────


class TestEventReportView:
    def test_event_report(self, seller_auth_client, published_event, sold_ticket):
        resp = seller_auth_client.get(
            f"{API_ROOT}events/{published_event.id}/report/"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["event_title"] == "Published Concert"
        assert resp.data["data"]["total_sold"] >= 1

    def test_event_report_forbidden(self, other_auth_client, published_event):
        resp = other_auth_client.get(
            f"{API_ROOT}events/{published_event.id}/report/"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


class TestEventReportDownloadView:
    def test_download_csv(self, seller_auth_client, published_event, sold_ticket):
        resp = seller_auth_client.get(
            f"{API_ROOT}events/{published_event.id}/report/download/"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp["Content-Type"] == "text/csv"
        content = b"".join(resp.streaming_content).decode()
        assert "TKT-SOLD-001" in content


class TestSellerReportView:
    url = f"{API_ROOT}reports/seller/"

    def test_seller_report(self, seller_auth_client, seller_profile):
        resp = seller_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["business_name"] == "Test Seller Inc."

    def test_seller_report_no_profile(self, auth_client):
        resp = auth_client.get(self.url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ── Seller Financials ──────────────────────────────────────────────────────


class TestSellerTransactionView:
    url = f"{API_ROOT}sellers/me/transactions/"

    def test_list_transactions(self, seller_auth_client, payment_transaction):
        resp = seller_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) >= 1

    def test_no_transactions(self, other_auth_client):
        resp = other_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK


class TestSellerPayoutView:
    url = f"{API_ROOT}sellers/me/payouts/"

    def test_list_payouts(self, seller_auth_client, payout):
        resp = seller_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["data"]) >= 1

    def test_no_payouts(self, other_auth_client):
        resp = other_auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK


class TestSellerReportDownloadView:
    def test_download_transactions(self, seller_auth_client, payment_transaction):
        resp = seller_auth_client.get(
            f"{API_ROOT}sellers/me/report/download/"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp["Content-Type"] == "text/csv"


# ── Paystack Webhook ───────────────────────────────────────────────────────


class TestPaymentWebhookView:
    """The view is gateway-neutral: the provider verifies and normalises."""

    url = f"{API_ROOT}webhook/payment/"
    legacy_url = f"{API_ROOT}webhook/paystack/"

    def test_invalid_signature(self, api_client):
        """A provider that rejects the signature must surface as 401."""
        from clients.payments import InvalidWebhookSignature

        with patch(
            "tickets.views.PaymentService.parse_webhook",
            side_effect=InvalidWebhookSignature("paystack"),
        ):
            resp = api_client.post(
                self.url,
                {"event": "charge.success", "data": {}},
                format="json",
                HTTP_X_PAYSTACK_SIGNATURE="invalid",
            )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_real_paystack_provider_rejects_a_forged_signature(self, api_client):
        """End-to-end through the actual provider, not a mock."""
        from clients.payments import PaymentGateway
        from clients.payments.providers.paystack import PaystackProvider

        gateway = PaymentGateway(PaystackProvider(secret_key="sk_test"))
        with patch("tickets.views.PaymentService.gateway", return_value=gateway):
            resp = api_client.post(
                self.url,
                {"event": "charge.success", "data": {}},
                format="json",
                HTTP_X_PAYSTACK_SIGNATURE="forged",
            )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("tickets.views.PaymentService.parse_webhook")
    def test_charge_success_webhook(self, mock_parse, api_client, ticket_purchase):
        mock_parse.return_value = WebhookEvent(
            type=PaymentEventType.PAYMENT_SUCCEEDED,
            reference=ticket_purchase.transaction_ref,
            amount=Decimal(str(ticket_purchase.total_amount)),
            provider="memory",
        )

        with patch("tickets.views.PaymentService.handle_webhook") as mock_handle:
            resp = api_client.post(
                self.url, {"any": "payload"}, format="json",
            )
            assert resp.status_code == status.HTTP_200_OK
            mock_handle.assert_called_once()
            assert mock_handle.call_args.args[0].type is (
                PaymentEventType.PAYMENT_SUCCEEDED
            )

    @patch("tickets.views.PaymentService.parse_webhook")
    def test_legacy_paystack_url_still_routes(self, mock_parse, api_client):
        mock_parse.return_value = WebhookEvent(
            type=PaymentEventType.UNKNOWN, provider="memory"
        )
        with patch("tickets.views.PaymentService.handle_webhook"):
            resp = api_client.post(self.legacy_url, {"a": 1}, format="json")
        assert resp.status_code == status.HTTP_200_OK

    @patch("tickets.views.PaymentService.parse_webhook")
    def test_handler_failure_returns_5xx_so_the_gateway_retries(
        self, mock_parse, api_client
    ):
        mock_parse.return_value = WebhookEvent(
            type=PaymentEventType.PAYMENT_SUCCEEDED, reference="REF-X", provider="memory"
        )
        with patch(
            "tickets.views.PaymentService.handle_webhook",
            side_effect=RuntimeError("db down"),
        ):
            resp = api_client.post(self.url, {"a": 1}, format="json")
        assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


# ── Event Delete (soft delete) ─────────────────────────────────────────────


class TestEventDeleteView:
    def test_delete_own_event(self, seller_auth_client, draft_event):
        resp = seller_auth_client.delete(
            f"{API_ROOT}events/{draft_event.id}/"
        )
        assert resp.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT)
        draft_event.refresh_from_db()
        assert draft_event.is_deleted is True

    def test_delete_other_event(self, other_auth_client, draft_event):
        resp = other_auth_client.delete(
            f"{API_ROOT}events/{draft_event.id}/"
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
