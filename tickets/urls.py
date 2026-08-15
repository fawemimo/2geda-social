from django.urls import path
from rest_framework.routers import DefaultRouter

from tickets import views

app_name = "tickets"

router = DefaultRouter()
router.register(r"categories", views.EventCategoryViewSet, basename="event-category")
router.register(r"events", views.EventViewSet, basename="event")
router.register(r"disputes", views.DisputeViewSet, basename="dispute")

urlpatterns = [
    path("sellers/apply/", views.SellerApplyView.as_view(), name="seller-apply"),
    path("sellers/me/", views.SellerProfileView.as_view(), name="seller-me"),
    path(
        "sellers/me/transactions/",
        views.SellerTransactionView.as_view(),
        name="seller-transactions",
    ),
    path(
        "sellers/me/payouts/",
        views.SellerPayoutView.as_view(),
        name="seller-payouts",
    ),
    path(
        "sellers/me/report/download/",
        views.SellerReportDownloadView.as_view(),
        name="seller-report-download",
    ),
    path(
        "admin/sellers/<uuid:pk>/review/",
        views.SellerApprovalView.as_view(),
        name="seller-review",
    ),
    path(
        "buy/initialize/",
        views.TicketPurchaseInitView.as_view(),
        name="purchase-initialize",
    ),
    path(
        "buy/verify/",
        views.TicketPurchaseVerifyView.as_view(),
        name="purchase-verify",
    ),
    path(
        "buy/my-tickets/",
        views.MyTicketsView.as_view(),
        name="my-tickets",
    ),
    path(
        "tickets/verify/<str:code>/",
        views.verify_ticket_code,
        name="ticket-code-verify",
    ),
    path(
        "events/<uuid:pk>/report/",
        views.EventReportView.as_view(),
        name="event-report",
    ),
    path(
        "events/<uuid:pk>/report/download/",
        views.EventReportDownloadView.as_view(),
        name="event-report-download",
    ),
    path(
        "reports/seller/",
        views.SellerReportView.as_view(),
        name="seller-report",
    ),
    # Gateway-neutral endpoint; point new gateway configuration here.
    path(
        "webhook/payment/",
        views.payment_webhook,
        name="payment-webhook",
    ),
    # Kept so an existing Paystack dashboard configuration keeps working.
    path(
        "webhook/paystack/",
        views.payment_webhook,
        name="paystack-webhook",
    ),
]

urlpatterns += router.urls
