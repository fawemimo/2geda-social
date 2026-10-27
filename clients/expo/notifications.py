import logging
import requests
import json

from utils.logging import ref

logger = logging.getLogger(__name__)
EXPO_PUSH_TIMEOUT = 10


class ExpoNotificationAPI:

    @staticmethod
    def send_notification(token, title, body, data=None):
        """
        Sends a single notification to a given device token using Expo's push notification service.
        """
        url = "https://exp.host/--/api/v2/push/send"
        headers = {"Content-Type": "application/json"}
        payload_data = {"to": token, "title": title, "body": body, "data":data}
        if data:
            payload_data["data"] = data

        try:
            response = requests.post(
                url, headers=headers, data=json.dumps(payload_data), timeout=EXPO_PUSH_TIMEOUT
            )
            response.raise_for_status()  # Raise an exception for HTTP errors
            # A push token is a device credential and the title/body are the
            # customer's own transaction details -- neither belongs off-box.
            logger.info(
                "Push notification sent",
                extra={"event": "push.sent", "device_ref": ref(token, "dev")},
            )
            return response.json()
        except requests.RequestException as e:
            logger.warning(
                "Push notification failed",
                exc_info=True,
                extra={"event": "push.failed", "device_ref": ref(token, "dev"), "message": str(e)},
            )
            return None

    @staticmethod
    def send_bulk_notification(tokens, title, body, data=None):
        """
        Sends bulk notifications to multiple device tokens using Expo's push notification service.
        """
        if not tokens:
            return None

        url = "https://exp.host/--/api/v2/push/send"
        headers = {"Content-Type": "application/json"}
        messages = []
        for token in tokens:
            message = {"to": token, "title": title, "body": body, "data":data}
            if data:
                message["data"] = data
            messages.append(message)

        try:
            response = requests.post(
                url, headers=headers, data=json.dumps(messages), timeout=EXPO_PUSH_TIMEOUT
            )
            response.raise_for_status()
            logger.info(
                "Bulk push notifications sent",
                extra={"event": "push.bulk_sent", "count": len(tokens)},
            )
            return response.json()
        except requests.RequestException as e:
            logger.warning(
                "Bulk push notification failed",
                exc_info=True,
                extra={"event": "push.bulk_failed", "count": len(tokens), "message": str(e)},
            )
            return None
