import logging
from django.db import transaction
from accounts.models import User
from medias.models import Media
from social.models import Post, PostMedia, Reshare
from social.tasks import delete_media_files, notify_followers, process_post_media
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
        location_label = validated_data.get("location_label", "")
        latitude = validated_data.get("latitude")
        longitude = validated_data.get("longitude")

        post = Post.objects.create(
            author=author,
            body=body,
            visibility=visibility,
            reshare_of_id=reshare_of_id,
            reshare_comment=reshare_comment,
            location_label=location_label,
            latitude=latitude,
            longitude=longitude
        )

        if media_ids:
            PostService._attach_media(post, media_ids)
            transaction.on_commit(lambda: process_post_media.delay(str(post.id), media_ids))

        if reshare_of_id:
            try:
                original = Post.objects.get(pk=reshare_of_id)
                Reshare.objects.create(user=author, original_post=original, reshare_post=post)
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

        return post

    @staticmethod
    @transaction.atomic
    def update(*, instance: Post, validated_data: dict) -> Post:
        for field in ("body", "visibility", "reshare_comment", "location_label", "latitude", "longitude"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        media_ids = validated_data.get("media_ids")
        if media_ids is not None:
            old_ids = list(instance.attachments.values_list("media_id", flat=True))
            if set(media_ids) != set(old_ids):
                old_media_keys = list(
                    Media.objects.filter(id__in=old_ids).values_list("storage_key", flat=True)
                )
                instance.attachments.all().delete()
                PostService._attach_media(instance, media_ids)
                transaction.on_commit(lambda: process_post_media.delay(str(instance.id), media_ids))
                if old_media_keys:
                    transaction.on_commit(lambda: delete_media_files.delay(old_media_keys))

        instance.save()
        return instance

    @staticmethod
    @transaction.atomic
    def delete(*, instance: Post) -> None:
        instance.delete()

    @staticmethod
    def _attach_media(post: Post, media_ids: list[str]) -> None:
        for idx, media_id in enumerate(media_ids):
            try:
                media = Media.objects.get(pk=media_id)
            except Media.DoesNotExist:
                logger.warning("Media %s not found, skipping", media_id)
                continue
            PostMedia.objects.create(post=post, media=media, position=idx)

