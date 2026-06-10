from django.apps import AppConfig


class DisplaysConfig(AppConfig):
    name = "displays"

    def ready(self):
        import displays.signals  # noqa: F401
