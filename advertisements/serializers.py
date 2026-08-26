from __future__ import annotations

from rest_framework import serializers

from advertisements.models import (
    AdCreative,
    AdDailyMetric,
    AdEvent,
    AdPlacement,
    Advertisement,
)
from utils.enum import (
    AdAudienceGender,
    AdCallToAction,
    AdEventType,
    AdMode,
    AdObjective,
    AdPricingModel,
    AdScreenPosition,
)

MAX_CREATIVES_PER_AD = 10


class AdMediaIdsMixin:
    """Only the advertiser's own uploaded media may be used as a creative."""

    def validate_media_ids(self, value):
        if not value:
            return value

        if len(value) > MAX_CREATIVES_PER_AD:
            raise serializers.ValidationError(
                f"An advert may carry at most {MAX_CREATIVES_PER_AD} images."
            )

        ids = [str(v) for v in value]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Duplicate media ids are not allowed.")

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return value

        from medias.models import Media

        owned = {
            str(pk)
            for pk in Media.objects.filter(
                pk__in=ids, owner=user, is_deleted=False
            ).values_list("pk", flat=True)
        }
        unknown = [i for i in ids if i not in owned]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown media, or not owned by you: {', '.join(unknown)}"
            )
        return value


class AdPlacementInputSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=AdMode.choices())
    screen_position = serializers.ChoiceField(
        choices=AdScreenPosition.choices(),
        required=False,
        default=AdScreenPosition.INLINE.value,
    )
    display_seconds = serializers.IntegerField(min_value=0, max_value=120, required=False, default=0)
    is_skippable = serializers.BooleanField(required=False, default=True)
    skip_after_seconds = serializers.IntegerField(min_value=0, max_value=60, required=False, default=5)
    show_every_n = serializers.IntegerField(min_value=1, max_value=100, required=False, default=1)


class AdPlacementSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdPlacement
        fields = [
            "id", "mode", "screen_position", "display_seconds",
            "is_skippable", "skip_after_seconds", "show_every_n",
        ]
        read_only_fields = ["id"]


class AdCreativeSerializer(serializers.ModelSerializer):
    media_id = serializers.UUIDField(source="media.id", read_only=True)
    image_url = serializers.CharField(source="media.cdn_url", read_only=True)
    width = serializers.IntegerField(source="media.width_px", read_only=True)
    height = serializers.IntegerField(source="media.height_px", read_only=True)
    processing_status = serializers.CharField(
        source="media.processing_status", read_only=True,
    )

    class Meta:
        model = AdCreative
        fields = [
            "id", "media_id", "image_url", "width", "height",
            "processing_status", "headline", "caption", "alt_text", "position",
        ]
        read_only_fields = fields


class AdvertisementCreateSerializer(AdMediaIdsMixin, serializers.Serializer):
    title = serializers.CharField(max_length=140)
    # Optional by design — an advert may be image-only.
    caption = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default="",
    )
    call_to_action = serializers.ChoiceField(
        choices=AdCallToAction.choices(),
        required=False,
        default=AdCallToAction.LEARN_MORE.value,
    )
    destination_url = serializers.URLField(required=False, allow_blank=True, default="")
    objective = serializers.ChoiceField(
        choices=AdObjective.choices(),
        required=False,
        default=AdObjective.BRAND_AWARENESS.value,
    )

    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()

    media_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list,
    )
    placements = AdPlacementInputSerializer(many=True)

    priority = serializers.IntegerField(min_value=1, max_value=10, required=False, default=5)
    daily_impression_cap = serializers.IntegerField(min_value=0, required=False, default=0)
    total_impression_cap = serializers.IntegerField(min_value=0, required=False, default=0)
    frequency_cap_per_user = serializers.IntegerField(min_value=0, max_value=100, required=False, default=0)

    target_gender = serializers.ChoiceField(
        choices=AdAudienceGender.choices(),
        required=False,
        default=AdAudienceGender.ALL.value,
    )
    target_min_age = serializers.IntegerField(min_value=13, max_value=120, required=False, allow_null=True)
    target_max_age = serializers.IntegerField(min_value=13, max_value=120, required=False, allow_null=True)
    target_countries = serializers.ListField(
        child=serializers.CharField(max_length=2), required=False, default=list,
    )
    target_cities = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False, default=list,
    )
    target_interests = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, default=list,
    )

    pricing_model = serializers.ChoiceField(
        choices=AdPricingModel.choices(), required=False, default=AdPricingModel.CPM.value,
    )
    currency = serializers.CharField(max_length=3, required=False, default="NGN")
    budget_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0,
    )
    bid_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0,
    )

    def validate_placements(self, value):
        if not value:
            raise serializers.ValidationError("Choose at least one advert mode.")
        modes = [item["mode"] for item in value]
        if len(set(modes)) != len(modes):
            raise serializers.ValidationError("Each advert mode may appear only once.")
        return value

    def validate(self, attrs):
        starts_at, ends_at = attrs.get("starts_at"), attrs.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "ends_at must be after starts_at."}
            )

        low, high = attrs.get("target_min_age"), attrs.get("target_max_age")
        if low and high and low > high:
            raise serializers.ValidationError(
                {"target_max_age": "target_max_age must be >= target_min_age."}
            )
        return attrs


