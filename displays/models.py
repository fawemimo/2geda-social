from datetime import timedelta

from django.db import models
from django.utils import timezone

from accounts.models import User
from utils.enum import PostVisibility
from utils.models import BaseModel, UUIDPrimaryKeyMixin, TimestampMixin


class Display(BaseModel):
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="displays", db_index=True,
    )
    body = models.TextField(max_length=2000, blank=True)
    media = models.ForeignKey(
        "medias.Media", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="displays",
    )
    visibility = models.CharField(
        max_length=10, choices=PostVisibility.choices,
        default=PostVisibility.PUBLIC.value, db_index=True,
    )
    expires_at = models.DateTimeField(db_index=True)
    reshare_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reshares", db_index=True,
    )

    likes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    reshares_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "displays_display"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["author", "-created_at"], name="display_author_created_idx"),
            models.Index(fields=["expires_at", "is_deleted"], name="display_expiry_cleanup_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)


class DisplayComment(BaseModel):
    display = models.ForeignKey(
        Display, on_delete=models.CASCADE, related_name="comments", db_index=True,
    )
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="display_comments", db_index=True,
    )
    body = models.TextField(max_length=1000)

    class Meta:
        db_table = "displays_display_comment"
        ordering = ["created_at"]


class DisplayLike(UUIDPrimaryKeyMixin, TimestampMixin):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="display_likes", db_index=True,
    )
    display = models.ForeignKey(
        Display, on_delete=models.CASCADE, related_name="likes", db_index=True,
    )

    class Meta:
        db_table = "displays_display_like"
        unique_together = [("user", "display")]


class DisplayView(UUIDPrimaryKeyMixin, TimestampMixin):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True,
        related_name="display_views", db_index=True,
    )
    display = models.ForeignKey(
        Display, on_delete=models.CASCADE, related_name="views", db_index=True,
    )

    class Meta:
        db_table = "displays_display_view"
        unique_together = [("user", "display")]
