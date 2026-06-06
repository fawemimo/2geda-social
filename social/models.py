
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import BrinIndex, GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _

from utils.enum import NotificationType, PostVisibility
from utils.models import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin
from accounts.models import User
from medias.models import Media

# The core content unit.

class Post(BaseModel):
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="posts",
        db_index=True,
    )
    body = models.TextField(blank=True, max_length=2000)
    visibility = models.CharField(
        max_length=10,
        choices=PostVisibility.choices,
        default=PostVisibility.PUBLIC.value,
        db_index=True,
    )

    # ---- Reshare ----
    reshare_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reshares",
        db_index=True,
    )
    reshare_comment = models.TextField(
        blank=True,
        max_length=500,
        help_text=_("Quote comment when resharing. Empty = silent reshare."),
    )

    # ---- Counters (denormalised) ----
    likes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    reshares_count = models.PositiveIntegerField(default=0)

    # ---- Location snapshot (optional) ----
    location_label = models.CharField(max_length=120, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # ---- Search ----
    search_vector = SearchVectorField(null=True, blank=True)

    # GenericRelation so Like objects are deleted with the post
    likes = GenericRelation("Like", related_query_name="post")

    class Meta:
        db_table = "social_post"
        verbose_name = _("post")
        ordering = ["-created_at"]
        indexes = [
            # Feed: author's posts newest first
            models.Index(fields=["author", "-created_at"], name="post_author_feed_idx"),
            # Discovery: public posts newest first
            models.Index(
                fields=["-created_at"],
                condition=models.Q(visibility="public", is_deleted=False),
                name="post_public_feed_idx",
            ),
            GinIndex(fields=["search_vector"], name="post_search_gin_idx"),
            BrinIndex(fields=["created_at"], name="post_created_brin_idx"),
            models.Index(fields=["reshare_of"], name="post_reshare_of_idx"),
        ]

    def __str__(self) -> str:
        return f"Post({self.author.username}, {self.created_at:%Y-%m-%d})"

# Ordered attachment of a Media asset to a Post.

class PostMedia(UUIDPrimaryKeyMixin):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="attachments")
    media = models.ForeignKey(Media, on_delete=models.CASCADE, related_name="post_attachments")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "social_post_media"
        unique_together = [("post", "media")]
        ordering = ["position"]
        indexes = [
            models.Index(fields=["post", "position"], name="postmedia_order_idx"),
        ]

# A user's like on any likeable object (Post, Comment).

class Like(UUIDPrimaryKeyMixin, TimestampMixin):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="likes",
        db_index=True,
    )

    # Generic FK target
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField(db_index=True)
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        db_table = "social_like"
        verbose_name = _("like")
        unique_together = [("user", "content_type", "object_id")]
        indexes = [
            # "How many likes does object X have?" — sorted newest first
            models.Index(
                fields=["content_type", "object_id", "-created_at"],
                name="like_object_idx",
            ),
            # "What has user X liked?"
            models.Index(fields=["user", "-created_at"], name="like_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} ♥ {self.content_type.model}:{self.object_id}"


# Comment on a Post, optionally replying to another Comment (one level deep).

class Comment(BaseModel):
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="comments",
        db_index=True,
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="comments",
        db_index=True,
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies",
        db_index=True,
        help_text=_("Null = top-level comment; set = reply to another comment."),
    )
    body = models.TextField(max_length=1000)

    # ---- Counters ----
    likes_count = models.PositiveIntegerField(default=0)
    replies_count = models.PositiveIntegerField(default=0)

    # GenericRelation for cascade
    likes = GenericRelation(Like, related_query_name="comment")

    class Meta:
        db_table = "social_comment"
        verbose_name = _("comment")
        ordering = ["created_at"]
        indexes = [
            # Top-level comments on a post, oldest first
            models.Index(
                fields=["post", "created_at"],
                condition=models.Q(parent__isnull=True, is_deleted=False),
                name="comment_toplevel_idx",
            ),
            # Replies to a comment
            models.Index(fields=["parent", "created_at"], name="comment_replies_idx"),
            # Author's comment history
            models.Index(fields=["author", "-created_at"], name="comment_author_idx"),
        ]

    def __str__(self) -> str:
        return f"Comment({self.author.username} on Post:{self.post_id})"


# Explicit reshare record.

class Reshare(UUIDPrimaryKeyMixin, TimestampMixin):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="reshared",
        db_index=True,
    )
    original_post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="reshare_records",
        db_index=True,
    )
    # The new Post object created for this reshare (null for silent reshare)
    reshare_post = models.OneToOneField(
        Post,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="as_reshare",
    )

    class Meta:
        db_table = "social_reshare"
        unique_together = [("user", "original_post")]
        indexes = [
            models.Index(fields=["original_post"], name="reshare_original_idx"),
            models.Index(fields=["user"], name="reshare_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} reshared Post:{self.original_post_id}"

