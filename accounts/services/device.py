from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from accounts.models import User, UserDevice

from .exceptions import NotFoundError, PermissionDeniedError, ValidationError


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DevicePayload:
    name: str
    platform: str
    device_fingerprint: str
    os_version: str = ""
    app_version: str = ""
    push_token: str = ""


class DeviceService:
    @transaction.atomic
    def register(
        self,
        *,
        user: User,
        payload: DevicePayload,
        ip_address: str | None = None,
    ) -> UserDevice:
        if not payload.device_fingerprint or not payload.platform:
            raise ValidationError("device_fingerprint and platform are required.", code="device_invalid")

        defaults = {
            "name": payload.name or "",
            "platform": payload.platform,
            "os_version": payload.os_version,
            "app_version": payload.app_version,
            "push_token": payload.push_token,
            "push_token_updated_at": timezone.now() if payload.push_token else None,
            "last_seen_at": timezone.now(),
            "last_ip": ip_address,
            "is_deleted": False,
            "deleted_at": None,
        }
        device, _ = UserDevice.objects.update_or_create(
            user=user, device_fingerprint=payload.device_fingerprint, defaults=defaults
        )
        return device

    def list_for_user(self, user: User) -> Iterable[UserDevice]:
        return (
            UserDevice.objects.filter(user=user, is_deleted=False)
            .only(
                "id", "name", "platform", "os_version", "app_version",
                "is_trusted", "last_seen_at", "last_ip", "created_at",
            )
            .order_by("-last_seen_at")
        )

    @transaction.atomic
    def update_push_token(
        self, *, user: User, device_id: str, push_token: str
    ) -> UserDevice:
        device = self._get_device(user=user, device_id=device_id)
        UserDevice.objects.filter(pk=device.pk).update(
            push_token=push_token,
            push_token_updated_at=timezone.now(),
        )
        device.push_token = push_token
        return device

    @transaction.atomic
    def touch(self, *, user: User, device_id: str, ip_address: str | None = None) -> None:
        UserDevice.objects.filter(pk=device_id, user=user, is_deleted=False).update(
            last_seen_at=timezone.now(),
            last_ip=ip_address,
        )

    @transaction.atomic
    def trust(self, *, user: User, device_id: str) -> UserDevice:
        device = self._get_device(user=user, device_id=device_id)
        UserDevice.objects.filter(pk=device.pk).update(
            is_trusted=True, trusted_at=timezone.now()
        )
        device.is_trusted = True
        return device

    @transaction.atomic
    def revoke(self, *, user: User, device_id: str) -> None:
        device = self._get_device(user=user, device_id=device_id)
        device.revoke()
        logger.info("Device revoked user=%s device=%s", user.pk, device.pk)

    @staticmethod
    def get_trusted_push_tokens(user: User) -> list[str]:
        return list(
            UserDevice.objects.filter(
                user=user, is_trusted=True,
            )
            .exclude(push_token="")
            .values_list("push_token", flat=True)
        )

    @staticmethod
    def _get_device(*, user: User, device_id: str) -> UserDevice:
        try:
            device = UserDevice.objects.get(pk=device_id, is_deleted=False)
        except UserDevice.DoesNotExist as exc:
            raise NotFoundError("Device not found.", code="device_not_found") from exc
        if device.user_id != user.pk:
            raise PermissionDeniedError("You cannot manage another user's device.")
        return device

