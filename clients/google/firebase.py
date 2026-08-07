import logging
import os
import requests
from google.oauth2 import service_account
import google.auth.transport.requests as google_request_transport

from accounts.models import User
from accounts.services.exceptions import ValidationError

logger = logging.getLogger(__name__)

FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")


class FireBasePushAPI:
    def __init__(self):
        self.service_account_file = 'credentials.json'
        self.url = f'https://fcm.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/messages:send'
        self.credentials = service_account.Credentials.from_service_account_file(
            self.service_account_file,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )

    def get_access_token(self):
        try:
            logger.info("Refreshing Firebase credentials for access token.")
            request = google_request_transport.Request()
            self.credentials.refresh(request)
            logger.info("Access token successfully retrieved.")
            return self.credentials.token
        except Exception as e:
            logger.error(f"Failed to refresh Firebase access token: {e}")
            raise ValidationError("Failed to authenticate with Firebase.", code="firebase_auth_failed")

    def get_headers(self):
        try:
            access_token = self.get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; UTF-8",
            }
            logger.info("Headers successfully created for Firebase API request.")
            return headers
        except Exception as e:
            logger.error(f"Failed to create headers for Firebase API: {e}")
            raise ValidationError("Failed to prepare Firebase API request.", code="firebase_request_failed")

    def send_notification(self, push_token, title, body, data=None):
        if not push_token:
            logger.warning("Device token is missing. Notification cannot be sent.")
            return {"message": "Device token is missing"}

        payload = {
            "message": {
                "token": push_token,
                "notification": {
                    "title": title,
                    "body": body
                },
                "data": data or {}
            }
        }

        try:
            logger.info("Sending push notification.")
            response = requests.post(self.url, headers=self.get_headers(), json=payload)
            response_data = response.json()
            logger.info(f"Notification sent. Response: {response_data}")
            return response_data
        except requests.RequestException as e:
            logger.error(f"HTTP request failed while sending notification: {e}")
            raise ValidationError("Failed to send notification.", code="firebase_send_failed")
        except Exception as e:
            logger.error(f"Unexpected error occurred while sending notification: {e}")
            raise ValidationError("An unexpected error occurred.", code="unexpected_error")

    def send_bulk_notification(self, tokens, title, body, data=None):
        if not tokens:
            logger.warning("No device tokens provided for bulk notification.")
            raise ValidationError("No device tokens provided.", code="no_device_tokens")

        payload = {
            "message": {
                "token": tokens,
                "notification": {
                    "title": title,
                    "body": body
                },
                "data": data or {}
            }
        }

        try:
            logger.info("Sending bulk push notification to %s token(s).", len(tokens))
            response = requests.post(self.url, headers=self.get_headers(), json=payload)
            response_data = response.json()
            logger.info(f"Bulk notification sent. Response: {response_data}")
            return response_data
        except requests.RequestException as e:
            logger.error(f"HTTP request failed while sending bulk notification: {e}")
            raise ValidationError("Failed to send bulk notification.", code="firebase_send_failed")
        except Exception as e:
            logger.error(f"Unexpected error occurred while sending bulk notification: {e}")
            raise ValidationError("An unexpected error occurred.", code="unexpected_error")

