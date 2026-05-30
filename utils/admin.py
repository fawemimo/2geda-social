from django.contrib import admin
# from django.db.models import JSONField
# from django_json_widget.widgets import JSONEditorWidget
from utils.caches import CachingPaginator


class BaseModelAdmin(admin.ModelAdmin):
    # formfield_overrides = {
    #     JSONField: {"widget": JSONEditorWidget},
    # }
    list_per_page = 100
    paginator = CachingPaginator
    ordering = ("-created_at","-updated_at",)
