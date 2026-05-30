from accounts.models import User, UserDevice
from clients.google.firebase import FireBasePushAPI


# Send a push notification to the specified device.
class PushNotificationService:
    def send_push_notification(self, title: str, message: str, data: dict | None = None) -> bool:
        # check if device has a push token
        devices = UserDevice.objects.filter(push_token__isnull=False, is_trusted=True).exclude(push_token="")
        if not devices.exists():
            return False

        # Send the notification to all devices
        for device in devices:
            FireBasePushAPI().send_user_notification(
                user_id=str(device.user_id),
                title=title,
                body=message,
                data=data
            )
