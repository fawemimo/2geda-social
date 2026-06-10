from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from django.utils import timezone

from accounts.services.exceptions import PermissionDeniedError
from displays.models import Display, DisplayComment
from displays.serializers import (
    DisplayCommentCreateSerializer,
    DisplayCommentSerializer,
    DisplayCreateSerializer,
    DisplayListSerializer,
)
from displays.services import DisplayService
from utils.pagination import StandardPagination
from utils.responses import APIResponse


class DisplayViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    pagination_message = "Displays fetched successfully."

    def get_queryset(self):
        now = timezone.now()
        return Display.objects.filter(
            is_deleted=False, expires_at__gt=now,
        ).select_related(
            "author", "media",
        ).order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return DisplayCreateSerializer
        return DisplayListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        if data.get("media_id"):
            from medias.models import Media
            try:
                data["media"] = Media.objects.get(pk=data.pop("media_id"))
            except Media.DoesNotExist:
                return APIResponse.error(message="Media not found.", status_code=404)

        if data.get("reshare_of"):
            try:
                original = Display.objects.get(
                    pk=data.pop("reshare_of"), is_deleted=False,
                )
                data["reshare_of"] = original
            except Display.DoesNotExist:
                return APIResponse.error(message="Display to reshare not found.", status_code=404)

        display = DisplayService.create(author=request.user, validated_data=data)
        return APIResponse.success(
            message="Display created successfully.",
            data=DisplayListSerializer(display, context={"request": request}).data,
            status_code=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        DisplayService.record_view(display=instance, user=request.user if request.user.is_authenticated else None)
        serializer = self.get_serializer(instance)
        return APIResponse.success(data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            DisplayService.delete(instance=instance, user=request.user)
        except PermissionDeniedError as exc:
            return APIResponse.error(message=exc.message, status_code=exc.status_code)
        return APIResponse.success(message="Display deleted successfully.")

    @action(detail=True, methods=["get"])
    def viewers(self, request, pk=None):
        display = self.get_object()
        viewers = display.views.select_related("user").order_by("-created_at")[:50]
        data = [
            {
                "user_id": str(v.user_id) if v.user_id else None,
                "viewed_at": v.created_at,
            }
            for v in viewers
        ]
        return APIResponse.success(data=data)

    @action(detail=True, methods=["post"])
    def like(self, request, pk=None):
        display = self.get_object()
        result = DisplayService.toggle_like(display=display, user=request.user)
        return APIResponse.success(
            message="Like toggled successfully.",
            data=result,
        )

    @action(detail=False, methods=["get"])
    def my(self, request):
        now = timezone.now()
        qs = Display.objects.filter(
            author=request.user, is_deleted=False, expires_at__gt=now,
        ).select_related("media").order_by("-created_at")
        serializer = self.get_serializer(qs, many=True)
        return APIResponse.success(data=serializer.data)

    @action(detail=False, methods=["get"])
    def feed(self, request):
        from accounts.models import Follow

        now = timezone.now()
        following_ids = list(
            Follow.objects.filter(
                follower=request.user, status="accepted",
            ).values_list("following_id", flat=True)
        )
        qs = Display.objects.filter(
            author_id__in=following_ids + [request.user.id],
            is_deleted=False, expires_at__gt=now, visibility="public",
        ).select_related("author", "media").order_by("-created_at")
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return APIResponse.success(data=serializer.data)


class DisplayCommentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = DisplayCommentSerializer

    def get_queryset(self):
        display_id = self.kwargs.get("display_id")
        return DisplayComment.objects.filter(
            display_id=display_id, is_deleted=False,
        ).select_related("author").order_by("created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return DisplayCommentCreateSerializer
        return DisplayCommentSerializer

    def create(self, request, *args, **kwargs):
        display_id = self.kwargs.get("display_id")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            display = Display.objects.get(pk=display_id, is_deleted=False)
        except Display.DoesNotExist:
            return APIResponse.error(message="Display not found.", status_code=404)

        comment = DisplayComment.objects.create(
            display=display, author=request.user, body=serializer.validated_data["body"],
        )
        return APIResponse.success(
            message="Comment created.",
            data=DisplayCommentSerializer(comment, context={"request": request}).data,
            status_code=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.author != request.user:
            return APIResponse.error(message="You can only delete your own comments.", status_code=403)
        instance.delete()
        return APIResponse.success(message="Comment deleted.")
