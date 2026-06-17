"""
Notification system

Design notes:
  • actor_id / target_object stored as GenericForeignKey so any model
    (Post, Comment, User, etc.) can be the source without table sprawl.
  • Image attachments live in NotificationAttachment (not a nullable
    column on Notification) so the base table stays narrow and fast.
  • NotificationPreference is per (user, category) — one row per
    notification type the user has customised. Absence = default ON.
  • Soft-delete on Notification: "delete" hides from list, but the
    record is kept for audit and unread-count reconciliation.
  • Indexes are designed for the four hot queries:
      1. Inbox list:  recipient + is_read + created_at
      2. Unread count: recipient + is_read=False (partial)
      3. Actor feed:  actor + notification_type
      4. Category mute lookup: user + category
"""

from __future__ import annotations

import uuid
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from utils.enum import NotificationAttachmentType, NotificationCategory, NotificationMuteType, NotificationPriority, NotificationType
from utils.models import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin

# Maps every NotificationType to its NotificationCategory
NOTIFICATION_CATEGORY_MAP: dict[str, str] = {
    # Social
    NotificationType.POST_LIKED.value: NotificationCategory.SOCIAL.value,
    NotificationType.POST_COMMENTED.value: NotificationCategory.SOCIAL.value,
    NotificationType.POST_RESHARED.value: NotificationCategory.SOCIAL.value,
    NotificationType.COMMENT_LIKED.value: NotificationCategory.SOCIAL.value,
    NotificationType.COMMENT_REPLIED.value: NotificationCategory.SOCIAL.value,
    NotificationType.DISPLAY_CREATED.value: NotificationCategory.SOCIAL.value,
    # Following
    NotificationType.NEW_FOLLOWER.value: NotificationCategory.FOLLOWING.value,
    NotificationType.FOLLOW_REQUEST.value: NotificationCategory.FOLLOWING.value,
    NotificationType.FOLLOW_ACCEPTED.value: NotificationCategory.FOLLOWING.value,
    # Mention
    NotificationType.MENTION_POST.value: NotificationCategory.MENTION.value,
    NotificationType.MENTION_COMMENT.value: NotificationCategory.MENTION.value,
    # Chat
    NotificationType.NEW_MESSAGE.value: NotificationCategory.CHAT.value,
    NotificationType.GROUP_ADDED.value: NotificationCategory.CHAT.value,
    NotificationType.GROUP_REMOVED.value: NotificationCategory.CHAT.value,
    NotificationType.JOIN_REQUEST.value: NotificationCategory.CHAT.value,
    NotificationType.JOIN_APPROVED.value: NotificationCategory.CHAT.value,
    NotificationType.JOIN_REJECTED.value: NotificationCategory.CHAT.value,
    # System
    NotificationType.KYC_APPROVED.value: NotificationCategory.SYSTEM.value,
    NotificationType.KYC_REJECTED.value: NotificationCategory.SYSTEM.value,
    NotificationType.KYC_EXPIRING.value: NotificationCategory.SYSTEM.value,
    NotificationType.NEW_DEVICE_LOGIN.value: NotificationCategory.SYSTEM.value,
    NotificationType.PASSWORD_CHANGED.value: NotificationCategory.SYSTEM.value,
    NotificationType.ACCOUNT_SUSPENDED.value: NotificationCategory.SYSTEM.value,
    NotificationType.REFERRAL_JOINED.value: NotificationCategory.SYSTEM.value,
    # Marketing
    NotificationType.ANNOUNCEMENT.value: NotificationCategory.MARKETING.value,
    NotificationType.PROMOTION.value: NotificationCategory.MARKETING.value,
}



