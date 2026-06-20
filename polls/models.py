from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from utils.enum import PollStatus, PollType
from utils.models import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin


class Poll(BaseModel):
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="polls",
        db_index=True,
    )
    question = models.TextField(max_length=500)
    poll_type = models.CharField(
        max_length=20,
        choices=PollType.choices(),
        default=PollType.SINGLE_CHOICE.value,
    )
    status = models.CharField(
        max_length=10,
        choices=PollStatus.choices(),
        default=PollStatus.ACTIVE.value,
        db_index=True,
    )

    # ---- Duration ----
    starts_at = models.DateTimeField(default=timezone.now, db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # ---- Media (image / video / audio) ----
    media = models.ForeignKey(
        "medias.Media",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="polls",
    )

    # ---- Results visibility preferences ----
    show_results = models.BooleanField(
        default=True,
        help_text=_("Allow anyone to see results before the poll ends."),
    )
    show_voters = models.BooleanField(
        default=False,
        help_text=_("Show who voted to the public."),
    )
    show_vote_counts = models.BooleanField(
        default=True,
        help_text=_("Display vote counts per option."),
    )
    show_view_counts = models.BooleanField(
        default=True,
        help_text=_("Display total view count."),
    )

    # ---- Denormalised counters ----
    total_votes = models.PositiveIntegerField(default=0)
    total_views = models.PositiveIntegerField(default=0)
    options_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "polls_poll"
        verbose_name = _("poll")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["author", "-created_at"], name="poll_author_feed_idx"),
            models.Index(
                fields=["status", "-created_at"],
                condition=models.Q(is_deleted=False),
                name="poll_active_idx",
            ),
            models.Index(
                fields=["-created_at"],
                condition=models.Q(status="active", is_deleted=False),
                name="poll_public_feed_idx",
            ),
            BrinIndex(fields=["created_at"], name="poll_created_brin_idx"),
        ]

    def __str__(self) -> str:
        return f"Poll({self.question[:40]}, {self.status})"

    @property
    def is_active(self) -> bool:
        if self.status != PollStatus.ACTIVE.value:
            return False
        if self.ends_at and self.ends_at <= timezone.now():
            return False
        return True

    @property
    def is_expired(self) -> bool:
        if self.ends_at and self.ends_at <= timezone.now():
            return True
        return self.status == PollStatus.CLOSED.value


class PollOption(BaseModel):
    poll = models.ForeignKey(
        Poll,
        on_delete=models.CASCADE,
        related_name="options",
        db_index=True,
    )
    text = models.CharField(max_length=500)
    position = models.PositiveSmallIntegerField(default=0)

    # ---- Denormalised counter ----
    vote_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "polls_option"
        verbose_name = _("poll option")
        ordering = ["position"]
        indexes = [
            models.Index(fields=["poll", "position"], name="pollopt_order_idx"),
        ]

    def __str__(self) -> str:
        return self.text


class Vote(UUIDPrimaryKeyMixin, TimestampMixin):
    poll = models.ForeignKey(
        Poll,
        on_delete=models.CASCADE,
        related_name="votes",
        db_index=True,
    )
    option = models.ForeignKey(
        PollOption,
        on_delete=models.CASCADE,
        related_name="votes",
        db_index=True,
    )
    voter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="poll_votes",
        db_index=True,
    )

    class Meta:
        db_table = "polls_vote"
        verbose_name = _("vote")
        indexes = [
            models.Index(fields=["poll", "voter"], name="vote_poll_voter_idx"),
            models.Index(fields=["option", "voter"], name="vote_option_voter_idx"),
            models.Index(fields=["voter", "-created_at"], name="vote_voter_history_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.voter.username} → {self.option.text[:30]}"


class PollView(UUIDPrimaryKeyMixin, TimestampMixin):
    poll = models.ForeignKey(
        Poll,
        on_delete=models.CASCADE,
        related_name="views",
        db_index=True,
    )
    viewer = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="poll_views",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_("Fallback viewer identity when unauthenticated."),
    )

    class Meta:
        db_table = "polls_view"
        verbose_name = _("poll view")
        indexes = [
            models.Index(fields=["poll", "viewer"], name="view_poll_viewer_idx"),
            models.Index(fields=["poll", "-created_at"], name="view_poll_date_idx"),
        ]

    def __str__(self) -> str:
        return f"View({self.viewer or self.ip_address}) on Poll:{self.poll_id}"
