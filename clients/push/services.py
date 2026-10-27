from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings

from clients.expo.notifications import ExpoNotificationAPI
from clients.google.firebase import FireBasePushAPI
from config import get_str

logger = logging.getLogger(__name__)


class PushNotificationService:
    """
    Unified push notification service that can use either Firebase or Expo
    based on configuration.
    """

    @classmethod
    def get_provider(cls):
        """Get the configured push notification provider."""
        provider = get_str("PUSH_NOTIFICATION_PROVIDER", "expo").lower()
        return provider

    @classmethod
    def send_notification(cls, token: str, title: str, body: str, data: Optional[dict] = None):
        """
        Send a push notification using the configured provider.
        """
        provider = cls.get_provider()
        
        try:
            if provider == "expo":
                return ExpoNotificationAPI.send_notification(token, title, body, data=data)
            elif provider == "firebase":
                firebase = FireBasePushAPI()
                return firebase.send_notification(token, title, body, data=data)
            else:
                logger.warning(f"Unknown push provider: {provider}, defaulting to firebase")
                firebase = FireBasePushAPI()
                return firebase.send_notification(token, title, body, data=data)
        except Exception as e:
            logger.exception(f"Failed to send push notification via {provider}: {e}")
            return None

    @classmethod
    def send_bulk_notification(cls, tokens: list[str], title: str, body: str, data: Optional[dict] = None):
        """
        Send bulk push notifications.
        """
        provider = cls.get_provider()
        
        if not tokens:
            return None
            
        try:
            if provider == "expo":
                # Expo can send multiple, but our current implementation sends one by one
                results = []
                for token in tokens:
                    result = ExpoNotificationAPI.send_notification(token, title, body, data=data)
                    results.append(result)
                return results
            elif provider == "firebase":
                firebase = FireBasePushAPI()
                if len(tokens) == 1:
                    return firebase.send_notification(tokens[0], title, body, data=data)
                return firebase.send_bulk_notification(tokens, title, body, data=data)
            else:
                logger.warning(f"Unknown push provider: {provider}, defaulting to firebase")
                firebase = FireBasePushAPI()
                if len(tokens) == 1:
                    return firebase.send_notification(tokens[0], title, body, data=data)
                return firebase.send_bulk_notification(tokens, title, body, data=data)
        except Exception as e:
            logger.exception(f"Failed to send bulk push notification via {provider}: {e}")
            return None
