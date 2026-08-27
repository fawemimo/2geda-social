import logging
from django.db import transaction
from accounts.models import User
from social.event_broadcaster import broadcast_post_event
from social.models import Post, Reshare
from social.services.location import SocialLocationService
from social.tasks import broadcast_post_to_followers, notify_followers, process_post_media
from utils.enum import NotificationType

logger = logging.getLogger(__name__)


class PostService:

    @staticmethod
    @transaction.atomic
    def create(*, author: User, validated_data: dict) -> Post:
        body = validated_data.get("body", "")
        visibility = validated_data.get("visibility", "public")
        reshare_of_id = validated_data.get("reshare_of")
        reshare_comment = validated_data.get("reshare_comment", "")
        media_ids = validated_data.get("media_ids", [])
        location = SocialLocationService.capture(
            latitude=validated_data.get("latitude"),
            longitude=validated_data.get("longitude"),
            label=validated_data.get("location_label", ""),
        )

        post = Post.objects.create(
            author=author,
            body=body,
            visibility=visibility,
            reshare_of_id=reshare_of_id,
            reshare_comment=reshare_comment,
            location=location,
        )

        if media_ids:
            media_id_strs = [str(m) for m in media_ids]
            transaction.on_commit(
                lambda: process_post_media.delay(str(post.id), media_id_strs)
            )

        if reshare_of_id:
            try:
                Reshare.objects.create(
                    user=author,
                    original_post_id=reshare_of_id,
                    reshare_post=post,
                )
            except Exception:
                logger.exception("Failed to create reshare record for post %s", post.id)

        transaction.on_commit(lambda: notify_followers.delay(
            actor_id=str(author.id),
            notification_type=NotificationType.POST_COMMENTED.value,
            title=f"@{author.username} created a new post",
            body=post.body[:200] if post.body else "",
            source_model="Post",
            source_id=str(post.id),
        ))

        broadcast_post_to_followers.delay(
            post_id=str(post.id),
            author_id=str(author.id),
            event={
                "event": "post.new",
                "post_id": str(post.id),
                "author_id": str(author.id),
                "author_username": author.username,
                "body": body[:500] if body else "",
                "visibility": visibility,
            },
        )

        return post

    @staticmethod
    @transaction.atomic
    def update(*, instance: Post, validated_data: dict) -> Post:
        for field in ("body", "visibility", "reshare_comment"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        # Re-tag only when the caller sends new coordinates.
        if validated_data.get("latitude") is not None:
            instance.location = SocialLocationService.capture(
                latitude=validated_data.get("latitude"),
                longitude=validated_data.get("longitude"),
                label=validated_data.get("location_label", ""),
            )

        media_ids = validated_data.get("media_ids")
        if media_ids is not None:
            old_ids = {str(pk) for pk in instance.attachments.values_list("media_id", flat=True)}
            new_ids = [str(m) for m in media_ids]
            if set(new_ids) != old_ids:                
                instance.attachments.all().delete()
                transaction.on_commit(
                    lambda: process_post_media.delay(str(instance.id), new_ids)
                )

        instance.save()

        broadcast_post_event(str(instance.id), {
            "event": "post.updated",
            "post_id": str(instance.id),
            "author_id": str(instance.author_id),
            "body": instance.body[:500] if instance.body else "",
            "visibility": instance.visibility,
        })

        return instance

    @staticmethod
    @transaction.atomic
    def delete(*, instance: Post) -> None:
        post_id = str(instance.id)
        instance.delete()
        broadcast_post_event(post_id, {
            "event": "post.deleted",
            "post_id": post_id,
        })
