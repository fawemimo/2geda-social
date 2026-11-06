from django.urls import path

from polls.views import PollViewSet, poll_payment_webhook

app_name = "polls"

urlpatterns = [
    path("", PollViewSet.as_view({"get": "list", "post": "create"}), name="poll-list"),
    path(
        "<uuid:pk>/",
        PollViewSet.as_view(
            {
                "get": "retrieve",
                "put": "update",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="poll-detail",
    ),
    path("<uuid:pk>/vote/", PollViewSet.as_view({"post": "vote"}), name="poll-vote"),
    path("<uuid:pk>/vote/pay/", PollViewSet.as_view({"post": "initialize_vote_payment"}), name="poll-vote-pay"),
    path("<uuid:pk>/vote/status/", PollViewSet.as_view({"get": "vote_payment_status"}), name="poll-vote-status"),
    path("<uuid:pk>/unvote/", PollViewSet.as_view({"post": "unvote"}), name="poll-unvote"),
    path("<uuid:pk>/close/", PollViewSet.as_view({"post": "close"}), name="poll-close"),
    path("<uuid:pk>/results/", PollViewSet.as_view({"get": "results"}), name="poll-results"),
    path("<uuid:pk>/analytics/", PollViewSet.as_view({"get": "analytics"}), name="poll-analytics"),
    path("webhook/payment/", poll_payment_webhook, name="poll-payment-webhook"),
]
