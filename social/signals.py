
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.db import models
from django.db.models import F


# Create a UserProfile row whenever a new User is created.
@receiver(post_save, sender="accounts.User")
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        from accounts.models import UserProfile
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender="accounts.Follow")
def follow_created(sender, instance, created, **kwargs):
    if not created:
        return
    from accounts.models import Follow, FollowStatus, UserProfile
    if instance.status == FollowStatus.ACCEPTED.value:
        UserProfile.objects.filter(user=instance.follower).update(
            following_count=models.F("following_count") + 1
        )
        UserProfile.objects.filter(user=instance.following).update(
            followers_count=models.F("followers_count") + 1
        )


@receiver(post_delete, sender="accounts.Follow")
def follow_deleted(sender, instance, **kwargs):
    from accounts.models import FollowStatus, UserProfile
    from django.db.models import F
    if instance.status == FollowStatus.ACCEPTED.value:
        UserProfile.objects.filter(user=instance.follower).update(
            following_count=F("following_count") - 1
        )
        UserProfile.objects.filter(user=instance.following).update(
            followers_count=F("followers_count") - 1
        )


# Dispatch counter update to the correct model.
# Like counters
def _update_like_counter(content_type, object_id, delta: int):
    from social.models import Comment, Post

    model_class = content_type.model_class()
    if model_class is Post:
        Post.objects.filter(pk=object_id).update(likes_count=F("likes_count") + delta)
    elif model_class is Comment:
        Comment.objects.filter(pk=object_id).update(likes_count=F("likes_count") + delta)


@receiver(post_save, sender="social.Like")
def like_created(sender, instance, created, **kwargs):
    if created:
        _update_like_counter(instance.content_type, instance.object_id, +1)


@receiver(post_delete, sender="social.Like")
def like_deleted(sender, instance, **kwargs):
    _update_like_counter(instance.content_type, instance.object_id, -1)



# Comment counters

@receiver(post_save, sender="social.Comment")
def comment_created(sender, instance, created, **kwargs):
    if not created:
        return
    from social.models import Post, Comment

    Post.objects.filter(pk=instance.post_id).update(comments_count=F("comments_count") + 1)
    if instance.parent_id:
        Comment.objects.filter(pk=instance.parent_id).update(replies_count=F("replies_count") + 1)


@receiver(post_delete, sender="social.Comment")
def comment_deleted(sender, instance, **kwargs):
    from social.models import Post, Comment

    Post.objects.filter(pk=instance.post_id).update(comments_count=F("comments_count") - 1)
    if instance.parent_id:
        Comment.objects.filter(pk=instance.parent_id).update(replies_count=F("replies_count") - 1)



# Reshare counters
@receiver(post_save, sender="social.Reshare")
def reshare_created(sender, instance, created, **kwargs):
    if created:
        from social.models import Post
        from django.db.models import F
        Post.objects.filter(pk=instance.original_post_id).update(reshares_count=F("reshares_count") + 1)


@receiver(post_delete, sender="social.Reshare")
def reshare_deleted(sender, instance, **kwargs):
    from social.models import Post
    from django.db.models import F
    Post.objects.filter(pk=instance.original_post_id).update(reshares_count=F("reshares_count") - 1)



# KYC → Profile verified badge
@receiver(post_save, sender="accounts.KYC")
def kyc_status_changed(sender, instance, **kwargs):
    from accounts.models import KYCStatus, UserProfile
    if instance.status == KYCStatus.APPROVED.value:
        UserProfile.objects.filter(user=instance.user).update(is_verified=True)
    elif instance.status in (KYCStatus.REJECTED.value, KYCStatus.EXPIRED.value):
        UserProfile.objects.filter(user=instance.user).update(is_verified=False)


