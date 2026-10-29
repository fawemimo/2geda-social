import logging
from django.db import transaction
from accounts.models import User
from accounts.services.exceptions import NotFoundError, ValidationError
from notifications.services.dto import CreateNotificationDTO
from notifications.tasks import dispatch_notification
from social.event_broadcaster import broadcast_post_event, broadcast_trending_event
from social.models import Comment, Post
from social.tasks import notify_followers, process_comment_media
from utils.enum import NotificationPriority, NotificationType
from notifications.services.notification_services import NotificationService as NotificationCreator
from social.services.location import SocialLocationService

logger = logging.getLogger(__name__)


class CommentService:

    @staticmethod
    @transaction.atomic
    def create(*, author: User, post_id: str, validated_data: dict) -> Comment:
        try:
            post = Post.objects.get(pk=post_id, is_deleted=False)
        except Post.DoesNotExist:
            raise NotFoundError("Post not found.")

        parent_id = validated_data.get("parent_id")
        if parent_id:
            try:
                Comment.objects.get(pk=parent_id, post=post, is_deleted=False, parent__isnull=True)
            except Comment.DoesNotExist:
                raise ValidationError("Parent comment not found or is a reply.")

        media_ids = validated_data.get("media_ids", []) or []
        body = validated_data.get("body", "") or ""

        comment = Comment.objects.create(
            post=post,
            author=author,
            parent_id=parent_id,
            body=body,
            location=SocialLocationService.capture(
                latitude=validated_data.get("latitude"),
                longitude=validated_data.get("longitude"),
                label=validated_data.get("location_label", ""),
            ),
        )

        if media_ids:
            media_id_strs = [str(m) for m in media_ids]
            transaction.on_commit(
                lambda ids=media_id_strs: process_comment_media.delay(str(comment.id), ids)
            )

        post.refresh_from_db()

        CommentService._dispatch_comment_notification(comment)

        broadcast_post_event(str(post.id), {
            "event": "comment.new",
            "comment_id": str(comment.id),
            "author_id": str(author.id),
            "author_username": author.username,
            "body": comment.body[:500],
            "parent_id": str(parent_id) if parent_id else None,
            "post_id": str(post.id),
            "comments_count": post.comments_count,
        })

        broadcast_trending_event({
            "event": "trending.updated",
            "post_id": str(post.id),
            "action": "commented",
            "comments_count": post.comments_count,
            "likes_count": post.likes_count,
            "reshares_count": post.reshares_count,
        })

        transaction.on_commit(lambda: notify_followers.delay(
            actor_id=str(author.id),
            notification_type=NotificationType.POST_COMMENTED.value,
            title=f"@{author.username} commented on a post",
            body=comment.body[:200],
            source_model="Comment",
            source_id=str(comment.id),
        ))

        return comment

    @staticmethod
    @transaction.atomic
    def update(*, instance: Comment, body: str = None, validated_data: dict = None) -> Comment:
        if validated_data is None and body is not None:
            validated_data = {"body": body}
        if validated_data is None:
            validated_data = {}

        if "body" in validated_data and validated_data["body"] is not None:
            instance.body = validated_data["body"]
            instance.save(update_fields=["body"])

        media_ids = validated_data.get("media_ids")
        if media_ids is not None:
            old_ids = {str(pk) for pk in instance.attachments.values_list("media_id", flat=True)}
            new_ids = [str(m) for m in media_ids]
            if set(new_ids) != old_ids:
                instance.attachments.all().delete()
                transaction.on_commit(
                    lambda ids=new_ids: process_comment_media.delay(str(instance.id), ids)
                )

        return instance

    @staticmethod
    @transaction.atomic
    def delete(*, instance: Comment) -> None:
        post_id = str(instance.post_id)
        instance.delete()
        post = Post.objects.filter(pk=post_id).first()
        broadcast_post_event(post_id, {
            "event": "comment.deleted",
            "comment_id": str(instance.id),
            "post_id": post_id,
            "comments_count": post.comments_count if post else 0,
        })

    @staticmethod
    def _dispatch_comment_notification(comment: Comment) -> None:
        post = comment.post
        post_author = post.author
        notification_type = NotificationType.POST_COMMENTED.value
        title = f"@{comment.author.username} commented on your post"

        if comment.parent:
            replied_user = comment.parent.author
            if replied_user != comment.author:
                try:
                    dto = CreateNotificationDTO(
                        recipient_id=str(replied_user.id),
                        notification_type=NotificationType.COMMENT_REPLIED.value,
                        title=f"@{comment.author.username} replied to your comment",
                        body=comment.body[:200],
                        actor_id=str(comment.author.id),
                        source_model=Comment,
                        source_id=str(comment.id),
                        priority=NotificationPriority.NORMAL.value,
                    )
                    notif = NotificationCreator.create(dto)
                    dispatch_notification.delay(str(notif.id))
                except Exception:
                    logger.exception("Failed to dispatch reply notification")

        if post_author != comment.author and (not comment.parent or comment.parent.author != post_author):
            try:
                dto = CreateNotificationDTO(
                    recipient_id=str(post_author.id),
                    notification_type=notification_type,
                    title=title,
                    body=comment.body[:200],
                    actor_id=str(comment.author.id),
                    source_model=Post,
                    source_id=str(post.id),
                    priority=NotificationPriority.NORMAL.value,
                )
                notif = NotificationCreator.create(dto)
                dispatch_notification.delay(str(notif.id))
            except Exception:
                logger.exception("Failed to dispatch comment notification")
