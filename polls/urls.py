from django.urls import path

from polls.views import PollViewSet

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
    path("<uuid:pk>/vote/confirm/", PollViewSet.as_view({"post": "verify_vote_payment"}), name="poll-vote-confirm"),
    path("<uuid:pk>/unvote/", PollViewSet.as_view({"post": "unvote"}), name="poll-unvote"),
    path("<uuid:pk>/close/", PollViewSet.as_view({"post": "close"}), name="poll-close"),
    path("<uuid:pk>/results/", PollViewSet.as_view({"get": "results"}), name="poll-results"),
    path("<uuid:pk>/analytics/", PollViewSet.as_view({"get": "analytics"}), name="poll-analytics"),
]
