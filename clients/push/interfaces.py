from abc import ABC, abstractmethod
from typing import Optional


class PushNotificationProvider(ABC):
    @abstractmethod
    def send_notification(self, token: str, title: str, body: str, data: Optional[dict] = None):
        pass

    @abstractmethod
    def send_bulk_notification(self, tokens: list[str], title: str, body: str, data: Optional[dict] = None):
        pass
