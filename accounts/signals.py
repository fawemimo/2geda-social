from __future__ import annotations

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from accounts.cache import bump_list_version, make_user_detail_cache_key, make_user_me_cache_key
from accounts.models import User, UserProfile


@receiver([post_save, post_delete], sender=User)
def invalidate_user_caches_on_user_change(sender, instance, **kwargs):
    bump_list_version()
    cache.delete(make_user_detail_cache_key(str(instance.pk)))
    cache.delete(make_user_me_cache_key(str(instance.pk)))


@receiver([post_save, post_delete], sender=UserProfile)
def invalidate_user_caches_on_profile_change(sender, instance, **kwargs):
    bump_list_version()
    if instance.user_id:
        cache.delete(make_user_detail_cache_key(str(instance.user_id)))
        cache.delete(make_user_me_cache_key(str(instance.user_id)))
