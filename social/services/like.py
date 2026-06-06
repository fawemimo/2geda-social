from __future__ import annotations
import logging
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from accounts.models import User
from accounts.services.exceptions import NotFoundError, ValidationError
from notifications.services.dto import CreateNotificationDTO
from notifications.services.notification_services import NotificationService as NotificationCreator
from notifications.tasks import dispatch_notification
from social.models import Comment, Like, Post
from social.tasks import notify_followers
from utils.enum import NotificationPriority, NotificationType
logger = logging.getLogger(__name__)


class LikeService:

    @staticmethod
    @transaction.atomic
    def toggle(*, user: User, content_type_id: int, object_id: str) -> dict:
        ct = ContentType.objects.get_for_id(content_type_id)
        model_class = ct.model_class()
        if model_class is None:
            raise ValidationError("Invalid content type.")

        if model_class is Post:
            target_exists = Post.objects.filter(pk=object_id, is_deleted=False).exists()
        elif model_class is Comment:
            target_exists = Comment.objects.filter(pk=object_id, is_deleted=False).exists()
        else:
            raise ValidationError("Unsupported content type for liking.")

        if not target_exists:
            raise NotFoundError("Object not found.")

        like, created = Like.objects.get_or_create(
            user=user,
            content_type_id=content_type_id,
            object_id=object_id,
        )

        if not created:
            like.delete()
            return {"liked": False}

        recipient = LikeService._get_like_recipient(like)
        if recipient and recipient != user:
            LikeService._dispatch_like_notification(like, recipient)

        transaction.on_commit(lambda: notify_followers.delay(
            actor_id=str(user.id),
            notification_type=(
                NotificationType.POST_LIKED.value if model_class is Post
                else NotificationType.COMMENT_LIKED.value
            ),
            title=f"@{user.username} liked a {'post' if model_class is Post else 'comment'}",
            body="",
            source_model=model_class.__name__,
            source_id=object_id,
        ))

        return {"liked": True, "like_id": str(like.id)}

    @staticmethod
    def _get_like_recipient(like: Like) -> User | None:
        obj = like.content_object
        if isinstance(obj, Post):
            return obj.author
        if isinstance(obj, Comment):
            return obj.author
        return None

    @staticmethod
    def _dispatch_like_notification(like: Like, recipient: User) -> None:
        obj = like.content_object
        if isinstance(obj, Post):
            notif_type = NotificationType.POST_LIKED.value
            title = f"@{like.user.username} liked your post"
        elif isinstance(obj, Comment):
            notif_type = NotificationType.COMMENT_LIKED.value
            title = f"@{like.user.username} liked your comment"
        else:
            return

        try:
            dto = CreateNotificationDTO(
                recipient_id=str(recipient.id),
                notification_type=notif_type,
                title=title,
                body=title,
                actor_id=str(like.user.id),
                source_model=type(obj),
                source_id=str(obj.id),
                priority=NotificationPriority.NORMAL.value,
            )
            notif = NotificationCreator.create(dto)
            dispatch_notification.delay(str(notif.id))
        except Exception:
            logger.exception("Failed to dispatch like notification")
