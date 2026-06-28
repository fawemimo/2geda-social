from django.contrib import admin

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


class PriceTierInline(admin.TabularInline):
    model = PriceTier
    extra = 0
    fields = ["price_tag", "price", "quantity", "quantity_sold", "quantity_reserved", "is_active"]
    readonly_fields = ["quantity_sold", "quantity_reserved"]


class TicketInline(admin.TabularInline):
    model = Ticket
    extra = 0
    fields = ["ticket_code", "buyer", "status", "price_paid", "purchased_at"]
    readonly_fields = ["ticket_code", "buyer", "status", "price_paid", "purchased_at"]


@admin.register(EventCategory)
class EventCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "created_at"]
    search_fields = ["name"]
    list_filter = ["is_active"]


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = [
        "business_name", "user", "status", "total_events_created",
        "total_revenue", "submitted_at", "reviewed_at",
    ]
    search_fields = ["business_name", "user__email", "user__username"]
    list_filter = ["status"]
    readonly_fields = [
        "total_events_created", "total_revenue", "submitted_at",
        "reviewed_at", "reviewed_by",
    ]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = [
        "title", "seller", "status", "visibility", "pricing_mode",
        "total_tickets_sold", "total_revenue", "starts_at",
    ]
    search_fields = ["title", "seller__business_name"]
    list_filter = ["status", "visibility", "pricing_mode", "is_verified"]
    inlines = [PriceTierInline]
    readonly_fields = [
        "event_link", "total_tickets_sold", "total_revenue",
        "tickets_available", "tickets_reserved",
    ]


@admin.register(PriceTier)
class PriceTierAdmin(admin.ModelAdmin):
    list_display = ["event", "price_tag", "price", "quantity", "quantity_sold", "is_active"]
    list_filter = ["price_tag", "is_active"]
    search_fields = ["event__title"]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["ticket_code", "event", "buyer", "status", "price_paid", "purchased_at"]
    search_fields = ["ticket_code", "buyer__email", "event__title"]
    list_filter = ["status", "is_verified"]
    readonly_fields = ["qr_code_data", "ticket_code"]


@admin.register(TicketPurchase)
class TicketPurchaseAdmin(admin.ModelAdmin):
    list_display = [
        "transaction_ref", "buyer", "event", "quantity",
        "total_amount", "payment_status", "created_at",
    ]
    search_fields = ["transaction_ref", "buyer__email", "event__title"]
    list_filter = ["payment_status"]
    readonly_fields = ["paystack_data"]


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ["reference", "seller", "transaction_type", "amount", "status", "created_at"]
    search_fields = ["reference", "seller__business_name"]
    list_filter = ["transaction_type", "status"]


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ["payout_ref", "seller", "amount", "status", "paid_at", "created_at"]
    search_fields = ["payout_ref", "seller__business_name"]
    list_filter = ["status"]


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = [
        "ticket", "buyer", "seller", "reason", "status",
        "assigned_moderator", "created_at",
    ]
    search_fields = ["ticket__ticket_code", "buyer__email"]
    list_filter = ["status", "reason"]
