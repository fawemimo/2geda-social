from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from medias.models import Media
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
    DisputeReason,
    DisputeStatus,
    EventStatus,
    EventVisibility,
    PaymentStatus,
    PriceTag,
    PricingMode,
    SellerStatus,
    TicketFeeBearer,
    TicketStatus,
    TransactionType,
)
from utils.generators import generate_transaction_reference


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(
        email="buyer@test.com",
        username="buyer",
        password="pass123",
        is_active=True,
    )


@pytest.fixture
def seller_user(db) -> User:
    return User.objects.create_user(
        email="seller@test.com",
        username="seller",
        password="pass123",
        is_active=True,
    )


@pytest.fixture
def other_user(db) -> User:
    return User.objects.create_user(
        email="other@test.com",
        username="otheruser",
        password="pass123",
        is_active=True,
    )


@pytest.fixture
def admin_user(db) -> User:
    return User.objects.create_user(
        email="admin@test.com",
        username="admin",
        password="pass123",
        is_active=True,
        is_staff=True,
    )


@pytest.fixture
def auth_client(api_client, user) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def seller_auth_client(api_client, seller_user) -> APIClient:
    api_client.force_authenticate(user=seller_user)
    return api_client


@pytest.fixture
def other_auth_client(api_client, other_user) -> APIClient:
    api_client.force_authenticate(user=other_user)
    return api_client


@pytest.fixture
def admin_auth_client(api_client, admin_user) -> APIClient:
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def event_category(db) -> EventCategory:
    return EventCategory.objects.create(
        name="Music Concert",
        description="Live music events",
        is_active=True,
    )


@pytest.fixture
def seller_profile(seller_user, db) -> SellerProfile:
    return SellerProfile.objects.create(
        user=seller_user,
        business_name="Test Seller Inc.",
        business_email="seller@test.com",
        business_phone="+2348000000000",
        status=SellerStatus.APPROVED.value,
        commission_rate=5.00,
    )


@pytest.fixture
def pending_seller(other_user, db) -> SellerProfile:
    return SellerProfile.objects.create(
        user=other_user,
        business_name="Pending Seller Co.",
        business_email="pending@test.com",
        status=SellerStatus.PENDING.value,
    )


@pytest.fixture
def draft_event(seller_profile, event_category, db) -> Event:
    event = Event.objects.create(
        seller=seller_profile,
        category=event_category,
        title="Test Concert",
        description="A great concert",
        platform_name="Eko Convention Centre",
        location="Lagos, Nigeria",
        starts_at=timezone.now() + timedelta(days=30),
        ends_at=timezone.now() + timedelta(days=30, hours=4),
        visibility=EventVisibility.PUBLIC.value,
        fee_bearer=TicketFeeBearer.BUYER.value,
        pricing_mode=PricingMode.FLAT.value,
        status=EventStatus.DRAFT.value,
        tickets_available=100,
    )
    PriceTier.objects.create(
        event=event,
        price_tag=PriceTag.GENERAL.value,
        price=5000.00,
        quantity=100,
    )
    return event


@pytest.fixture
def published_event(seller_profile, event_category, db) -> Event:
    event = Event.objects.create(
        seller=seller_profile,
        category=event_category,
        title="Published Concert",
        description="A published concert",
        platform_name="YouTube Live",
        website_url="https://example.com",
        starts_at=timezone.now() + timedelta(days=14),
        ends_at=timezone.now() + timedelta(days=14, hours=3),
        visibility=EventVisibility.PUBLIC.value,
        fee_bearer=TicketFeeBearer.BUYER.value,
        pricing_mode=PricingMode.CATEGORIZED.value,
        status=EventStatus.PUBLISHED.value,
        tickets_available=200,
        is_verified=True,
    )
    PriceTier.objects.create(
        event=event,
        price_tag=PriceTag.VIP.value,
        price=15000.00,
        quantity=50,
    )
    PriceTier.objects.create(
        event=event,
        price_tag=PriceTag.REGULAR.value,
        price=5000.00,
        quantity=150,
    )
    return event


@pytest.fixture
def price_tier(published_event, db) -> PriceTier:
    return published_event.price_tiers.filter(price_tag=PriceTag.VIP.value).first()


@pytest.fixture
def ticket_purchase(user, published_event, price_tier, db) -> TicketPurchase:
    ref = generate_transaction_reference()
    purchase = TicketPurchase.objects.create(
        buyer=user,
        event=published_event,
        quantity=2,
        total_amount=price_tier.price * 2,
        fees_amount=500.00,
        transaction_ref=ref,
        payment_status=PaymentStatus.PENDING.value,
        reserved_until=timezone.now() + timedelta(minutes=15),
    )
    for _ in range(2):
        Ticket.objects.create(
            event=published_event,
            buyer=user,
            price_tier=price_tier,
            purchase=purchase,
            ticket_code=f"TKT-TEST-{_+1}",
            price_paid=price_tier.price,
            status=TicketStatus.RESERVED.value,
        )
    PriceTier.objects.filter(id=price_tier.id).update(
        quantity_reserved=2,
    )
    return purchase


@pytest.fixture
def sold_ticket(user, published_event, price_tier, db) -> Ticket:
    purchase = TicketPurchase.objects.create(
        buyer=user,
        event=published_event,
        quantity=1,
        total_amount=price_tier.price,
        transaction_ref="REF-SOLD-TEST",
        payment_status=PaymentStatus.SUCCESSFUL.value,
    )
    ticket = Ticket.objects.create(
        event=published_event,
        buyer=user,
        price_tier=price_tier,
        purchase=purchase,
        ticket_code="TKT-SOLD-001",
        price_paid=price_tier.price,
        fees_paid=100.00,
        status=TicketStatus.SOLD.value,
        purchased_at=timezone.now() - timedelta(hours=2),
        qr_code_data='{"ticket_code": "TKT-SOLD-001"}',
    )
    return ticket


@pytest.fixture
def dispute(seller_profile, user, sold_ticket, published_event, db) -> Dispute:
    from chats.models import Conversation, ConversationMember
    from utils.enum import MemberRole

    conv = Conversation.objects.create(
        name=f"Dispute: {sold_ticket.ticket_code}",
    )
    ConversationMember.objects.create(conversation=conv, user=user)
    ConversationMember.objects.create(
        conversation=conv, user=seller_profile.user
    )

    return Dispute.objects.create(
        ticket=sold_ticket,
        buyer=user,
        seller=seller_profile,
        event=published_event,
        reason=DisputeReason.REFUND_REQUEST.value,
        description="Ticket not as described.",
        status=DisputeStatus.OPEN.value,
        conversation=conv,
    )


@pytest.fixture
def payment_transaction(seller_profile, published_event, user, sold_ticket, db) -> PaymentTransaction:
    return PaymentTransaction.objects.create(
        seller=seller_profile,
        event=published_event,
        buyer=user,
        ticket=sold_ticket,
        transaction_type=TransactionType.PURCHASE.value,
        amount=sold_ticket.price_paid,
        fees=100.00,
        reference=generate_transaction_reference(),
        status=PaymentStatus.SUCCESSFUL.value,
    )


@pytest.fixture
def payout(seller_profile, published_event, db) -> Payout:
    return Payout.objects.create(
        seller=seller_profile,
        event=published_event,
        amount=45000.00,
        fees_deducted=5000.00,
        payout_ref="PO-TEST001",
        status=PaymentStatus.PENDING.value,
    )
