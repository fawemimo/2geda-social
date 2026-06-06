from django.contrib import admin

from utils.caches import CachingPaginator


class BaseModelAdmin(admin.ModelAdmin):
    list_per_page = 100
    paginator = CachingPaginator
    ordering = ("-created_at", "-updated_at",)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj) or [])
        for f in ("id", "pk", "created_at", "updated_at", "deleted_at"):
            if hasattr(self.model, f) and f not in fields:
                fields.append(f)
        return fields

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request) or [])
        if hasattr(self.model, "is_deleted") and "is_deleted" not in filters:
            filters.append("is_deleted")
        if hasattr(self.model, "created_at") and "created_at" not in filters:
            filters.append("created_at")
        return filters

    def has_delete_permission(self, request, obj=None):
        if hasattr(self.model, "is_deleted"):
            return False
        return super().has_delete_permission(request, obj)

    actions = ["restore_soft_deleted"]

    def restore_soft_deleted(self, request, queryset):
        if not hasattr(self.model, "is_deleted"):
            self.message_user(request, "This model does not support soft delete.")
            return
        updated = queryset.update(is_deleted=False, deleted_at=None)
        self.message_user(request, f"{updated} record(s) restored.")

    restore_soft_deleted.short_description = "Restore soft-deleted records"


class BaseTabularInline(admin.TabularInline):
    extra = 0
    can_delete = True

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj) or [])
        for f in ("id", "pk", "created_at", "updated_at"):
            if hasattr(self.model, f) and f not in fields:
                fields.append(f)
        return fields


class BaseStackedInline(admin.StackedInline):
    extra = 0
    can_delete = True

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj) or [])
        for f in ("id", "pk", "created_at", "updated_at"):
            if hasattr(self.model, f) and f not in fields:
                fields.append(f)
        return fields
