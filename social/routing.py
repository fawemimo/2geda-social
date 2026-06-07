from django.urls import re_path

from social.consumers import FeedConsumer, PostConsumer

websocket_urlpatterns = [
    re_path(r"ws/posts/(?P<post_id>[0-9a-f-]+)/$", PostConsumer.as_asgi()),
    re_path(r"ws/feed/$", FeedConsumer.as_asgi()),
]
