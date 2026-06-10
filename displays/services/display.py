from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import User
from accounts.services.exceptions import NotFoundError, PermissionDeniedError
from displays.models import Display


class DisplayService:

    @staticmethod
    @transaction.atomic
    def create(*, author: User, validated_data: dict) -> Display:
        display = Display.objects.create(
            author=author,
            body=validated_data.get("body", ""),
            media=validated_data.get("media"),
            visibility=validated_data.get("visibility", "public"),
            reshare_of=validated_data.get("reshare_of"),
        )

        transaction.on_commit(lambda: _dispatch_display_notifications(
            actor_id=str(author.id),
            display_id=str(display.id),
            author_username=author.username,
            body=display.body[:200] if display.body else "",
        ))

        return display

    @staticmethod
    @transaction.atomic
    def delete(*, instance: Display, user: User | None = None) -> None:
        if user and instance.author != user:
            raise PermissionDeniedError("You can only delete your own displays.")
        instance.delete()

    @staticmethod
    def get_active_for_user(*, user: User) -> list[Display]:
        now = timezone.now()
        return list(
            Display.objects.filter(
                author=user, is_deleted=False, expires_at__gt=now,
            ).select_related("media").order_by("-created_at")
        )

    @staticmethod
    def get_active_feed(*, user: User) -> list[Display]:
        from accounts.models import Follow

        now = timezone.now()
        following_ids = Follow.objects.filter(
            follower=user, status="accepted",
        ).values_list("following_id", flat=True)

        return list(
            Display.objects.filter(
                author_id__in=list(following_ids) + [user.id],
                is_deleted=False,
                expires_at__gt=now,
                visibility="public",
            ).select_related("author", "media").order_by("-created_at")
        )

    @staticmethod
    def record_view(*, display: Display, user: User | None = None) -> int:
        from displays.models import DisplayView

        lookup = {"display": display}
        if user:
            lookup["user"] = user
        else:
            return display.views_count

        _, created = DisplayView.objects.get_or_create(**lookup)
        if created:
            Display.objects.filter(pk=display.pk).update(
                views_count=F("views_count") + 1,
            )
            display.refresh_from_db()
        return display.views_count

    @staticmethod
    @transaction.atomic
    def toggle_like(*, display: Display, user: User) -> dict:
        from displays.models import DisplayLike

        like, created = DisplayLike.objects.get_or_create(user=user, display=display)

        if created:
            Display.objects.filter(pk=display.pk).update(
                likes_count=F("likes_count") + 1,
            )
            liked = True
        else:
            like.delete()
            Display.objects.filter(pk=display.pk).update(
                likes_count=F("likes_count") - 1,
            )
            liked = False

        display.refresh_from_db()
        return {"liked": liked, "likes_count": display.likes_count}


def _dispatch_display_notifications(
    actor_id: str,
    display_id: str,
    author_username: str,
    body: str,
) -> None:
    from displays.tasks import notify_display_followers

    notify_display_followers.delay(
        actor_id=actor_id,
        display_id=display_id,
        title=f"@{author_username} posted a new display",
        body=body,
    )