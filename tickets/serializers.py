from rest_framework import serializers

from accounts.models import User
from chats.models import ConversationMember
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
from tickets.services.seller_service import SellerService
from utils.enum import PriceTag


class EventCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EventCategory
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at", "is_deleted", "deleted_at"]


class PriceTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceTier
        fields = [
            "id", "event", "price_tag", "price", "quantity",
            "quantity_sold", "quantity_reserved", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "event", "created_at", "updated_at", "quantity_sold", "quantity_reserved"
        ]

    def validate(self, attrs):
        quantity = attrs.get("quantity", 0)
        if quantity < 0:
            raise serializers.ValidationError("Quantity must be non-negative.")
        price = attrs.get("price", 0)
        if price < 0:
            raise serializers.ValidationError("Price must be non-negative.")
        return attrs


class PriceTierNestedSerializer(serializers.Serializer):
    price_tag = serializers.ChoiceField(choices=PriceTag.choices())
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    quantity = serializers.IntegerField(min_value=1)


class PriceTierReadSerializer(serializers.ModelSerializer):
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = PriceTier
        fields = "__all__"


class SellerProfileSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = SellerProfile
        fields = [
            "id",
            "user",
            "user_email",
            "user_username",
            "business_name",
            "business_email",
            "business_phone",
            "business_address",
            "status",
            "commission_rate",
            "total_events_created",
            "total_revenue",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "status",
            "commission_rate",
            "total_events_created",
            "total_revenue",
            "created_at",
            "updated_at",
        ]


class SellerApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SellerProfile
        fields = [
            "business_name",
            "business_email",
            "business_phone",
            "business_address",
        ]


class SellerApprovalSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject"])
    rejection_reason = serializers.CharField(required=False, allow_blank=True)


class EventSerializer(serializers.ModelSerializer):
    price_tiers = PriceTierNestedSerializer(many=True, required=False)
    seller_name = serializers.CharField(
        source="seller.business_name", read_only=True
    )
    category_name = serializers.CharField(
        source="category.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Event
        fields = [
            "id",
            "seller",
            "seller_name",
            "category",
            "category_name",
            "title",
            "description",
            "cover_image",
            "platform_name",
            "website_url",
            "location",
            "starts_at",
            "ends_at",
            "visibility",
            "fee_bearer",
            "pricing_mode",
            "price_tiers",
            "event_link",
            "is_verified",
            "status",
            "total_tickets_sold",
            "total_revenue",
            "tickets_available",
            "tickets_reserved",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "seller",
            "event_link",
            "is_verified",
            "status",
            "total_tickets_sold",
            "total_revenue",
            "tickets_available",
            "tickets_reserved",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        price_tiers_data = validated_data.pop("price_tiers", [])
        from tickets.services.event_service import EventService
        seller = self.context["request"].user.seller_profile
        event_data = {
            **validated_data,
            "price_tiers": price_tiers_data,
        }
        return EventService.create(seller, **event_data)

    def update(self, instance, validated_data):
        price_tiers_data = validated_data.pop("price_tiers", None)
        from tickets.services.event_service import EventService
        seller = self.context["request"].user.seller_profile
        update_data = {**validated_data}
        if price_tiers_data is not None:
            update_data["price_tiers"] = price_tiers_data
        return EventService.update(instance, seller, **update_data)


class EventListSerializer(serializers.ModelSerializer):
    seller_name = serializers.CharField(
        source="seller.business_name", read_only=True
    )
    category_name = serializers.CharField(
        source="category.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "seller_name",
            "category_name",
            "platform_name",
            "starts_at",
            "visibility",
            "pricing_mode",
            "event_link",
            "is_verified",
            "status",
            "total_tickets_sold",
            "tickets_available",
            "cover_image",
        ]


class TicketSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True)
    buyer_username = serializers.CharField(source="buyer.username", read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "event",
            "event_title",
            "buyer",
            "buyer_username",
            "price_tier",
            "ticket_code",
            "qr_code_data",
            "status",
            "price_paid",
            "fees_paid",
            "is_verified",
            "purchased_at",
            "created_at",
        ]
        read_only_fields = [
            "id", "ticket_code", "qr_code_data", "status",
            "purchased_at", "created_at",
        ]


class TicketPurchaseInitializeSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    price_tier_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=100)


class TicketPurchaseVerifySerializer(serializers.Serializer):
    reference = serializers.CharField()


class DisputeSerializer(serializers.ModelSerializer):
    buyer_username = serializers.CharField(source="buyer.username", read_only=True)
    seller_name = serializers.CharField(
        source="seller.business_name", read_only=True
    )
    ticket_code = serializers.CharField(
        source="ticket.ticket_code", read_only=True
    )
    event_title = serializers.CharField(source="event.title", read_only=True)
    moderator_username = serializers.CharField(
        source="assigned_moderator.username", read_only=True, allow_null=True
    )
    conversation_id = serializers.UUIDField(
        source="conversation.id", read_only=True, allow_null=True
    )

    class Meta:
        model = Dispute
        fields = [
            "id",
            "ticket",
            "ticket_code",
            "buyer",
            "buyer_username",
            "seller_name",
            "event",
            "event_title",
            "reason",
            "description",
            "status",
            "assigned_moderator",
            "moderator_username",
            "resolution_notes",
            "resolved_at",
            "conversation_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "buyer",
            "seller",
            "status",
            "assigned_moderator",
            "resolution_notes",
            "resolved_at",
            "conversation",
            "created_at",
            "updated_at",
        ]


class DisputeCreateSerializer(serializers.Serializer):
    ticket_id = serializers.UUIDField()
    reason = serializers.ChoiceField(
        choices=[
            "ticket_not_delivered",
            "event_cancelled",
            "wrong_description",
            "refund_request",
            "other",
        ]
    )
    description = serializers.CharField()


class DisputeResolveSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(
        choices=["resolved_buyer", "resolved_seller", "closed"]
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class PaymentTransactionSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(
        source="event.title", read_only=True, allow_null=True
    )
    buyer_username = serializers.CharField(
        source="buyer.username", read_only=True, allow_null=True
    )

    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "seller",
            "event",
            "event_title",
            "buyer",
            "buyer_username",
            "transaction_type",
            "amount",
            "fees",
            "currency",
            "reference",
            "status",
            "notes",
            "created_at",
        ]
        read_only_fields = [
            "id", "created_at", "updated_at",
        ]


class PayoutSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(
        source="event.title", read_only=True, allow_null=True
    )

    class Meta:
        model = Payout
        fields = [
            "id",
            "seller",
            "event",
            "event_title",
            "amount",
            "fees_deducted",
            "currency",
            "status",
            "payout_ref",
            "paid_at",
            "created_at",
        ]


class TicketVerifySerializer(serializers.Serializer):
    code = serializers.CharField()
