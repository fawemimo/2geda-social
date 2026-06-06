import logging
from django.db import transaction
from django.utils import timezone
from accounts.services.exceptions import ConflictError, NotFoundError, ValidationError
from accounts.models import Follow, User
from notifications.services.dto import CreateNotificationDTO
from notifications.tasks import dispatch_notification
from utils.enum import FollowStatus, NotificationPriority, NotificationType
from notifications.services.notification_services import NotificationService as NotificationCreator
logger = logging.getLogger(__name__)


class FollowService:

    @staticmethod
    @transaction.atomic
    def follow(follower: User, following_id: str) -> Follow:
        if str(follower.id) == str(following_id):
            raise ValidationError("You cannot follow yourself.")

        try:
            following = User.objects.get(pk=following_id, is_active=True, is_deleted=False)
        except User.DoesNotExist:
            raise NotFoundError("User not found.")

        existing = Follow.objects.filter(follower=follower, following=following).first()
        if existing:
            if existing.status == FollowStatus.ACCEPTED.value:
                raise ConflictError("You are already following this user.")
            existing.delete()

        follow = Follow.objects.create(
            follower=follower,
            following=following,
            status=FollowStatus.ACCEPTED.value,
            accepted_at=timezone.now(),
        )

        FollowService._dispatch_follow_notification(follower, following, follow)
        return follow

    @staticmethod
    @transaction.atomic
    def unfollow(follower: User, following_id: str) -> None:
        try:
            following = User.objects.get(pk=following_id)
        except User.DoesNotExist:
            raise NotFoundError("User not found.")

        deleted, _ = Follow.objects.filter(follower=follower, following=following).delete()
        if not deleted:
            raise ValidationError("You are not following this user.")

    @staticmethod
    def _dispatch_follow_notification(follower: User, following: User, follow: Follow) -> None:
        title = f"@{follower.username} started following you"
        try:
            dto = CreateNotificationDTO(
                recipient_id=str(following.id),
                notification_type=NotificationType.NEW_FOLLOWER.value,
                title=title,
                body=title,
                actor_id=str(follower.id),
                source_model=Follow,
                source_id=str(follow.id),
                priority=NotificationPriority.NORMAL.value,
            )
            notification = NotificationCreator.create(dto)
            dispatch_notification.delay(str(notification.id))
        except Exception:
            logger.exception("Failed to dispatch follow notification")

