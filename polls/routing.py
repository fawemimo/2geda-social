from django.urls import re_path

from polls.consumers import PollConsumer

websocket_urlpatterns = [
    re_path(r"ws/polls/(?P<poll_id>[0-9a-f-]+)/$", PollConsumer.as_asgi()),
]
