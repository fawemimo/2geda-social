from django.urls import path
from rest_framework.routers import DefaultRouter

from advertisements import views

app_name = "advertisements"

router = DefaultRouter()
router.register(r"", views.AdvertisementViewSet, basename="advertisement")

urlpatterns = [
    # Delivery + telemetry come first so they are not shallowed by the router's
    # detail route.
    path("serve/", views.AdServeView.as_view(), name="ad-serve"),
    path("events/", views.AdEventView.as_view(), name="ad-event"),
    path("options/", views.AdOptionsView.as_view(), name="ad-options"),
]

urlpatterns += router.urls
