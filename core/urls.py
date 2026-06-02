"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
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
    path('api/v2/accounts/', include('accounts.urls', namespace='accounts')),
    path('api/v2/chats/', include('chats.urls', namespace='chats')),
    path('api/v2/docs/swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='swagger-ui'),
    path('api/v2/docs/redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='redoc'),
    # path('api/docs/swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='swagger-ui'),
    # path('api/docs/redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='redoc'),
]