class Notification(BaseModel):
    """
    A single notification for one recipient.

    Read/unread state is tracked directly on this row (no separate join table)
    because read state is 1-to-1 per notification per user.

    Generic FK (content_type + object_id) points to the source object:
      - Post → post_liked, post_commented, post_reshared
      - Comment → comment_liked, comment_replied
      - User → new_follower, follow_request, follow_accepted
      - Message → new_message
      etc.

    actor is the User who triggered the notification (None for system events).
    recipient is always a single user.
    """

    # Who gets it
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )

    # Who triggered it (null for system/marketing)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_notifications",
        db_index=True,
    )

    # What type of event
    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        db_index=True,
    )
    category = models.CharField(
        max_length=15,
        choices=NotificationCategory.choices,
        db_index=True,
        help_text=_(
            "Derived from notification_type. Stored for fast preference lookup."
        ),
    )
    priority = models.CharField(
        max_length=8,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL.value,
        db_index=True,
    )

    # Source object (generic FK)
    content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_index=True,
    )
    object_id = models.UUIDField(null=True, blank=True, db_index=True)
    source_object = GenericForeignKey("content_type", "object_id")

    # Content─
    title = models.CharField(max_length=200)
    body = models.TextField(max_length=1000, blank=True)
    # Deep-link the client navigates to on tap
    action_url = models.CharField(
        max_length=500,
        blank=True,
        help_text=_("Client-side deep link, e.g. /posts/uuid or /profile/username"),
    )
    # Extra arbitrary data for the client (e.g. post thumbnail url, actor avatar)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Arbitrary JSON payload for client rendering."),
    )

    # Read state
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # Delivery state
    is_sent_push = models.BooleanField(
        default=False,
        help_text=_("True after FCM/APNs push was dispatched."),
    )
    sent_push_at = models.DateTimeField(null=True, blank=True)

    is_sent_ws = models.BooleanField(
        default=False,
        help_text=_("True after WebSocket delivery confirmed."),
    )
    sent_ws_at = models.DateTimeField(null=True, blank=True)

    # Grouping─
    # group_key allows collapsing similar notifs: "3 people liked your post"
    # Set to e.g. "post_liked:post_uuid" so the consumer can group them.
    group_key = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        help_text=_("Grouping key for collapsible notifications."),
    )

    class Meta:
        db_table = "notifications_notification"
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at"]
        indexes = [
            # Inbox: unread first, then by recency
            models.Index(
                fields=["recipient", "-created_at"],
                name="notif_recipient_inbox_idx",
            ),
            # Unread count (hot path — badge number)
            models.Index(
                fields=["recipient", "is_read"],
                condition=models.Q(is_read=False, is_deleted=False),
                name="notif_unread_partial_idx",
            ),
            # Category inbox (filtered tab: "Social", "Following"…)─
            models.Index(
                fields=["recipient", "category", "-created_at"],
                name="notif_recipient_category_idx",
            ),
            # Actor feed (admin: all notifs triggered by a user)
            models.Index(
                fields=["actor", "notification_type"],
                name="notif_actor_type_idx",
            ),
            # Group collapsing
            models.Index(
                fields=["group_key", "-created_at"],
                condition=models.Q(is_deleted=False),
                name="notif_group_key_idx",
            ),
            # BRIN on created_at — efficient range scans, low overhead
            BrinIndex(fields=["created_at"], name="notifification_created_brin_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"[{self.notification_type}] "
            f"→ {getattr(self.recipient, 'username', self.recipient_id)}"
        )

    # Domain logic (pure, no side effects)

    def mark_as_read(self) -> None:
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def mark_as_unread(self) -> None:
        if self.is_read:
            self.is_read = False
            self.read_at = None
            self.save(update_fields=["is_read", "read_at"])

    def record_push_sent(self) -> None:
        self.is_sent_push = True
        self.sent_push_at = timezone.now()
        self.save(update_fields=["is_sent_push", "sent_push_at"])

    def record_ws_sent(self) -> None:
        self.is_sent_ws = True
        self.sent_ws_at = timezone.now()
        self.save(update_fields=["is_sent_ws", "sent_ws_at"])

    @property
    def is_high_priority(self) -> bool:
        return self.priority in (
            NotificationPriority.HIGH.value,
            NotificationPriority.URGENT.value,
        )

    def to_ws_payload(self) -> dict:
        """
        Minimal serialisable dict broadcast over WebSocket.
        Attachments are included inline if present.
        """
        attachments = []
        if (
            hasattr(self, "_prefetched_objects_cache")
            and "attachments" in self._prefetched_objects_cache
        ):
            attachments = [a.to_payload() for a in self.attachments.all()]

        return {
            "id": str(self.id),
            "notification_type": self.notification_type,
            "category": self.category,
            "priority": self.priority,
            "title": self.title,
            "body": self.body,
            "action_url": self.action_url,
            "metadata": self.metadata,
            "actor": {
                "id": str(self.actor_id) if self.actor_id else None,
                "username": getattr(self.actor, "username", None),
                "avatar": None,  # populated by serializer layer
            },
            "attachments": attachments,
            "is_read": self.is_read,
            "group_key": self.group_key,
            "created_at": self.created_at.isoformat(),
        }


class NotificationAttachment(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Optional media attached to a notification.

    Kept in a separate table (not a nullable field on Notification) so that:
      - The Notification table stays narrow and fast.
      - A notification can carry multiple attachments if needed.
      - Images are stored in S3; only the CDN URL lives here.

    Examples:
      - Post preview thumbnail  → new like / comment
      - Actor's avatar          → new follower (if not in metadata)
      - Promotional banner      → marketing announcement
    """

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    attachment_type = models.CharField(
        max_length=12,
        choices=NotificationAttachmentType.choices,
        default=NotificationAttachmentType.IMAGE.value,
    )
    cdn_url = models.TextField(help_text=_("Full CDN URL of the image."))    
    alt_text = models.CharField(max_length=200, blank=True)
    width_px = models.PositiveIntegerField(null=True, blank=True)
    height_px = models.PositiveIntegerField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(
        default=0,
        help_text=_("Display order when multiple attachments present."),
    )

    class Meta:
        db_table = "notifications_attachment"
        ordering = ["position"]
        indexes = [
            models.Index(
                fields=["notification", "position"], name="notif_attach_order_idx"
            ),
        ]

    def to_payload(self) -> dict:
        return {
            "type": self.attachment_type,
            "cdn_url": self.cdn_url,
            "alt_text": self.alt_text,
            "width": self.width_px,
            "height": self.height_px,
        }

    def __str__(self) -> str:
        return f"Attachment({self.attachment_type}) for Notif:{self.notification_id}"


class NotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Per-user, per-category notification switch.

    Interface Segregation:
      Each category gets its own row — not one row with 20 boolean columns.
      Absence of a row = default ON.

    Channels each category can be delivered over:
      - in_app  : WebSocket + in-app inbox
      - push    : FCM / APNs mobile push
      - email   : async email digest

    Example state:
      user=Eze, category=MARKETING → in_app=True, push=False, email=False
      user=Eze, category=SOCIAL   → in_app=True, push=True,  email=False
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
        db_index=True,
    )
    category = models.CharField(
        max_length=15,
        choices=NotificationCategory.choices,
        db_index=True,
    )

    # Channel toggles
    in_app_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=False)  # opt-in only

    class Meta:
        db_table = "notifications_preference"
        verbose_name = _("notification preference")
        unique_together = [("user", "category")]
        indexes = [
            models.Index(fields=["user", "category"], name="notifpref_user_cat_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"Pref({getattr(self.user, 'username', self.user_id)} "
            f"| {self.category} | in_app={self.in_app_enabled} "
            f"push={self.push_enabled})"
        )

    def is_channel_enabled(self, channel: str) -> bool:
        """
        channel: "in_app" | "push" | "email"
        Returns True if the channel is on for this category.
        """
        return {
            "in_app": self.in_app_enabled,
            "push": self.push_enabled,
            "email": self.email_enabled,
        }.get(channel, False)
    

class NotificationMute(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Time-bounded or permanent mute for a specific actor or source.

    Separate from NotificationPreference (which is category-wide + permanent).
    This handles:
      - "Mute @spammy_user forever"
      - "Mute this post's comments for 7 days"
      - "Do not disturb for 8 hours"

    expires_at = None → permanent mute.
    expires_at set    → auto-un-mute after that timestamp (checked in service).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_mutes",
        db_index=True,
    )
    mute_type = models.CharField(
        max_length=10,
        choices=NotificationMuteType.choices,
        db_index=True,
    )

    # Actor mute (mute_type=ACTOR)
    muted_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="muted_by",
        db_index=True,
    )

    # ── Source object mute (mute_type=SOURCE)
    content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    object_id = models.UUIDField(null=True, blank=True)
    source_object = GenericForeignKey("content_type", "object_id")

    # ── Category mute (mute_type=CATEGORY) ───────────────────────────────────
    muted_category = models.CharField(
        max_length=15,
        choices=NotificationCategory.choices,
        blank=True,
    )

    # Expiry 
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=_("null = permanent. Set for timed mutes."),
    )
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "notifications_mute"
        verbose_name = _("notification mute")
        indexes = [
            models.Index(fields=["user", "mute_type"], name="mute_user_type_idx"),
            models.Index(fields=["user", "muted_actor"], name="mute_user_actor_idx"),
            models.Index(fields=["expires_at"], name="mute_expires_at_idx"),
        ]

    @property
    def is_active(self) -> bool:
        if self.expires_at is None:
            return True
        return self.expires_at > timezone.now()

    def __str__(self) -> str:
        target = (
            self.muted_actor
            or self.muted_category
            or f"{self.content_type}:{self.object_id}"
        )
        return f"Mute({self.user_id} → {target})"


class NotificationBatch(UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Collapses multiple similar notifications into one display row.

    e.g. "Brandon, Tiwa and 4 others liked your post"

    When a new notification is created with a group_key that already has
    a batch, the service updates this record instead of creating a new
    Notification row. The recipient sees one updating notification entry.

    actor_ids stores the first 3 actor IDs for preview rendering.
    total_count is the full count including actors beyond the first 3.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_batches",
        db_index=True,
    )
    group_key = models.CharField(max_length=200, db_index=True)
    # Most recent individual notification in this batch
    latest_notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="batch",
    )
    actor_ids = models.JSONField(
        default=list,
        help_text=_("First 3 actor UUIDs for preview."),
    )
    total_count = models.PositiveIntegerField(default=1)
    is_read = models.BooleanField(default=False, db_index=True)
    last_event_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "notifications_batch"
        unique_together = [("recipient", "group_key")]
        indexes = [
            models.Index(
                fields=["recipient", "-last_event_at"], name="batch_recipient_idx"
            ),
            models.Index(
                fields=["recipient"],
                condition=models.Q(is_read=False),
                name="batch_unread_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Batch({self.group_key} × {self.total_count}) → {self.recipient_id}"
