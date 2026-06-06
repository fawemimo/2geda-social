from __future__ import annotations

import logging

from django.db import models
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.models import UserDevice
from notifications.models import Notification, NotificationMute, NotificationPreference
from notifications.serializers import DeviceTokenSerializer, MuteActorSerializer, MuteSerializer, MuteSourceSerializer, NotificationSerializer, PreferenceSerializer, PreferenceUpdateSerializer
from notifications.services.dto import MuteActorDTO, MuteSourceDTO, UpdatePreferenceDTO
from notifications.services.notification_services import NotificationService
from utils.pagination import StandardPagination
from utils.responses import APIResponse

logger = logging.getLogger(__name__)


class NotificationInboxView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get(self, request):
        category = request.query_params.get("category")
        unread_only = request.query_params.get("unread_only", "").lower() == "true"

        qs = Notification.objects.filter(
            recipient=request.user, is_deleted=False,
        ).select_related("actor").order_by("-created_at")

        if category:
            qs = qs.filter(category=category)
        if unread_only:
            qs = qs.filter(is_read=False)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = NotificationSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = NotificationSerializer(qs, many=True)
        return APIResponse.success(data=serializer.data)


class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(
            recipient=request.user, is_read=False, is_deleted=False,
        ).count()
        return APIResponse.success(data={"unread_count": count})


class UnreadCountByCategoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(
            recipient=request.user, is_read=False, is_deleted=False,
        )
        counts = dict(qs.values_list("category").annotate(count=models.Count("id")))
        return APIResponse.success(data=counts)



#  Read / Unread



class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            notif = Notification.objects.get(
                pk=pk, recipient=request.user, is_deleted=False,
            )
            notif.mark_as_read()
            return APIResponse.success(message="Notification marked as read.")
        except Notification.DoesNotExist:
            return APIResponse.error(message="Notification not found.", status_code=404)


class MarkUnreadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            notif = Notification.objects.get(
                pk=pk, recipient=request.user, is_deleted=False,
            )
            notif.mark_as_unread()
            return APIResponse.success(message="Notification marked as unread.")
        except Notification.DoesNotExist:
            return APIResponse.error(message="Notification not found.", status_code=404)


class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        category = request.data.get("category")
        qs = Notification.objects.filter(
            recipient=request.user, is_read=False, is_deleted=False,
        )
        if category:
            qs = qs.filter(category=category)
        count = qs.update(is_read=True, read_at=timezone.now())
        return APIResponse.success(message=f"{count} notifications marked as read.")



#  Delete



class DeleteNotificationView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            notif = Notification.objects.get(
                pk=pk, recipient=request.user, is_deleted=False,
            )
            notif.delete()
            return APIResponse.success(message="Notification deleted.")
        except Notification.DoesNotExist:
            return APIResponse.error(message="Notification not found.", status_code=404)


class DeleteAllNotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        category = request.query_params.get("category")
        qs = Notification.objects.filter(
            recipient=request.user, is_deleted=False,
        )
        if category:
            qs = qs.filter(category=category)
        count = list(qs.values_list("pk", flat=True))
        Notification.objects.filter(pk__in=count).delete()
        return APIResponse.success(message=f"{len(count)} notifications deleted.")



#  Preferences



class PreferenceListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        prefs = NotificationPreference.objects.filter(user=request.user)
        serializer = PreferenceSerializer(prefs, many=True)
        data = {p["category"]: p for p in serializer.data}
        return APIResponse.success(data=data)


class PreferenceUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        serializer = PreferenceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dto = UpdatePreferenceDTO(
            user_id=str(request.user.id),
            category=serializer.validated_data["category"],
            in_app_enabled=serializer.validated_data.get("in_app_enabled", True),
            push_enabled=serializer.validated_data.get("push_enabled", True),
            email_enabled=serializer.validated_data.get("email_enabled", False),
        )
        pref = NotificationService.update_preference(dto)
        return APIResponse.success(
            message="Preference updated.",
            data=PreferenceSerializer(pref).data,
        )


class MuteListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mutes = NotificationService.get_mutes(str(request.user.id))
        serializer = MuteSerializer(mutes, many=True)
        return APIResponse.success(data=serializer.data)


class MuteActorView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MuteActorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dto = MuteActorDTO(
            user_id=str(request.user.id),
            actor_id=str(serializer.validated_data["actor_id"]),
            expires_at=serializer.validated_data.get("expires_at"),
        )
        mute = NotificationService.mute_actor(dto)
        return APIResponse.success(
            message="Actor muted.",
            data=MuteSerializer(mute).data,
            status_code=status.HTTP_201_CREATED,
        )


class MuteSourceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MuteSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dto = MuteSourceDTO(
            user_id=str(request.user.id),
            source_model=serializer.validated_data["source_model"],
            source_id=str(serializer.validated_data["source_id"]),
            expires_at=serializer.validated_data.get("expires_at"),
        )
        mute = NotificationService.mute_source(dto)
        return APIResponse.success(
            message="Source muted.",
            data=MuteSerializer(mute).data,
            status_code=status.HTTP_201_CREATED,
        )


class UnmuteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            mute = NotificationMute.objects.get(pk=pk, user=request.user)
            mute.delete()
            return APIResponse.success(message="Unmuted successfully.")
        except NotificationMute.DoesNotExist:
            return APIResponse.error(message="Mute not found.", status_code=404)



#  Device tokens



class RegisterDeviceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device_fingerprint = serializer.validated_data.get("device_fingerprint", "")
        push_token = serializer.validated_data["device_token"]
        platform = serializer.validated_data.get("platform", "")
        if not device_fingerprint:
            return APIResponse.error(message="device_fingerprint is required.", status_code=400)
        device, created = UserDevice.objects.update_or_create(
            user=request.user,
            device_fingerprint=device_fingerprint,
            defaults={
                "push_token": push_token,
                "platform": platform,
                "push_token_updated_at": timezone.now(),
                "is_deleted": False,
                "deleted_at": None,
            },
        )
        return APIResponse.success(
            message="Device registered." if created else "Device updated.",
            data={"id": str(device.id)},
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class UnregisterDeviceView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        token = request.data.get("device_token") or request.query_params.get("device_token")
        if not token:
            return APIResponse.error(message="device_token is required.", status_code=400)
        updated = UserDevice.objects.filter(
            user=request.user, push_token=token, is_deleted=False,
        ).update(push_token="", push_token_updated_at=timezone.now())
        if updated:
            return APIResponse.success(message="Device unregistered.")
        return APIResponse.error(message="Device not found.", status_code=404)



