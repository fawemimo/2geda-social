
from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from medias.models import Media
from utils.enum import ConversationType, DeliveryStatus, MemberRole, MessageType
from utils.models import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin
from accounts.models import User


# Chat room container.

class Conversation(BaseModel):
    conversation_type = models.CharField(
        max_length=10,
        choices=ConversationType.choices,
        default=ConversationType.DIRECT.value,
        db_index=True,
    )

    # Group-only fields
    name   = models.CharField(max_length=100, blank=True)
    avatar = models.ForeignKey(
        "medias.Media",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="conversation_avatars",
    )
    description = models.TextField(max_length=300, blank=True)

    # Created by — null for system-created conversations
    created_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_conversations",
    )

    # Lock state — prevents non-admins from sending messages
    is_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="locked_conversations",
    )

    # Denormalised last-activity timestamp for inbox ordering
    last_message_at = models.DateTimeField(
        null=True, blank=True,
        db_index=True,
        help_text=_("Updated on every new message. Used to sort inbox."),
    )
    last_message_preview = models.CharField(
        max_length=200, blank=True,
        help_text=_("Snippet of the last message body for inbox display."),
    )

    class Meta:
        db_table = "chat_conversation"
        verbose_name = _("conversation")
        ordering = ["-last_message_at"]
        indexes = [
            models.Index(fields=["-last_message_at"], name="conv_last_msg_idx"),
            models.Index(
                fields=["conversation_type"],
                condition=models.Q(is_deleted=False),
                name="conv_type_active_idx",
            ),
        ]

    def __str__(self) -> str:
        if self.conversation_type == ConversationType.GROUP.value:
            return f"Group({self.name or self.id})"
        return f"Direct({self.id})"
    # Returns the Channels layer group name for this conversation.

    def get_channel_group_name(self) -> str:
        return f"chat_{self.id}"


# Membership record — who is in which conversation.

class ConversationMember(UUIDPrimaryKeyMixin, TimestampMixin):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="members",
        db_index=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversation_memberships",
        db_index=True,
    )
    role = models.CharField(
        max_length=10,
        choices=MemberRole.choices,
        default=MemberRole.MEMBER.value,
    )

    # Notification settings per-member
    is_muted          = models.BooleanField(default=False)
    mute_until        = models.DateTimeField(null=True, blank=True)
    is_pinned         = models.BooleanField(default=False)   # pinned in inbox

    # Membership lifecycle
    left_at           = models.DateTimeField(null=True, blank=True)
    added_by          = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="members_added",
    )
    conversation_last_message_at = models.DateTimeField(
        null=True, blank=True,
        db_index=True,
        help_text=_("Copy of conversation.last_message_at for efficient sorting")
    )

    # Read watermark — messages before this timestamp are "read"
    last_read_at      = models.DateTimeField(null=True, blank=True)
    # Denormalised unread count (updated by signal)
    unread_count      = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "chat_conversation_member"
        unique_together = [("conversation", "user")]
        indexes = [
            # "What conversations is user X in?" — inbox query
            models.Index(
                fields=["user", "-conversation_last_message_at"],
                name="member_user_inbox_idx",
            ),
            # Active (not-left) members only
            models.Index(
                fields=["conversation", "user"],
                condition=models.Q(left_at__isnull=True),
                name="member_active_idx",
            ),
        ]


    @property
    def is_active(self) -> bool:
        return self.left_at is None

    def __str__(self) -> str:
        return f"{self.user.username} in {self.conversation_id} [{self.role}]"
# Call this when conversation.last_message_at changes

    def update_conversation_last_message_at(self):
        if self.conversation.last_message_at != self.conversation_last_message_at:
            ConversationMember.objects.filter(pk=self.pk).update(
                conversation_last_message_at=self.conversation.last_message_at
            )

# A single chat message — append-only.

class Message(BaseModel):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=True,
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_messages",
        db_index=True,
    )
    message_type = models.CharField(
        max_length=12,
        choices=MessageType.choices,
        default=MessageType.TEXT.value,
        db_index=True,
    )

    # Content
    body = models.TextField(blank=True, max_length=4000)
    media = models.ForeignKey(
        Media,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="chat_messages",
    )

    # Location payload (for MessageType.LOCATION)
    latitude  = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Thread / reply
    reply_to = models.ForeignKey(
        "self",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="replies",
    )

    # Edit chain
    edit_of = models.ForeignKey(
        "self",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="edits",
    )
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)


    # Who deleted this message (admin or the author)
    deleted_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="deleted_messages",
    )

    delivery_status = models.CharField(
        max_length=10,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.SENT.value,
        db_index=True,
    )

    class Meta:
        db_table = "chat_message"
        verbose_name = _("message")
        ordering = ["created_at"]
        indexes = [
            # Primary access pattern: messages in a conversation, sorted oldest→newest
            models.Index(
                fields=["conversation", "created_at"],
                condition=models.Q(is_deleted=False),
                name="msg_conv_time_idx",
            ),
            # Sender history
            models.Index(fields=["sender", "-created_at"], name="msg_sender_idx"),
            # Reply lookups
            models.Index(fields=["reply_to"], name="msg_reply_to_idx"),
            # BRIN on created_at — efficient range scans for pagination
            BrinIndex(fields=["created_at"], name="msg_created_brin_idx"),
        ]
# Clear sensitive content before soft-deleting.

    def soft_delete(self, deleted_by_id=None):
        self.body  = ""
        self.media = None
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if deleted_by_id:
            self.deleted_by_id = deleted_by_id
        self.save(update_fields=["body", "media", "is_deleted", "deleted_at", "deleted_by"])

    def to_event_payload(self) -> dict:
        return {
            "id":             str(self.id),
            "conversation_id": str(self.conversation_id),
            "sender_id":      str(self.sender_id),
            "sender_username": self.sender.username,
            "message_type":   self.message_type,
            "body":           self.body,
            "reply_to_id":    str(self.reply_to_id) if self.reply_to_id else None,
            "media_url":      self.media.cdn_url if self.media else None,
            "is_edited":      self.is_edited,
            "delivery_status": self.delivery_status,
            "created_at":     self.created_at.isoformat(),
            "is_deleted":     self.is_deleted,
            "deleted_by_id":  str(self.deleted_by_id) if self.deleted_by_id else None,
        }

    def __str__(self) -> str:
        return f"Message({self.sender.username} → conv:{self.conversation_id})"

# Emoji reaction on a message.

class MessageReaction(UUIDPrimaryKeyMixin, TimestampMixin):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="reactions",
        db_index=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="message_reactions",
    )
    emoji = models.CharField(max_length=10)   # unicode emoji e.g. "👍"

    class Meta:
        db_table = "chat_message_reaction"
        unique_together = [("message", "user", "emoji")]
        indexes = [
            models.Index(fields=["message"], name="reaction_msg_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.emoji} by {self.user.username} on {self.message_id}"


class JoinRequest(UUIDPrimaryKeyMixin, TimestampMixin):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    STATUS_CHOICES = [
        (PENDING, _("Pending")),
        (APPROVED, _("Approved")),
        (REJECTED, _("Rejected")),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="join_requests",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="group_join_requests",
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=PENDING,
        db_index=True,
    )
    processed_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="processed_join_requests",
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "chat_join_request"
        unique_together = [("conversation", "user")]
        indexes = [
            models.Index(
                fields=["conversation", "status"],
                name="join_req_conv_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} → {self.conversation_id} [{self.status}]"


