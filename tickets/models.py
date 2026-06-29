from django.db import models

# Create your models here.
import uuid

from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from medias.models import Media
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
from utils.generators import generate_event_link, generate_ticket_code
from utils.models import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin


class EventCategory(BaseModel):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    description = models.TextField(blank=True)
    icon = models.ForeignKey(
        Media,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="category_icons",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "tickets_event_category"
        verbose_name = _("event category")
        verbose_name_plural = _("event categories")
        indexes = [
            models.Index(
                fields=["name"],
                condition=models.Q(is_deleted=False),
                name="cat_active_name_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class SellerProfile(BaseModel):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="seller_profile",
        db_index=True,
    )
    business_name = models.CharField(max_length=200)
    business_email = models.EmailField(blank=True)
    business_phone = models.CharField(max_length=30, blank=True)
    business_address = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=SellerStatus.choices(),
        default=SellerStatus.NOT_SUBMITTED.value,
        db_index=True,
    )

    document_type = models.CharField(
        max_length=20,
        choices=[],
        blank=True,
    )
    front_image = models.ForeignKey(
        Media,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="seller_kyc_front",
    )
    back_image = models.ForeignKey(
        Media,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="seller_kyc_back",
    )
    selfie_image = models.ForeignKey(
        Media,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="seller_kyc_selfie",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="seller_reviews",
    )
    rejection_reason = models.TextField(blank=True)

    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text=_("Platform commission percentage (e.g. 5.00 = 5%)"),
    )
    total_events_created = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)

    class Meta:
        db_table = "tickets_seller_profile"
        verbose_name = _("seller profile")
        indexes = [
            models.Index(fields=["status"], name="seller_status_idx"),
            models.Index(
                fields=["user"],
                condition=models.Q(is_deleted=False),
                name="seller_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.business_name or self.user.username} [{self.status}]"

    def approve(self, reviewer: User) -> None:
        from datetime import timedelta

        self.status = SellerStatus.APPROVED.value
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewer
        self.save(update_fields=["status", "reviewed_at", "reviewed_by"])

    def reject(self, reviewer: User, reason: str) -> None:
        self.status = SellerStatus.REJECTED.value
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewer
        self.rejection_reason = reason
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason"])

    def suspend(self) -> None:
        self.status = SellerStatus.SUSPENDED.value
        self.save(update_fields=["status"])


class Event(BaseModel):
    seller = models.ForeignKey(
        SellerProfile,
        on_delete=models.CASCADE,
        related_name="events",
        db_index=True,
    )
    category = models.ForeignKey(
        EventCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        db_index=True,
    )

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    cover_image = models.ForeignKey(
        Media,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="event_covers",
    )
    platform_name = models.CharField(
        max_length=200,
        help_text=_("Venue or platform name (e.g. Zoom, Google Meet, Eko Hotels)"),
    )
    website_url = models.URLField(blank=True)
    location = models.CharField(
        max_length=300,
        blank=True,
        help_text=_("Physical venue address if applicable"),
    )

    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)

    visibility = models.CharField(
        max_length=20,
        choices=EventVisibility.choices(),
        default=EventVisibility.PUBLIC.value,
        db_index=True,
    )
    fee_bearer = models.CharField(
        max_length=10,
        choices=TicketFeeBearer.choices(),
        default=TicketFeeBearer.BUYER.value,
    )
    pricing_mode = models.CharField(
        max_length=15,
        choices=PricingMode.choices(),
        default=PricingMode.FLAT.value,
    )

    qr_code = models.TextField(
        blank=True,
        help_text=_("Base64 or URL to event QR image"),
    )
    event_link = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_event_link,
    )
    is_verified = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_("Verified badge — set by admin"),
    )

    status = models.CharField(
        max_length=15,
        choices=EventStatus.choices(),
        default=EventStatus.DRAFT.value,
        db_index=True,
    )

    # Denormalised counters
    total_tickets_sold = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    tickets_available = models.PositiveIntegerField(default=0)
    tickets_reserved = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "tickets_event"
        verbose_name = _("event")
        verbose_name_plural = _("events")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["seller", "-created_at"], name="event_seller_idx"),
            models.Index(
                fields=["status", "-created_at"],
                condition=models.Q(is_deleted=False),
                name="event_active_idx",
            ),
            models.Index(
                fields=["-created_at"],
                condition=models.Q(status="published", is_deleted=False),
                name="event_public_idx",
            ),
            BrinIndex(fields=["created_at"], name="event_created_brin_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.status})"

    @property
    def is_upcoming(self) -> bool:
        return self.starts_at > timezone.now()

    @property
    def is_live(self) -> bool:
        now = timezone.now()
        return self.starts_at <= now and (self.ends_at is None or self.ends_at > now)


class PriceTier(UUIDPrimaryKeyMixin, TimestampMixin):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="price_tiers",
        db_index=True,
    )
    price_tag = models.CharField(
        max_length=15,
        choices=PriceTag.choices(),
        default=PriceTag.GENERAL.value,
    )
    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=0)
    quantity_sold = models.PositiveIntegerField(default=0)
    quantity_reserved = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "tickets_price_tier"
        verbose_name = _("price tier")
        unique_together = [("event", "price_tag")]
        indexes = [
            models.Index(
                fields=["event", "is_active"],
                name="pricetier_event_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.price_tag.upper()} — ₦{self.price} ({self.event.title[:30]})"

    @property
    def available(self) -> int:
        return self.quantity - self.quantity_sold - self.quantity_reserved


class Ticket(BaseModel):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="tickets",
        db_index=True,
    )
    buyer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="purchased_tickets",
        db_index=True,
    )
    price_tier = models.ForeignKey(
        PriceTier,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    purchase = models.ForeignKey(
        "TicketPurchase",
        on_delete=models.CASCADE,
        related_name="tickets",
        db_index=True,
    )

    ticket_code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        default=generate_ticket_code,
    )
    qr_code_data = models.TextField(blank=True)
    status = models.CharField(
        max_length=12,
        choices=TicketStatus.choices(),
        default=TicketStatus.RESERVED.value,
        db_index=True,
    )
    price_paid = models.DecimalField(max_digits=12, decimal_places=2)
    fees_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_verified = models.BooleanField(
        default=False,
        help_text=_("Custom verified badge on the ticket"),
    )
    purchased_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "tickets_ticket"
        verbose_name = _("ticket")
        verbose_name_plural = _("tickets")
        indexes = [
            models.Index(fields=["event", "status"], name="ticket_event_status_idx"),
            models.Index(fields=["buyer", "-purchased_at"], name="ticket_buyer_idx"),
            models.Index(fields=["ticket_code"], name="ticket_code_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.ticket_code} — {self.event.title[:30]}"


class TicketPurchase(UUIDPrimaryKeyMixin, TimestampMixin):
    buyer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ticket_purchases",
        db_index=True,
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="purchases",
        db_index=True,
    )
    quantity = models.PositiveIntegerField()
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    fees_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default="NGN")

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices(),
        default=PaymentStatus.PENDING.value,
        db_index=True,
    )
    transaction_ref = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )
    paystack_access_code = models.CharField(max_length=64, blank=True)
    paystack_authorization_url = models.URLField(blank=True)
    paystack_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Raw Paystack response/event data for audit"),
    )

    reserved_until = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Tickets reserved until this timestamp, then released"),
    )

    class Meta:
        db_table = "tickets_purchase"
        verbose_name = _("ticket purchase")
        indexes = [
            models.Index(
                fields=["buyer", "-created_at"],
                name="purchase_buyer_idx",
            ),
            models.Index(
                fields=["event", "payment_status"],
                name="purchase_event_status_idx",
            ),
            models.Index(
                fields=["transaction_ref"],
                name="purchase_ref_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Purchase({self.transaction_ref}) — {self.event.title[:30]}"


class PaymentTransaction(UUIDPrimaryKeyMixin, TimestampMixin):
    seller = models.ForeignKey(
        SellerProfile,
        on_delete=models.CASCADE,
        related_name="transactions",
        db_index=True,
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    buyer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transaction_logs",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    transaction_type = models.CharField(
        max_length=15,
        choices=TransactionType.choices(),
        db_index=True,
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    fees = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default="NGN")

    reference = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices(),
        default=PaymentStatus.SUCCESSFUL.value,
        db_index=True,
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "tickets_transaction"
        verbose_name = _("payment transaction")
        verbose_name_plural = _("payment transactions")
        indexes = [
            models.Index(
                fields=["seller", "-created_at"],
                name="tx_seller_idx",
            ),
            models.Index(
                fields=["seller", "transaction_type"],
                name="tx_seller_type_idx",
            ),
            models.Index(
                fields=["reference"],
                name="tx_reference_idx",
            ),
            BrinIndex(fields=["created_at"], name="tx_created_brin_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_type.upper()} {self.reference}"


class Payout(UUIDPrimaryKeyMixin, TimestampMixin):
    seller = models.ForeignKey(
        SellerProfile,
        on_delete=models.CASCADE,
        related_name="payouts",
        db_index=True,
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payouts",
        help_text=_("Null if aggregated multiple events"),
    )

    amount = models.DecimalField(max_digits=15, decimal_places=2)
    fees_deducted = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default="NGN")

    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices(),
        default=PaymentStatus.PENDING.value,
        db_index=True,
    )
    payout_ref = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tickets_payout"
        verbose_name = _("payout")
        indexes = [
            models.Index(
                fields=["seller", "-created_at"],
                name="payout_seller_idx",
            ),
            models.Index(
                fields=["event", "status"],
                name="payout_event_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Payout({self.payout_ref}) — {self.seller.business_name}"


class Dispute(BaseModel):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="disputes",
        db_index=True,
    )
    buyer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ticket_disputes",
        db_index=True,
    )
    seller = models.ForeignKey(
        SellerProfile,
        on_delete=models.CASCADE,
        related_name="disputes",
        db_index=True,
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="disputes",
        db_index=True,
    )

    reason = models.CharField(
        max_length=30,
        choices=DisputeReason.choices(),
        db_index=True,
    )
    description = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=DisputeStatus.choices(),
        default=DisputeStatus.OPEN.value,
        db_index=True,
    )

    assigned_moderator = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="moderated_disputes",
    )
    resolution_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    # Link to the existing chats.Conversation for real-time messaging
    conversation = models.OneToOneField(
        "chats.Conversation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dispute",
    )

    class Meta:
        db_table = "tickets_dispute"
        verbose_name = _("dispute")
        verbose_name_plural = _("disputes")
        indexes = [
            models.Index(
                fields=["status", "-created_at"],
                name="dispute_status_idx",
            ),
            models.Index(
                fields=["buyer", "status"],
                name="dispute_buyer_idx",
            ),
            models.Index(
                fields=["seller", "status"],
                name="dispute_seller_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Dispute({self.ticket.ticket_code}) [{self.status}]"
