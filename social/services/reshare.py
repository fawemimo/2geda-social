import logging
from django.db import transaction
from accounts.models import User
from accounts.services.exceptions import ConflictError, NotFoundError
from notifications.services.dto import CreateNotificationDTO
from notifications.tasks import dispatch_notification
from social.event_broadcaster import broadcast_post_event, broadcast_trending_event
from social.models import Post, Reshare
from social.tasks import notify_followers
from utils.enum import NotificationPriority, NotificationType
from notifications.services.notification_services import NotificationService as NotificationCreator
logger = logging.getLogger(__name__)


class ReshareService:

    @staticmethod
    @transaction.atomic
    def create(*, user: User, validated_data: dict) -> Reshare:
        original_post_id = validated_data["original_post_id"]
        try:
            original_post = Post.objects.get(pk=original_post_id, is_deleted=False)
        except Post.DoesNotExist:
            raise NotFoundError("Original post not found.")

        existing = Reshare.objects.filter(user=user, original_post=original_post).select_for_update().first()
        if existing:
            raise ConflictError("You have already reshared this post.")

        reshare_comment = validated_data.get("reshare_comment", "")
        reshare_post = Post.objects.create(
            author=user,
            body=reshare_comment,
            visibility=original_post.visibility,
            reshare_of=original_post,
            reshare_comment=reshare_comment,
        )

        reshare = Reshare.objects.create(
            user=user,
            original_post=original_post,
            reshare_post=reshare_post,
        )

        original_post.refresh_from_db()

        ReshareService._dispatch_reshare_notification(user, original_post, reshare)

        broadcast_post_event(str(original_post.id), {
            "event": "reshare.new",
            "reshare_id": str(reshare.id),
            "user_id": str(user.id),
            "username": user.username,
            "post_id": str(original_post.id),
            "reshares_count": original_post.reshares_count,
        })

        broadcast_trending_event({
            "event": "trending.updated",
            "post_id": str(original_post.id),
            "action": "reshared",
            "comments_count": original_post.comments_count,
            "likes_count": original_post.likes_count,
            "reshares_count": original_post.reshares_count,
        })

        transaction.on_commit(lambda: notify_followers.delay(
            actor_id=str(user.id),
            notification_type=NotificationType.POST_RESHARED.value,
            title=f"@{user.username} reshared a post",
            body=reshare_comment[:200],
            source_model="Reshare",
            source_id=str(reshare.id),
        ))

        return reshare

    @staticmethod
    @transaction.atomic
    def delete(*, instance: Reshare) -> None:
        original_post_id = str(instance.original_post_id)
        reshare_post_id = instance.reshare_post_id
        if reshare_post_id:
            instance.reshare_post.delete()
        instance.delete()
        original_post = Post.objects.filter(pk=original_post_id).first()
        broadcast_post_event(original_post_id, {
            "event": "reshare.deleted",
            "post_id": original_post_id,
            "reshares_count": original_post.reshares_count if original_post else 0,
        })

    @staticmethod
    def _dispatch_reshare_notification(user: User, original_post: Post, reshare: Reshare) -> None:
        if original_post.author == user:
            return
        try:
            dto = CreateNotificationDTO(
                recipient_id=str(original_post.author.id),
                notification_type=NotificationType.POST_RESHARED.value,
                title=f"@{user.username} reshared your post",
                body=reshare.reshare_post.body[:200] if reshare.reshare_post else "",
                actor_id=str(user.id),
                source_model=Post,
                source_id=str(original_post.id),
                priority=NotificationPriority.NORMAL.value,
            )
            notif = NotificationCreator.create(dto)
            dispatch_notification.delay(str(notif.id))
        except Exception:
            logger.exception("Failed to dispatch reshare notification")
