from django.contrib import admin
from django.urls import include, path, re_path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from django.http import JsonResponse


schema_view = get_schema_view(
    openapi.Info(
        title="2geda Social API",
        default_version="v2",
        description="2geda Social API Documentation",
        terms_of_service="https://www.google.com/policies/terms/",
        contact=openapi.Contact(email="contact@snippets.local"),
        license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

def status_check(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path('admin/', admin.site.urls),
    path("status/", status_check),
    path("prometheus/", include("django_prometheus.urls")),
    path('api/v2/accounts/', include('accounts.urls', namespace='accounts')),
    path('api/v2/chats/', include('chats.urls', namespace='chats')),
    path('api/v2/social/', include('social.urls', namespace='social')),
    path('api/v2/notifications/', include('notifications.urls', namespace='notifications')),
    path('api/v2/medias/', include('medias.urls', namespace='medias')),
    path('api/v2/displays/', include('displays.urls', namespace='displays')),
    path('api/v2/polls/', include('polls.urls', namespace='polls')),
    path('api/v2/tickets/',include('tickets.urls', namespace='tickets')),
    path('api/v2/docs/swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='swagger-ui'),
    path('api/v2/docs/redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='redoc'),
    re_path(r'^api/v2/docs/openapi(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema'),
]
