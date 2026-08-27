from django.apps import AppConfig


class ConfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "config"
    verbose_name = "Configuration"

    def ready(self):
        from config import signals  # noqa: F401
