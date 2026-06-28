import json

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.views import APIView

from tickets.models import (
    Dispute,
    Event,
    EventCategory,
    Payout,
    PaymentTransaction,
    SellerProfile,
    Ticket,
)
from tickets.serializers import (
    DisputeCreateSerializer,
    DisputeResolveSerializer,
    DisputeSerializer,
    EventCategorySerializer,
    EventListSerializer,
    EventSerializer,
    PayoutSerializer,
    PaymentTransactionSerializer,
    PriceTierReadSerializer,
    SellerApprovalSerializer,
    SellerApplicationSerializer,
    SellerProfileSerializer,
    TicketPurchaseInitializeSerializer,
    TicketPurchaseVerifySerializer,
    TicketSerializer,
)
from tickets.services.dispute_service import DisputeService
from tickets.services.event_service import EventService
from tickets.services.exceptions import (
    DisputeAlreadyResolved,
    InsufficientTickets,
    InvalidEventStatus,
    PaymentVerificationFailed,
    PricingMismatch,
    SellerNotApproved,
    SellerSuspended,
)
from tickets.services.payment_service import PaymentService
from tickets.services.report_service import ReportService
from tickets.services.seller_service import SellerService
from tickets.services.ticket_service import TicketService
from utils.enum import EventStatus, TicketStatus
from utils.responses import APIResponse


# ── Categories ────────────────────────────────────────────────────────────


class EventCategoryViewSet(viewsets.ModelViewSet):
    queryset = EventCategory.objects.filter(is_deleted=False, is_active=True).order_by("name")
    serializer_class = EventCategorySerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        serializer.save()


# ── Seller ──


class SellerApplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SellerApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = SellerService.apply(
                user=request.user,
                **serializer.validated_data,
            )
            return APIResponse.success(
                message="Seller application submitted successfully.",
                data=SellerProfileSerializer(profile).data,
                status_code=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return APIResponse.error(message=str(e))


class SellerProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = SellerService.get_for_user(request.user)
        if not profile:
            return APIResponse.error(
                message="Seller profile not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return APIResponse.success(
            data=SellerProfileSerializer(profile).data
        )

    def patch(self, request):
        profile = SellerService.get_for_user(request.user)
        if not profile:
            return APIResponse.error(
                message="Seller profile not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        serializer = SellerProfileSerializer(
            profile, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return APIResponse.success(
            message="Profile updated.",
            data=SellerProfileSerializer(profile).data,
        )


class SellerApprovalView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = get_object_or_404(SellerProfile, id=pk, is_deleted=False)
        serializer = SellerApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data["action"]
        try:
            if action == "approve":
                SellerService.approve(profile, request.user)
                msg = "Seller approved successfully."
            else:
                reason = serializer.validated_data.get("rejection_reason", "")
                SellerService.reject(profile, request.user, reason)
                msg = "Seller rejected."
            return APIResponse.success(
                message=msg,
                data=SellerProfileSerializer(profile).data,
            )
        except Exception as e:
            return APIResponse.error(message=str(e))


# ── Events ──


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer

    def get_permissions(self):
        if self.action in ("public", "by_link", "price_tiers", "list", "retrieve"):
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = getattr(self.request, "user", None)
        if user and user.is_authenticated:
            profile = SellerService.get_for_user(user)
            if profile:
                return Event.objects.filter(
                    seller=profile, is_deleted=False
                ).select_related("seller", "category")
        return Event.objects.filter(
            status=EventStatus.PUBLISHED.value,
            is_deleted=False,
        ).select_related("seller", "category")

    def get_serializer_class(self):
        if self.action == "list":
            return EventListSerializer
        return EventSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return APIResponse.success(data=serializer.data)

    def perform_create(self, serializer):
        pass

    def _get_event_or_404(self, pk):
        try:
            event = Event.objects.get(id=pk, is_deleted=False)
        except Event.DoesNotExist:
            return None
        return event

    def _check_owner(self, request, event):
        profile = SellerService.get_for_user(request.user)
        if not profile or event.seller_id != profile.id:
            return None
        return profile

    def create(self, request, *args, **kwargs):
        profile = SellerService.get_for_user(request.user)
        try:
            SellerService.require_approved(profile)
        except (SellerNotApproved, SellerSuspended) as e:
            return APIResponse.error(
                message=e.message,
                code=e.code,
                status_code=e.status_code,
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event_data = dict(serializer.validated_data)
        price_tiers = request.data.get("price_tiers", [])
        if price_tiers:
            event_data["price_tiers"] = price_tiers
        try:
            event = EventService.create(profile, **event_data)
            return APIResponse.success(
                message="Event created.",
                data=EventSerializer(event).data,
                status_code=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return APIResponse.error(message=str(e))

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        event = self._get_event_or_404(pk)
        if not event:
            return APIResponse.error(
                message="Event not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        profile = self._check_owner(request, event)
        if not profile:
            return APIResponse.error(
                message="You do not own this event.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        try:
            event = EventService.publish(event, profile)
            return APIResponse.success(
                message="Event published.",
                data=EventSerializer(event).data,
            )
        except InvalidEventStatus as e:
            return APIResponse.error(message=e.message, code=e.code, status_code=e.status_code)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        event = self._get_event_or_404(pk)
        if not event:
            return APIResponse.error(
                message="Event not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        profile = self._check_owner(request, event)
        if not profile:
            return APIResponse.error(
                message="You do not own this event.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        try:
            event = EventService.cancel(event, profile)
            return APIResponse.success(
                message="Event cancelled.",
                data=EventSerializer(event).data,
            )
        except InvalidEventStatus as e:
            return APIResponse.error(message=e.message, code=e.code, status_code=e.status_code)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        event = self._get_event_or_404(kwargs.get("pk"))
        if not event:
            return APIResponse.error(
                message="Event not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        profile = self._check_owner(request, event)
        if not profile:
            return APIResponse.error(
                message="You do not own this event.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        serializer = self.get_serializer(event, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_update(serializer)
            return APIResponse.success(
                message="Event updated.",
                data=EventSerializer(serializer.instance).data,
            )
        except InvalidEventStatus as e:
            return APIResponse.error(message=e.message, code=e.code, status_code=e.status_code)

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        event = self._get_event_or_404(kwargs.get("pk"))
        if not event:
            return APIResponse.error(
                message="Event not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        profile = self._check_owner(request, event)
        if not profile:
            return APIResponse.error(
                message="You do not own this event.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        event.delete()
        return APIResponse.success(message="Event deleted.")

    @action(detail=False, methods=["get"])
    def public(self, request):
        events = EventService.get_public_events()
        page = self.paginate_queryset(events)
        if page is not None:
            serializer = EventListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = EventListSerializer(events, many=True)
        return APIResponse.success(data=serializer.data)

    @action(detail=False, methods=["get"])
    def by_link(self, request):
        link = request.query_params.get("link")
        if not link:
            return APIResponse.error(message="link query parameter is required.")
        event = EventService.get_by_link(link)
        if not event:
            return APIResponse.error(
                message="Event not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return APIResponse.success(data=EventSerializer(event).data)

    @action(detail=True, methods=["get"])
    def price_tiers(self, request, pk=None):
        event = self._get_event_or_404(pk)
        if not event:
            return APIResponse.error(
                message="Event not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        tiers = event.price_tiers.filter(is_active=True)
        serializer = PriceTierReadSerializer(tiers, many=True)
        return APIResponse.success(data=serializer.data)


# ── Tickets / Purchase ─────────────────────────────────────────────────────


class TicketPurchaseInitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TicketPurchaseInitializeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event = get_object_or_404(
            Event,
            id=serializer.validated_data["event_id"],
            status=EventStatus.PUBLISHED.value,
            is_deleted=False,
        )

        try:
            result = TicketService.initialize_purchase(
                buyer=request.user,
                event=event,
                price_tier_id=str(serializer.validated_data["price_tier_id"]),
                quantity=serializer.validated_data["quantity"],
            )
            return APIResponse.success(
                message="Purchase initialized. Redirect to Paystack.",
                data=result,
                status_code=status.HTTP_201_CREATED,
            )
        except (InsufficientTickets, PricingMismatch) as e:
            return APIResponse.error(
                message=e.message,
                code=e.code,
                status_code=e.status_code,
            )


class TicketPurchaseVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TicketPurchaseVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = TicketService.verify_purchase(
                serializer.validated_data["reference"]
            )
            return APIResponse.success(
                message="Purchase verified successfully.",
                data=result,
            )
        except PaymentVerificationFailed as e:
            return APIResponse.error(
                message=e.message,
                code=e.code,
                status_code=e.status_code,
            )


class MyTicketsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tickets = TicketService.get_buyer_tickets(request.user)
        serializer = TicketSerializer(tickets, many=True)
        return APIResponse.success(data=serializer.data)


# Disputes 


class DisputeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = DisputeSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Dispute.objects.filter(is_deleted=False).select_related(
                "ticket", "event", "buyer", "seller", "assigned_moderator"
            )
        profile = SellerService.get_for_user(user)
        if profile:
            return Dispute.objects.filter(
                seller=profile, is_deleted=False
            ).select_related("ticket", "event", "buyer")
        return Dispute.objects.filter(
            buyer=user, is_deleted=False
        ).select_related("ticket", "event", "seller")

    def create(self, request, *args, **kwargs):
        serializer = DisputeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket = get_object_or_404(
            Ticket,
            id=serializer.validated_data["ticket_id"],
            buyer=request.user,
            status=TicketStatus.SOLD.value,
            is_deleted=False,
        )

        try:
            dispute = DisputeService.open_dispute(
                buyer=request.user,
                ticket=ticket,
                reason=serializer.validated_data["reason"],
                description=serializer.validated_data["description"],
            )
            return APIResponse.success(
                message="Dispute opened.",
                data=DisputeSerializer(dispute).data,
                status_code=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return APIResponse.error(message=str(e))

    @action(detail=True, methods=["post"])
    def assign_moderator(self, request, pk=None):
        if not request.user.is_staff:
            return APIResponse.error(
                message="Only admins can assign moderators.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        dispute = self.get_object()
        try:
            dispute = DisputeService.assign_moderator(dispute, request.user)
            return APIResponse.success(
                message="Moderator assigned.",
                data=DisputeSerializer(dispute).data,
            )
        except DisputeAlreadyResolved as e:
            return APIResponse.error(
                message=e.message, code=e.code, status_code=e.status_code
            )

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        if not request.user.is_staff:
            return APIResponse.error(
                message="Only admins can resolve disputes.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        dispute = self.get_object()
        serializer = DisputeResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            dispute = DisputeService.resolve(
                dispute=dispute,
                moderator=request.user,
                resolution=serializer.validated_data["resolution"],
                notes=serializer.validated_data.get("notes", ""),
            )
            return APIResponse.success(
                message="Dispute resolved.",
                data=DisputeSerializer(dispute).data,
            )
        except DisputeAlreadyResolved as e:
            return APIResponse.error(
                message=e.message, code=e.code, status_code=e.status_code
            )


# ── Reports ─


class EventReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        event = get_object_or_404(Event, id=pk, is_deleted=False)
        profile = SellerService.get_for_user(request.user)
        if not profile or event.seller_id != profile.id:
            if not request.user.is_staff:
                return APIResponse.error(
                    message="You do not have access to this report.",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
        report = ReportService.event_sales_report(event)
        return APIResponse.success(data=report)


class EventReportDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        event = get_object_or_404(Event, id=pk, is_deleted=False)
        profile = SellerService.get_for_user(request.user)
        if not profile or event.seller_id != profile.id:
            if not request.user.is_staff:
                return APIResponse.error(
                    message="You do not have access.",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
        csv_file = ReportService.download_event_csv(event)
        response = StreamingHttpResponse(
            csv_file,
            content_type="text/csv",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="event_{event.id}_report.csv"'
        )
        return response


class SellerReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = SellerService.get_for_user(request.user)
        if not profile:
            return APIResponse.error(
                message="Seller profile not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        report = ReportService.seller_aggregate_report(profile)
        return APIResponse.success(data=report)


class SellerReportDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = SellerService.get_for_user(request.user)
        if not profile:
            return APIResponse.error(
                message="Seller profile not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        csv_file = ReportService.download_full_transaction_report(profile)
        response = StreamingHttpResponse(
            csv_file,
            content_type="text/csv",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="seller_{profile.id}_transactions.csv"'
        )
        return response


# ── Seller Financials ──────────────────────────────────────────────────────


class SellerTransactionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = SellerService.get_for_user(request.user)
        if not profile:
            return APIResponse.success(data=[])
        transactions = PaymentTransaction.objects.filter(
            seller=profile,
        ).select_related("event", "buyer").order_by("-created_at")
        serializer = PaymentTransactionSerializer(transactions, many=True)
        return APIResponse.success(data=serializer.data)


class SellerPayoutView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = SellerService.get_for_user(request.user)
        if not profile:
            return APIResponse.success(data=[])
        payouts = Payout.objects.filter(
            seller=profile,
        ).order_by("-created_at")
        serializer = PayoutSerializer(payouts, many=True)
        return APIResponse.success(data=serializer.data)


# ── Paystack Webhook ───────────────────────────────────────────────────────


@api_view(["POST"])
@permission_classes([AllowAny])
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature", "")
    payload_body = request.body

    if not PaymentService.verify_webhook_signature(payload_body, signature):
        return APIResponse.error(
            message="Invalid signature.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    data = json.loads(payload_body)
    event = data.get("event", "")
    event_data = data.get("data", {})

    try:
        PaymentService.handle_webhook(event, event_data)
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Paystack webhook error: %s", e)

    return APIResponse.success(message="Webhook received.")


# ── Ticket verification (public) ────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([AllowAny])
def verify_ticket_code(request, code):
    ticket = TicketService.verify_ticket_code(code)
    if not ticket:
        return APIResponse.error(
            message="Ticket not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return APIResponse.success(
        data={
            "ticket_code": ticket.ticket_code,
            "status": ticket.status,
            "event_title": ticket.event.title,
            "event_date": ticket.event.starts_at.isoformat(),
            "buyer_username": ticket.buyer.username,
            "is_verified": ticket.is_verified,
            "price_paid": str(ticket.price_paid),
            "purchased_at": ticket.purchased_at.isoformat() if ticket.purchased_at else None,
        }
    )
