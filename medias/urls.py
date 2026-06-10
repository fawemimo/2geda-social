from django.urls import include, path
from rest_framework.routers import DefaultRouter

from medias import views

app_name = "medias"

router = DefaultRouter()
router.register("", views.MediaViewSet, basename="media")

urlpatterns = [
    path("upload/", views.MediaUploadView.as_view(), name="media-upload"),
    path("", include(router.urls)),
]
