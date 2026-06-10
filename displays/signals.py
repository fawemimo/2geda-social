from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


@receiver(post_save, sender="displays.DisplayComment")
def display_comment_created(sender, instance, created, **kwargs):
    if not created:
        return
    from displays.models import Display

    Display.objects.filter(pk=instance.display_id).update(
        comments_count=F("comments_count") + 1,
    )


@receiver(post_delete, sender="displays.DisplayComment")
def display_comment_deleted(sender, instance, **kwargs):
    from displays.models import Display

    Display.objects.filter(pk=instance.display_id).update(
        comments_count=F("comments_count") - 1,
    )


@receiver(post_save, sender="displays.DisplayLike")
def display_like_created(sender, instance, created, **kwargs):
    if not created:
        return
    from displays.models import Display

    Display.objects.filter(pk=instance.display_id).update(
        likes_count=F("likes_count") + 1,
    )


@receiver(post_delete, sender="displays.DisplayLike")
def display_like_deleted(sender, instance, **kwargs):
    from displays.models import Display

    Display.objects.filter(pk=instance.display_id).update(
        likes_count=F("likes_count") - 1,
    )
