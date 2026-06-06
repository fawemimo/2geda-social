from __future__ import annotations

import logging
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from notifications.models import (
    NOTIFICATION_CATEGORY_MAP,
    Notification,
    NotificationAttachment,
    NotificationAttachmentType,
    NotificationBatch,
    NotificationCategory,
    NotificationMute,
    NotificationPreference,
)
from notifications.services.dto import CreateNotificationDTO, MuteActorDTO, MuteSourceDTO, UpdatePreferenceDTO
from utils.enum import NotificationMuteType, NotificationPriority

logger = logging.getLogger(__name__)

# Max actors kept in a batch preview
BATCH_PREVIEW_LIMIT = 3

# How many notifications to return in a single inbox page
INBOX_PAGE_SIZE = 20



class NotificationService:
    """
    Creates, fetches, and mutates notification records.

    Does NOT: dispatch WebSocket messages, send push notifications,
              or touch the Celery queue. Those belong in NotificationDispatcher.
    """


    @classmethod
    @transaction.atomic
    def create(cls, dto: CreateNotificationDTO) -> Notification:
        """
        Create a Notification (and optional attachment) from a DTO.

        Steps:
          1. Derive the category from the notification_type.
          2. Check if the recipient has muted this actor/category.
          3. Persist the Notification.
          4. Persist the image attachment if provided.
          5. Update or create the batch record for grouped display.

        Returns the saved Notification instance.
        Raises ValueError if notification_type is invalid.
        """
        notification_type = dto.notification_type
        if notification_type not in NOTIFICATION_CATEGORY_MAP:
            raise ValueError(f"Unknown notification_type: {notification_type!r}")

        category = NOTIFICATION_CATEGORY_MAP[notification_type]

        #  Preference gate
        is_urgent = dto.priority in (
            NotificationPriority.HIGH.value,
            NotificationPriority.URGENT.value,
        )
        if not is_urgent:
            if cls._is_muted_by_preference(dto.recipient_id, category):
                logger.debug(
                    "Notification suppressed by preference | recipient=%s category=%s",
                    dto.recipient_id,
                    category,
                )
                # Still create the record so it appears in "muted" inbox tab
                # but mark it suppressed via a flag (we use is_sent_push=False
                # and let dispatcher skip it)

            if cls._is_muted_by_actor(dto.recipient_id, dto.actor_id):
                logger.debug(
                    "Notification suppressed: actor muted | recipient=%s actor=%s",
                    dto.recipient_id,
                    dto.actor_id,
                )
                return cls._create_suppressed(dto, category)

        #  Build group key 
        group_key = cls._build_group_key(notification_type, dto.source_id)

        #  Content type 
        content_type_obj = None
        if dto.source_model and dto.source_id:
            content_type_obj = ContentType.objects.get_for_model(dto.source_model)

        notification = Notification.objects.create(
            recipient_id=dto.recipient_id,
            actor_id=dto.actor_id,
            notification_type=notification_type,
            category=category,
            priority=dto.priority,
            content_type=content_type_obj,
            object_id=dto.source_id,
            title=dto.title,
            body=dto.body,
            action_url=dto.action_url,
            metadata=dto.metadata,
            group_key=group_key,
        )

        #  Optional image attachment 
        if dto.image_cdn_url:
            NotificationAttachment.objects.create(
                notification=notification,
                attachment_type=NotificationAttachmentType.IMAGE,
                cdn_url=dto.image_cdn_url,
                alt_text=dto.image_alt_text,
                width_px=dto.image_width,
                height_px=dto.image_height,
                position=0,
            )

        #  Batch upsert 
        if group_key:
            cls._upsert_batch(
                recipient_id=dto.recipient_id,
                group_key=group_key,
                notification=notification,
                actor_id=dto.actor_id
            )

        logger.info(
            "Notification created | id=%s type=%s recipient=%s",
            notification.id,
            notification_type,
            dto.recipient_id,
        )
        return notification

    #  Read / Inbox queries ─

    @classmethod
    def get_inbox(
        cls,
        user_id: str,
        category: Optional[str] = None,
        unread_only: bool = False,
        cursor_created_at: Optional[object] = None,
        page_size: int = INBOX_PAGE_SIZE,
    ) -> QuerySet:
        """
        Return the user's notification inbox as a QuerySet.
        Supports filtering by category and unread-only.
        Cursor pagination: pass the created_at of the last seen item.
        """
        qs = (
            Notification.objects.filter(recipient_id=user_id, is_deleted=False)
            .select_related("actor")
            .prefetch_related("attachments")
            .order_by("-created_at")
        )

        if category:
            qs = qs.filter(category=category)
        if unread_only:
            qs = qs.filter(is_read=False)
        if cursor_created_at:
            qs = qs.filter(created_at__lt=cursor_created_at)

        return qs[:page_size]

    @classmethod
    def get_unread_count(cls, user_id: str) -> int:
        """
        Return the total unread notification count for a user.
        Uses the partial index on (recipient, is_read=False) — O(1) at scale.
        """
        return Notification.objects.filter(
            recipient_id=user_id,
            is_read=False,
            is_deleted=False,
        ).count()

    @classmethod
    def get_unread_count_by_category(cls, user_id: str) -> dict[str, int]:
        """Return unread counts per category for badge rendering."""
        from django.db.models import Count

        rows = (
            Notification.objects.filter(
                recipient_id=user_id, is_read=False, is_deleted=False
            )
            .values("category")
            .annotate(count=Count("id"))
        )
        return {row["category"]: row["count"] for row in rows}

    #  Mark read / unread 

    @classmethod
    def mark_read(cls, notification_id: str, user_id: str) -> Notification:
        """Mark a single notification as read. Scoped to the requesting user."""
        notif = cls._get_owned_notification(notification_id, user_id)
        notif.mark_as_read()
        return notif

    @classmethod
    def mark_unread(cls, notification_id: str, user_id: str) -> Notification:
        """Mark a single notification as unread."""
        notif = cls._get_owned_notification(notification_id, user_id)
        notif.mark_as_unread()
        return notif

    @classmethod
    def mark_all_read(cls, user_id: str, category: Optional[str] = None) -> int:
        """
        Mark all (or all within a category) as read.
        Returns the count of rows updated.
        """
        qs = Notification.objects.filter(
            recipient_id=user_id,
            is_read=False,
            is_deleted=False,
        )
        if category:
            qs = qs.filter(category=category)

        count = qs.update(is_read=True, read_at=timezone.now())
        logger.info("Marked %d notifications read for user=%s", count, user_id)
        return count

    #  Delete ─

    @classmethod
    def delete_notification(cls, notification_id: str, user_id: str) -> None:
        """Soft-delete a notification. Scoped to the owning user."""
        notif = cls._get_owned_notification(notification_id, user_id)
        notif.delete()  # SoftDeleteMixin.delete()

    @classmethod
    def delete_all(cls, user_id: str, category: Optional[str] = None) -> int:
        """
        Soft-delete all notifications (or all in a category).
        Returns count deleted.
        """
        qs = Notification.objects.filter(
            recipient_id=user_id,
            is_deleted=False,
        )
        if category:
            qs = qs.filter(category=category)

        count = qs.count()
        qs.update(is_deleted=True, deleted_at=timezone.now())
        logger.info("Deleted %d notifications for user=%s", count, user_id)
        return count

    #  Preferences ─

    @classmethod
    def update_preference(cls, dto: UpdatePreferenceDTO) -> NotificationPreference:
        """
        Upsert a NotificationPreference for a user/category pair.
        Absence of a row = default ON.
        """
        valid = {e.value for e in NotificationCategory}
        if dto.category not in valid:
            raise ValueError(f"Invalid category: {dto.category!r}")

        pref, _ = NotificationPreference.objects.update_or_create(
            user_id=dto.user_id,
            category=dto.category,
            defaults={
                "in_app_enabled": dto.in_app_enabled,
                "push_enabled": dto.push_enabled,
                "email_enabled": dto.email_enabled,
            },
        )
        return pref

    @classmethod
    def get_preferences(cls, user_id: str) -> QuerySet:
        """Return all saved preferences for a user."""
        return NotificationPreference.objects.filter(user_id=user_id)

    #  Mutes 

    @classmethod
    def mute_actor(cls, dto: MuteActorDTO) -> NotificationMute:
        """Mute all notifications from a specific actor."""
        mute, _ = NotificationMute.objects.update_or_create(
            user_id=dto.user_id,
            mute_type=NotificationMuteType.ACTOR.value,
            muted_actor_id=dto.actor_id,
            defaults={"expires_at": dto.expires_at},
        )
        return mute

    @classmethod
    def unmute_actor(cls, user_id: str, actor_id: str) -> None:
        """Remove a specific actor mute."""
        NotificationMute.objects.filter(
            user_id=user_id,
            mute_type=NotificationMuteType.ACTOR,
            muted_actor_id=actor_id,
        ).delete()

    @classmethod
    def mute_source(cls, dto: MuteSourceDTO) -> NotificationMute:
        """Mute notifications about a specific object (post, group, etc.)."""
        from django.apps import apps
        try:
            model = apps.get_model("social", dto.source_model)
        except LookupError:
            raise ValueError(f"Unknown source model: {dto.source_model!r}")
        if model is None:
            raise ValueError(f"Unknown source model: {dto.source_model!r}")
        ct = ContentType.objects.get_for_model(model)
        mute, _ = NotificationMute.objects.update_or_create(
            user_id=dto.user_id,
            mute_type=NotificationMuteType.SOURCE,
            content_type=ct,
            object_id=dto.source_id,
            defaults={"expires_at": dto.expires_at},
        )
        return mute

    @classmethod
    def get_mutes(cls, user_id: str) -> QuerySet:
        """Return all active mutes for a user."""
        return NotificationMute.objects.filter(
            user_id=user_id,
        ).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )

    #  Private helpers ─

    @classmethod
    def _get_owned_notification(
        cls, notification_id: str, user_id: str
    ) -> Notification:
        try:
            return Notification.objects.get(
                pk=notification_id,
                recipient_id=user_id,
                is_deleted=False,
            )
        except Notification.DoesNotExist:
            raise NotificationNotFoundError(
                f"Notification {notification_id} not found for user {user_id}."
            )

    @classmethod
    def _is_muted_by_preference(cls, user_id: str, category: str) -> bool:
        """Return True if the user has turned off in_app for this category."""
        try:
            pref = NotificationPreference.objects.get(
                user_id=user_id,
                category=category,
            )
            return not pref.in_app_enabled
        except NotificationPreference.DoesNotExist:
            return False  # absence = default ON

    @classmethod
    def _is_muted_by_actor(cls, user_id: str, actor_id: Optional[str]) -> bool:
        if not actor_id:
            return False
        return (
            NotificationMute.objects.filter(
                user_id=user_id,
                mute_type=NotificationMuteType.ACTOR,
                muted_actor_id=actor_id,
            )
            .filter(
                models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=timezone.now())
            )
            .exists()
        )

    @staticmethod
    def _build_group_key(notification_type: str, source_id: Optional[str]) -> str:
        """Build a stable group key for batch collapsing."""
        if source_id:
            return f"{notification_type}:{source_id}"
        return notification_type

    @classmethod
    def _upsert_batch(
        cls,
        recipient_id: str,
        group_key: str,
        notification: Notification,
        actor_id: Optional[str],
    ) -> NotificationBatch:
        """
        Create or update the batch record for a group_key.
        Keeps the first BATCH_PREVIEW_LIMIT actor IDs for preview.
        """
        existing = NotificationBatch.objects.filter(
            recipient_id=recipient_id,
            group_key=group_key,
        ).first()

        if existing:
            actor_ids = existing.actor_ids or []
            if actor_id and str(actor_id) not in actor_ids:
                actor_ids = [str(actor_id)] + actor_ids
                actor_ids = actor_ids[:BATCH_PREVIEW_LIMIT]

            NotificationBatch.objects.filter(pk=existing.pk).update(
                latest_notification=notification,
                actor_ids=actor_ids,
                total_count=F("total_count") + 1,
                is_read=False,
                last_event_at=timezone.now(),
            )
            existing.refresh_from_db()
            return existing

        return NotificationBatch.objects.create(
            recipient_id=recipient_id,
            group_key=group_key,
            latest_notification=notification,
            actor_ids=[str(actor_id)] if actor_id else [],
            total_count=1,
        )

    @classmethod
    def _create_suppressed(
        cls,
        dto: CreateNotificationDTO,
        category: str,
    ) -> Notification:
        """
        Create a notification that is suppressed from push/WS delivery.
        It still appears in the in-app inbox (muted tab).
        """
        content_type_obj = None
        if dto.source_model and dto.source_id:
            content_type_obj = ContentType.objects.get_for_model(dto.source_model)

        return Notification.objects.create(
            recipient_id=dto.recipient_id,
            actor_id=dto.actor_id,
            notification_type=dto.notification_type,
            category=category,
            priority=dto.priority,
            content_type=content_type_obj,
            object_id=dto.source_id,
            title=dto.title,
            body=dto.body,
            action_url=dto.action_url,
            metadata=dto.metadata,
            # Pre-mark as sent so dispatcher skips push/WS
            is_sent_push=True,
            is_sent_ws=True,
        )


class NotificationNotFoundError(Exception):
    default_http_status = 404


import django.db.models as models  # noqa: E402 — needed for Q() in helpers above
