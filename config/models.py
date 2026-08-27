from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from config.registry import CATEGORIES, VALUE_TYPES, spec_for
from utils.models import TimestampMixin, UUIDPrimaryKeyMixin


class Setting(UUIDPrimaryKeyMixin, TimestampMixin):


    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.TextField(
        blank=True,
        help_text=_("Leave blank to fall back to the environment value."),
    )
    value_type = models.CharField(
        max_length=10, choices=VALUE_TYPES, default="string",
    )
    category = models.CharField(
        max_length=50,
        choices=[(c, c) for c in CATEGORIES],
        default=CATEGORIES[0],
        db_index=True,
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Uncheck to ignore this row and use the .env value instead."),
    )

    class Meta:
        db_table = "config_setting"
        ordering = ["category", "key"]
        verbose_name = _("setting")
        verbose_name_plural = _("settings")
        indexes = [
            models.Index(fields=["is_active", "key"], name="config_active_key_idx"),
        ]

    def __str__(self) -> str:
        return self.key

    def clean(self):
        self.key = (self.key or "").strip().upper()

        spec = spec_for(self.key)
        if spec is None:
            raise ValidationError(
                {"key": _(
                    "Unknown setting. Add it to config/registry.py first so the "
                    "code has a documented default to fall back to."
                )}
            )
        if spec.env_only:
            raise ValidationError(
                {"key": _(
                    "This is a secret or API key. It is read only from the "
                    "environment and cannot be stored in the database."
                )}
            )

        self.value_type = spec.value_type
        self.category = spec.category
        if not self.description:
            self.description = spec.help_text
        
        if self.value.strip():
            try:
                self.cast(self.value, self.value_type)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValidationError(
                    {"value": _("Not a valid %(t)s: %(e)s") % {
                        "t": self.value_type, "e": exc,
                    }}
                ) from exc

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    
    @staticmethod
    def cast(raw, value_type: str):
       
        if raw is not None and not isinstance(raw, str):
            if value_type == "integer" and isinstance(raw, int) and not isinstance(raw, bool):
                return raw
            if value_type == "boolean" and isinstance(raw, bool):
                return raw
            if value_type == "json" and isinstance(raw, (dict, list)):
                return raw
            if value_type == "csv" and isinstance(raw, (list, tuple)):
                return [str(item).strip() for item in raw if str(item).strip()]

        text = "" if raw is None else str(raw).strip()
        if value_type == "integer":
            return int(text)
        if value_type == "boolean":
            lowered = text.lower()
            if lowered in ("1", "true", "yes", "on"):
                return True
            if lowered in ("0", "false", "no", "off", ""):
                return False
            raise ValueError(f"{raw!r} is not a boolean")
        if value_type == "json":
            return json.loads(text)
        if value_type == "csv":
            return [part.strip() for part in text.split(",") if part.strip()]
        return text

    @property
    def typed_value(self):
        return self.cast(self.value, self.value_type)