class AdvertisementUpdateSerializer(AdvertisementCreateSerializer):
    """Same shape, everything optional."""

    title = serializers.CharField(max_length=140, required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    media_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    placements = AdPlacementInputSerializer(many=True, required=False)

    def validate_placements(self, value):
        if value is None:
            return value
        return super().validate_placements(value)


class AdvertisementSerializer(serializers.ModelSerializer):
    advertiser_username = serializers.CharField(
        source="advertiser.username", read_only=True,
    )
    creatives = AdCreativeSerializer(many=True, read_only=True)
    placements = AdPlacementSerializer(many=True, read_only=True)
    click_through_rate = serializers.FloatField(read_only=True)
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = Advertisement
        fields = [
            "id", "advertiser", "advertiser_username", "title", "caption",
            "call_to_action", "destination_url", "objective", "status",
            "starts_at", "ends_at", "activated_at", "completed_at",
            "priority", "daily_impression_cap", "total_impression_cap",
            "frequency_cap_per_user",
            "target_gender", "target_min_age", "target_max_age",
            "target_countries", "target_cities", "target_interests",
            "pricing_model", "currency", "budget_amount", "bid_amount",
            "amount_spent",
            "impressions_count", "clicks_count", "conversions_count",
            "click_through_rate", "is_live",
            "rejection_reason", "reviewed_at",
            "creatives", "placements",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class AdServeSerializer(serializers.Serializer):
    """The lean payload a mobile client renders. No commercial fields."""

    advertisement_id = serializers.UUIDField(source="advertisement.id")
    placement_id = serializers.UUIDField(source="id")
    title = serializers.CharField(source="advertisement.title")
    caption = serializers.CharField(source="advertisement.caption")
    call_to_action = serializers.CharField(source="advertisement.call_to_action")
    destination_url = serializers.CharField(source="advertisement.destination_url")
    mode = serializers.CharField()
    screen_position = serializers.CharField()
    display_seconds = serializers.IntegerField()
    is_skippable = serializers.BooleanField()
    skip_after_seconds = serializers.IntegerField()
    creatives = serializers.SerializerMethodField()

    def get_creatives(self, obj):
        return AdCreativeSerializer(
            obj.advertisement.creatives.all(), many=True, context=self.context
        ).data


class AdEventCreateSerializer(serializers.Serializer):
    advertisement_id = serializers.UUIDField()
    event_type = serializers.ChoiceField(choices=AdEventType.choices())
    placement_id = serializers.UUIDField(required=False, allow_null=True)
    device_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    dedupe_key = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    metadata = serializers.DictField(required=False, default=dict)


class AdReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject"])
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["action"] == "reject" and not attrs.get("reason", "").strip():
            raise serializers.ValidationError(
                {"reason": "A reason is required when rejecting an advert."}
            )
        return attrs


class AdDailyMetricSerializer(serializers.ModelSerializer):
    click_through_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = AdDailyMetric
        fields = ["date", "impressions", "clicks", "conversions", "spend",
                  "click_through_rate"]
        read_only_fields = fields
