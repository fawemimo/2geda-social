from django.urls import path
from chats.api_views import DeclineCallView

app_name = "chats"

urlpatterns = [
    path("calls/decline/", DeclineCallView.as_view(), name="call-decline"),
]
