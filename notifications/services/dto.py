from dataclasses import dataclass, field
from typing import Optional

from utils.enum import NotificationPriority

@dataclass
class CreateNotificationDTO:
    """
    All data needed to create one notification.
    Callers build this DTO; the service validates and persists it.
    """

    recipient_id: str
    notification_type: str  # NotificationType value
    title: str
    body: str = ""
    actor_id: Optional[str] = None
    source_model: Optional[type] = None  # e.g. Post, Comment
    source_id: Optional[str] = None
    action_url: str = ""
    metadata: dict = field(default_factory=dict)
    priority: str = NotificationPriority.NORMAL.value
    # Image attachment (optional)
    image_cdn_url: str = ""
    image_alt_text: str = ""
    image_width: Optional[int] = None
    image_height: Optional[int] = None


@dataclass
class MuteActorDTO:
    user_id: str
    actor_id: str
    expires_at: Optional[object] = None  # datetime or None


@dataclass
class MuteSourceDTO:
    user_id: str
    source_model: type
    source_id: str
    expires_at: Optional[object] = None


@dataclass
class UpdatePreferenceDTO:
    user_id: str
    category: str
    in_app_enabled: bool = True
    push_enabled: bool = True
    email_enabled: bool = False
