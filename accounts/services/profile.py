from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from accounts.models import User, UserProfile

from .exceptions import NotFoundError, ValidationError


logger = logging.getLogger(__name__)


UPDATABLE_USER_FIELDS = {"username", "phone_number"}
UPDATABLE_PROFILE_FIELDS = {
    "display_name",
    "bio",
    "website",
    "date_of_birth",
    "first_name",
    "last_name",
    "work",
    "current_city",
    "is_private"
}


class ProfileService:
    def get(self, *, user: User) -> UserProfile:
        try:
            return (
                UserProfile.objects.select_related("user", "avatar", "cover_photo")
                .get(user=user)
            )
        except UserProfile.DoesNotExist:
            return UserProfile.objects.create(user=user)

    @transaction.atomic
    def update_partial(self, *, user: User, data: dict[str, Any]) -> UserProfile:
        if not isinstance(data, dict) or not data:
            raise ValidationError("No fields provided to update.", code="empty_update")

        user_updates = {k: v for k, v in data.items() if k in UPDATABLE_USER_FIELDS}
        profile_updates = {k: v for k, v in data.items() if k in UPDATABLE_PROFILE_FIELDS}

        unknown = set(data) - UPDATABLE_USER_FIELDS - UPDATABLE_PROFILE_FIELDS
        if unknown:
            raise ValidationError(
                f"Unsupported fields: {', '.join(sorted(unknown))}", code="unknown_fields"
            )

        has_changes = False
        if user_updates:
            User.objects.filter(pk=user.pk).update(**user_updates)
            for k, v in user_updates.items():
                setattr(user, k, v)
            has_changes = True
            if has_changes:
                user.save()

        profile = self.get(user=user)
        if profile_updates:
            UserProfile.objects.filter(pk=profile.pk).update(**profile_updates)
            for k, v in profile_updates.items():
                setattr(profile, k, v)
            has_changes = True
        if has_changes:
            profile.save()
        return profile

    @transaction.atomic
    def deactivate(self, *, user: User) -> None:
        user.soft_delete()

