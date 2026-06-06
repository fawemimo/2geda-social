from django.apps import AppConfig
from django.conf import settings


class SocialConfig(AppConfig):
    name = 'social'

    def ready(self):
        import social.signals  # noqa: F401

        

