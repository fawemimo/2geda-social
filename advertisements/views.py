from __future__ import annotations

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.views import APIView

from advertisements.models import Advertisement
from advertisements.serializers import (
    AdDailyMetricSerializer,
    AdEventCreateSerializer,
    AdReviewSerializer,
    AdServeSerializer,
    AdvertisementCreateSerializer,
    AdvertisementSerializer,
    AdvertisementUpdateSerializer,
)
from advertisements.services import AdDeliveryService, AdvertisementService
from utils.enum import AdMode, AdScreenPosition, AdStatus
from utils.pagination import StandardPagination
from utils.responses import APIResponse

logger = logging.getLogger(__name__)


class AdvertisementViewSet(viewsets.ModelViewSet):
    """Advertiser-facing campaign management."""

    permission_classes = [IsAdminUser]
    pagination_class = StandardPagination
    pagination_message = "Advertisements fetched successfully."

    def get_queryset(self):
        queryset = Advertisement.objects.filter(is_deleted=False)
        user = self.request.user
        # Staff review every advert; advertisers only ever see their own.
        if not user.is_staff:
            queryset = queryset.filter(advertiser=user)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset.select_related("advertiser").prefetch_related(
            "creatives__media", "placements"
        )

    def get_serializer_class(self):
        if self.action == "create":
            return AdvertisementCreateSerializer
        if self.action in ("update", "partial_update"):
            return AdvertisementUpdateSerializer
        return AdvertisementSerializer

    def _get_owned(self, pk) -> Advertisement:
        return AdvertisementService.get_for_advertiser(
            advert_id=pk, user=self.request.user
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is None:
            return APIResponse.success(
                data=AdvertisementSerializer(queryset, many=True).data
            )
        return paginator.get_paginated_response(
            AdvertisementSerializer(page, many=True).data
        )

    def retrieve(self, request, *args, **kwargs):
        advert = self._get_owned(kwargs.get("pk"))
        return APIResponse.success(data=AdvertisementSerializer(advert).data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        advert = AdvertisementService.create(
            advertiser=request.user, validated_data=serializer.validated_data
        )
        return APIResponse.success(
            message="Advertisement created as a draft.",
            data=AdvertisementSerializer(advert).data,
            status_code=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        advert = self._get_owned(kwargs.get("pk"))
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        advert = AdvertisementService.update(
            advert=advert, validated_data=serializer.validated_data
        )
        return APIResponse.success(
            message="Advertisement updated.",
            data=AdvertisementSerializer(advert).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        advert = self._get_owned(kwargs.get("pk"))
        AdvertisementService.delete(advert=advert)
        return APIResponse.success(message="Advertisement deleted.")    

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        advert = AdvertisementService.submit_for_review(advert=self._get_owned(pk))
        return APIResponse.success(
            message="Advertisement submitted for review.",
            data=AdvertisementSerializer(advert).data,
        )

    @action(detail=True, methods=["post"], url_path="pause")
    def pause(self, request, pk=None):
        advert = AdvertisementService.pause(advert=self._get_owned(pk))
        return APIResponse.success(
            message="Advertisement paused.",
            data=AdvertisementSerializer(advert).data,
        )

    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, pk=None):
        advert = AdvertisementService.resume(advert=self._get_owned(pk))
        return APIResponse.success(
            message="Advertisement resumed.",
            data=AdvertisementSerializer(advert).data,
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        advert = AdvertisementService.cancel(advert=self._get_owned(pk))
        return APIResponse.success(
            message="Advertisement cancelled.",
            data=AdvertisementSerializer(advert).data,
        )

    @action(detail=True, methods=["get"], url_path="metrics")
    def metrics(self, request, pk=None):
        advert = self._get_owned(pk)
        daily = advert.daily_metrics.all()[:90]
        return APIResponse.success(
            message="Advertisement metrics fetched successfully.",
            data={
                "impressions": advert.impressions_count,
                "clicks": advert.clicks_count,
                "conversions": advert.conversions_count,
                "click_through_rate": advert.click_through_rate,
                "amount_spent": str(advert.amount_spent),
                "budget_amount": str(advert.budget_amount),
                "daily": AdDailyMetricSerializer(daily, many=True).data,
            },
        )

    @action(detail=True, methods=["post"], url_path="review",
            permission_classes=[IsAdminUser])
    def review(self, request, pk=None):
        serializer = AdReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        advert = Advertisement.objects.filter(pk=pk, is_deleted=False).first()
        if advert is None:
            return APIResponse.error(
                message="Advertisement not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if serializer.validated_data["action"] == "approve":
            advert = AdvertisementService.approve(advert=advert, reviewer=request.user)
            message = "Advertisement approved."
        else:
            advert = AdvertisementService.reject(
                advert=advert,
                reviewer=request.user,
                reason=serializer.validated_data["reason"],
            )
            message = "Advertisement rejected."

        return APIResponse.success(
            message=message, data=AdvertisementSerializer(advert).data
        )


class AdServeView(APIView):
    """What the mobile app calls to fill an advert slot.

    Public: adverts also render for signed-out users, who only ever match
    untargeted campaigns.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        mode = request.query_params.get("mode")
        if not mode:
            return APIResponse.error(
                message="mode query parameter is required.",
                data={"valid_modes": [m.value for m in AdMode]},
            )
        if mode not in {m.value for m in AdMode}:
            return APIResponse.error(
                message=f"Unknown advert mode '{mode}'.",
                data={"valid_modes": [m.value for m in AdMode]},
            )

        screen_position = request.query_params.get("screen_position") or None
        if screen_position and screen_position not in {p.value for p in AdScreenPosition}:
            return APIResponse.error(
                message=f"Unknown screen position '{screen_position}'.",
                data={"valid_positions": [p.value for p in AdScreenPosition]},
            )

        try:
            limit = max(1, min(int(request.query_params.get("limit", 1)), 5))
        except (TypeError, ValueError):
            limit = 1

        viewer = request.user if request.user.is_authenticated else None
        placements = AdDeliveryService.select(
            mode=mode, viewer=viewer, screen_position=screen_position, limit=limit,
        )

        return APIResponse.success(
            message="Adverts fetched successfully.",
            data=AdServeSerializer(placements, many=True, context={"request": request}).data,
        )


class AdEventView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AdEventCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from advertisements.tasks import record_ad_event

        record_ad_event.delay(
            advertisement_id=str(data["advertisement_id"]),
            event_type=data["event_type"],
            user_id=str(request.user.pk) if request.user.is_authenticated else None,
            placement_id=str(data["placement_id"]) if data.get("placement_id") else None,
            device_id=data.get("device_id", ""),
            dedupe_key=data.get("dedupe_key", ""),
            metadata=data.get("metadata") or {},
        )

        return APIResponse.success(
            message="Event recorded.",
            status_code=status.HTTP_202_ACCEPTED,
        )


class AdOptionsView(APIView):
    """Vocabulary for the advert-builder UI."""

    permission_classes = [AllowAny]

    def get(self, request):
        from utils.enum import (
            AdAudienceGender,
            AdCallToAction,
            AdObjective,
            AdPricingModel,
        )

        def as_options(enum_cls):
            return [
                {"value": value, "label": label}
                for value, label in enum_cls.choices()
            ]

        return APIResponse.success(
            message="Advert options fetched successfully.",
            data={
                "modes": as_options(AdMode),
                "screen_positions": as_options(AdScreenPosition),
                "objectives": as_options(AdObjective),
                "calls_to_action": as_options(AdCallToAction),
                "pricing_models": as_options(AdPricingModel),
                "genders": as_options(AdAudienceGender),
                "statuses": as_options(AdStatus),
            },
        )
