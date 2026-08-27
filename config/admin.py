from __future__ import annotations

from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from config.models import Setting
from config.registry import REGISTRY, spec_for
from config.runtime import all_effective, invalidate_cache


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):

    list_display = ["key", "short_value", "value_type", "category", "is_active", "source_hint"]
    list_filter = ["category", "value_type", "is_active"]
    search_fields = ["key", "description"]
    ordering = ["category", "key"]
    readonly_fields = ["value_type", "category", "created_at", "updated_at", "guidance"]
    fields = [
        "key", "value", "value_type", "category", "is_active",
        "description", "guidance", "created_at", "updated_at",
    ]
    list_per_page = 100
    actions = ["activate", "deactivate", "reset_to_env"]

    @admin.display(description="Value")
    def short_value(self, obj: Setting) -> str:
        if not obj.value:
            return mark_safe('<em style="color:#888">(from .env)</em>')
        text = obj.value if len(obj.value) <= 60 else obj.value[:57] + "..."
        return text

    @admin.display(description="Effective source")
    def source_hint(self, obj: Setting) -> str:
        if obj.is_active and obj.value.strip():
            return mark_safe('<b style="color:#0a7">database</b>')
        return mark_safe('<span style="color:#888">.env / default</span>')

    @admin.display(description="Guidance")
    def guidance(self, obj: Setting) -> str:
        spec = spec_for(obj.key) if obj.key else None
        if spec is None:
            return "—"
        return format_html(
            "<div style='line-height:1.6'>"
            "<b>Default:</b> <code>{}</code><br>"
            "<b>Type:</b> {}<br>"
            "<b>Blank value:</b> falls back to the <code>{}</code> environment "
            "variable, then to the default above.{}"
            "</div>",
            spec.default, spec.value_type, spec.key,
            mark_safe("<br><b style='color:#b00'>Workers must be restarted "
                      "for this one to take effect.</b>")
            if spec.requires_restart else "",
        )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.append("key")
        return fields

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_cache()
        messages.info(request, f"Configuration cache cleared; {obj.key} is live.")

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_cache()

    @admin.action(description="Activate selected settings")
    def activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        invalidate_cache()
        self.message_user(request, f"Activated {updated} setting(s).")

    @admin.action(description="Deactivate (fall back to .env)")
    def deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        invalidate_cache()
        self.message_user(request, f"Deactivated {updated} setting(s).")

    @admin.action(description="Clear value (fall back to .env)")
    def reset_to_env(self, request, queryset):
        updated = queryset.update(value="")
        invalidate_cache()
        self.message_user(
            request, f"Cleared {updated} value(s); they now read from .env."
        )

    def changelist_view(self, request, extra_context=None):
        report = all_effective()
        from_env = sum(1 for r in report.values() if r["source"] == "environment")
        secrets = sum(1 for r in report.values() if r["env_only"])
        self.message_user(
            request,
            f"{len(REGISTRY)} known variables · {from_env} currently from .env · "
            f"{secrets} secrets are environment-only by design.",
            level=messages.INFO,
        )
        return super().changelist_view(request, extra_context)
