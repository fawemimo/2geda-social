"""Keep the cached override map honest."""
from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from config.models import Setting
from config.runtime import invalidate_cache


@receiver(post_save, sender=Setting)
@receiver(post_delete, sender=Setting)
def _bust_config_cache(sender, **kwargs) -> None:
    """An admin edit must take effect on the next request, not in five minutes."""
    invalidate_cache()
