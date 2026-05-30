
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _

from utils.models import BaseModel, TimestampMixin, UUIDPrimaryKeyMixin
from accounts.models import User
from utils.enum import MediaType, MediaVisibility, ProcessingStatus
# A single uploaded asset.

class Media(BaseModel):
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="media_assets",
        db_index=True,
    )
    media_type = models.CharField(max_length=10, choices=MediaType.choices, db_index=True)
    visibility = models.CharField(
        max_length=10,
        choices=MediaVisibility.choices,
        default=MediaVisibility.PUBLIC.value,
        db_index=True,
    )

    # ---- Storage ----
    storage_key = models.CharField(
        max_length=512,
        unique=True,
        help_text=_("S3 / R2 object key. Never expose this directly."),
    )
    cdn_url = models.TextField(
        blank=True,
        help_text=_("CDN-fronted public URL; empty until processing completes."),
    )
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=80, blank=True)
    file_size_bytes = models.PositiveBigIntegerField(default=0)

    # ---- Dimensions / Duration ----
    width_px = models.PositiveIntegerField(null=True, blank=True)
    height_px = models.PositiveIntegerField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    blurhash = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("BlurHash string for low-res placeholder."),
    )

    processing_status = models.CharField(
        max_length=12,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING.value,
        db_index=True,
    )
    processing_error = models.TextField(blank=True)

    # Alt text / caption (for accessibility & search)
    alt_text = models.CharField(max_length=500, blank=True)
    caption = models.TextField(blank=True)
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        db_table = "media_media"
        verbose_name = _("media")
        verbose_name_plural = _("media")
        indexes = [
            models.Index(fields=["owner", "media_type"], name="media_owner_type_idx"),
            models.Index(
                fields=["owner", "processing_status"],
                condition=models.Q(is_deleted=False),
                name="media_owner_ready_idx",
            ),
            GinIndex(fields=["search_vector"], name="media_search_gin_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.media_type}: {self.original_filename or self.id}"

# Processed derivative of a Media asset (e.g. 400×400 thumbnail).

class MediaVariant(UUIDPrimaryKeyMixin, TimestampMixin):
    media = models.ForeignKey(
        Media,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    label = models.CharField(
        max_length=40,
        help_text=_("e.g. 'thumbnail', 'medium', 'hls_720p'"),
    )
    storage_key = models.CharField(max_length=512, unique=True)
    cdn_url = models.TextField(blank=True)
    width_px = models.PositiveIntegerField(null=True, blank=True)
    height_px = models.PositiveIntegerField(null=True, blank=True)
    file_size_bytes = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "media_variant"
        unique_together = [("media", "label")]

    def __str__(self) -> str:
        return f"{self.media_id} [{self.label}]"

# User-curated gallery / album.

class Collection(BaseModel):
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="collections",
        db_index=True,
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    cover_media = models.ForeignKey(
        Media,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="collection_covers",
    )
    is_public = models.BooleanField(default=True, db_index=True)
    items_count = models.PositiveIntegerField(default=0)  # denormalised

    # Full-text
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        db_table = "media_collection"
        verbose_name = _("collection")
        indexes = [
            models.Index(fields=["owner", "is_public"], name="collection_owner_public_idx"),
            GinIndex(fields=["search_vector"], name="collection_search_gin_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.owner.username}/{self.name}"

# Ordered membership of a Media asset in a Collection.

class CollectionItem(UUIDPrimaryKeyMixin, TimestampMixin):
    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        related_name="items",
    )
    media = models.ForeignKey(
        Media,
        on_delete=models.CASCADE,
        related_name="collection_memberships",
    )
    position = models.PositiveIntegerField(default=0, db_index=True)
    caption = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "media_collection_item"
        unique_together = [("collection", "media")]
        ordering = ["position"]
        indexes = [
            models.Index(fields=["collection", "position"], name="collitem_order_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.collection} pos={self.position}"

