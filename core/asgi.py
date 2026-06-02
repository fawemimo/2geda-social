"""
ASGI config for the core project.

Routes HTTP requests to Django and WebSocket connections to Channels consumers.
"""
import os

# Workaround for corrupted channels package in some environments.
import channels as _channels
if not hasattr(_channels, "DEFAULT_CHANNEL_LAYER"):
    _channels.DEFAULT_CHANNEL_LAYER = "default"

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

django_asgi = get_asgi_application()

import chats.routing  # noqa: E402
# import archive.notifications.routing  # noqa: E402

combined_routes = chats.routing.websocket_urlpatterns  # + archive.notifications.routing.websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi,
    "websocket": AuthMiddlewareStack(
        URLRouter(chats.routing.websocket_urlpatterns)
    ),
})

