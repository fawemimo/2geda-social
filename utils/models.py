
import uuid
from django.db import models
from django.utils import timezone

# Replaces auto-increment integer PKs with UUID4.

class UUIDPrimaryKeyMixin(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    class Meta:
        abstract = True

# Audit timestamps. All production models should carry these.

class TimestampMixin(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

# Never hard-delete rows in production.

class SoftDeleteMixin(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def hard_delete(self):
        super().delete()

    class Meta:
        abstract = True

# Convenience base — compose all three mixins in one import.

class BaseModel(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    class Meta:
        abstract = True
