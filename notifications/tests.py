from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User, UserDevice
from notifications.models import (
    Notification,
    NotificationMute,
    NotificationPreference,
)
from utils.enum import NotificationPriority, NotificationType

pytestmark = pytest.mark.django_db

API_ROOT = "/api/v2/notifications/"


def _auth_client(user: User) -> APIClient:
    user.is_active = True
    user.save(update_fields=["is_active"])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


def _create_notification(recipient: User, *, actor: User | None = None, **kwargs) -> Notification:
    from notifications.services.dto import CreateNotificationDTO
    from notifications.services.notification_services import NotificationService as NotificationCreator

    dto = CreateNotificationDTO(
        recipient_id=str(recipient.id),
        notification_type=kwargs.get("notification_type", NotificationType.POST_LIKED.value),
        title=kwargs.get("title", "Test notification"),
        body=kwargs.get("body", ""),
        actor_id=str(actor.id) if actor else None,
        source_model=None,
        source_id=None,
        priority=NotificationPriority.NORMAL.value,
    )
    return NotificationCreator.create(dto)


# ─────────────────────────────────────────────────────────────────────────────
#  Inbox
# ─────────────────────────────────────────────────────────────────────────────


class TestNotificationInboxView:
    url = API_ROOT

    def test_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_empty_inbox(self):
        user = User.objects.create_user(email="ni1@t.com", username="ni1", password="p")
        resp = _auth_client(user).get(self.url)
        assert resp.status_code == 200
        assert "data" in resp.data

    def test_with_notifications(self):
        user = User.objects.create_user(email="ni2@t.com", username="ni2", password="p")
        _create_notification(user)
        _create_notification(user)
        resp = _auth_client(user).get(self.url)
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 2

    def test_filter_by_category(self):
        user = User.objects.create_user(email="ni3@t.com", username="ni3", password="p")
        _create_notification(user, notification_type=NotificationType.POST_LIKED.value)
        _create_notification(user, notification_type=NotificationType.NEW_FOLLOWER.value)
        resp = _auth_client(user).get(self.url, {"category": "social"})
        assert resp.status_code == 200
        for n in resp.data["data"]:
            assert n["category"] == "social"

    def test_filter_unread_only(self):
        user = User.objects.create_user(email="ni4@t.com", username="ni4", password="p")
        n1 = _create_notification(user)
        n2 = _create_notification(user)
        n2.mark_as_read()
        resp = _auth_client(user).get(self.url, {"unread_only": "true"})
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1

    def test_does_not_include_other_users_notifications(self):
        user_a = User.objects.create_user(email="ni5a@t.com", username="ni5a", password="p")
        user_b = User.objects.create_user(email="ni5b@t.com", username="ni5b", password="p")
        _create_notification(user_b)
        resp = _auth_client(user_a).get(self.url)
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 0


# ─────────────────────────────────────────────────────────────────────────────
#  Unread Count
# ─────────────────────────────────────────────────────────────────────────────


class TestUnreadCountView:
    url = f"{API_ROOT}unread-count/"

    def test_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_zero_unread(self):
        user = User.objects.create_user(email="uc1@t.com", username="uc1", password="p")
        resp = _auth_client(user).get(self.url)
        assert resp.data["data"]["unread_count"] == 0

    def test_counts_unread(self):
        user = User.objects.create_user(email="uc2@t.com", username="uc2", password="p")
        _create_notification(user)
        _create_notification(user)
        resp = _auth_client(user).get(self.url)
        assert resp.data["data"]["unread_count"] == 2


class TestUnreadCountByCategoryView:
    url = f"{API_ROOT}unread-count-by-category/"

    def test_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_returns_counts_by_category(self):
        user = User.objects.create_user(email="ucc1@t.com", username="ucc1", password="p")
        _create_notification(user, notification_type=NotificationType.POST_LIKED.value)
        _create_notification(user, notification_type=NotificationType.NEW_FOLLOWER.value)
        _create_notification(user, notification_type=NotificationType.POST_LIKED.value)
        resp = _auth_client(user).get(self.url)
        assert resp.data["data"]["social"] == 2
        assert resp.data["data"]["following"] == 1


# ─────────────────────────────────────────────────────────────────────────────
#  Mark Read / Unread
# ─────────────────────────────────────────────────────────────────────────────


class TestMarkReadView:
    def test_mark_read(self):
        user = User.objects.create_user(email="mr1@t.com", username="mr1", password="p")
        notif = _create_notification(user)
        resp = _auth_client(user).post(f"{API_ROOT}{notif.id}/read/")
        assert resp.status_code == 200
        notif.refresh_from_db()
        assert notif.is_read is True

    def test_not_found(self):
        user = User.objects.create_user(email="mr2@t.com", username="mr2", password="p")
        resp = _auth_client(user).post(f"{API_ROOT}00000000-0000-0000-0000-000000000000/read/")
        assert resp.status_code == 404

    def test_cannot_mark_others_notification(self):
        user_a = User.objects.create_user(email="mr3a@t.com", username="mr3a", password="p")
        user_b = User.objects.create_user(email="mr3b@t.com", username="mr3b", password="p")
        notif = _create_notification(user_b)
        resp = _auth_client(user_a).post(f"{API_ROOT}{notif.id}/read/")
        assert resp.status_code == 404


class TestMarkUnreadView:
    def test_mark_unread(self):
        user = User.objects.create_user(email="mu1@t.com", username="mu1", password="p")
        notif = _create_notification(user)
        notif.mark_as_read()
        resp = _auth_client(user).post(f"{API_ROOT}{notif.id}/unread/")
        assert resp.status_code == 200
        notif.refresh_from_db()
        assert notif.is_read is False


class TestMarkAllReadView:
    url = f"{API_ROOT}mark-all-read/"

    def test_mark_all_read(self):
        user = User.objects.create_user(email="mar1@t.com", username="mar1", password="p")
        _create_notification(user)
        _create_notification(user)
        resp = _auth_client(user).post(self.url, {}, format="json")
        assert resp.status_code == 200
        assert Notification.objects.filter(recipient=user, is_read=False).count() == 0

    def test_mark_all_read_by_category(self):
        user = User.objects.create_user(email="mar2@t.com", username="mar2", password="p")
        _create_notification(user, notification_type=NotificationType.POST_LIKED.value)
        _create_notification(user, notification_type=NotificationType.NEW_FOLLOWER.value)
        resp = _auth_client(user).post(self.url, {"category": "social"}, format="json")
        assert resp.status_code == 200
        social_unread = Notification.objects.filter(
            recipient=user, category="social", is_read=False,
        ).count()
        following_unread = Notification.objects.filter(
            recipient=user, category="following", is_read=False,
        ).count()
        assert social_unread == 0
        assert following_unread == 1


# ─────────────────────────────────────────────────────────────────────────────
#  Delete
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteNotificationView:
    def test_delete(self):
        user = User.objects.create_user(email="dn1@t.com", username="dn1", password="p")
        notif = _create_notification(user)
        resp = _auth_client(user).delete(f"{API_ROOT}{notif.id}/")
        assert resp.status_code == 200
        notif.refresh_from_db()
        assert notif.is_deleted is True

    def test_cannot_delete_others(self):
        user_a = User.objects.create_user(email="dn2a@t.com", username="dn2a", password="p")
        user_b = User.objects.create_user(email="dn2b@t.com", username="dn2b", password="p")
        notif = _create_notification(user_b)
        resp = _auth_client(user_a).delete(f"{API_ROOT}{notif.id}/")
        assert resp.status_code == 404


class TestDeleteAllNotificationsView:
    url = f"{API_ROOT}delete-all/"

    def test_delete_all(self):
        user = User.objects.create_user(email="da1@t.com", username="da1", password="p")
        _create_notification(user)
        _create_notification(user)
        resp = _auth_client(user).delete(self.url)
        assert resp.status_code == 200
        assert Notification.objects.filter(recipient=user, is_deleted=False).count() == 0

    def test_delete_all_by_category(self):
        user = User.objects.create_user(email="da2@t.com", username="da2", password="p")
        _create_notification(user, notification_type=NotificationType.POST_LIKED.value)
        _create_notification(user, notification_type=NotificationType.NEW_FOLLOWER.value)
        resp = _auth_client(user).delete(f"{self.url}?category=social")
        assert resp.status_code == 200
        assert Notification.objects.filter(
            recipient=user, category="social", is_deleted=False,
        ).count() == 0
        assert Notification.objects.filter(
            recipient=user, category="following", is_deleted=False,
        ).count() == 1


# ─────────────────────────────────────────────────────────────────────────────
#  Preferences
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceListView:
    url = f"{API_ROOT}preferences/"

    def test_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_empty_preferences(self):
        user = User.objects.create_user(email="pl1@t.com", username="pl1", password="p")
        resp = _auth_client(user).get(self.url)
        assert resp.status_code == 200
        assert resp.data["data"] == {}

    def test_with_preferences(self):
        user = User.objects.create_user(email="pl2@t.com", username="pl2", password="p")
        NotificationPreference.objects.create(user=user, category="social", push_enabled=False)
        resp = _auth_client(user).get(self.url)
        assert resp.status_code == 200
        assert resp.data["data"]["social"]["push_enabled"] is False
        assert resp.data["data"]["social"]["in_app_enabled"] is True


class TestPreferenceUpdateView:
    url = f"{API_ROOT}preferences/update/"

    def test_unauthenticated(self):
        resp = APIClient().put(self.url, {"category": "social"}, format="json")
        assert resp.status_code == 401

    def test_upsert_preference(self):
        user = User.objects.create_user(email="pu1@t.com", username="pu1", password="p")
        resp = _auth_client(user).put(
            self.url,
            {"category": "social", "push_enabled": False, "email_enabled": True},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["push_enabled"] is False
        assert resp.data["data"]["email_enabled"] is True

    def test_update_existing(self):
        user = User.objects.create_user(email="pu2@t.com", username="pu2", password="p")
        NotificationPreference.objects.create(
            user=user, category="social", push_enabled=True,
        )
        resp = _auth_client(user).put(
            self.url,
            {"category": "social", "push_enabled": False},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["push_enabled"] is False

    def test_missing_category(self):
        user = User.objects.create_user(email="pu3@t.com", username="pu3", password="p")
        resp = _auth_client(user).put(self.url, {}, format="json")
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  Mutes
# ─────────────────────────────────────────────────────────────────────────────


class TestMuteListView:
    url = f"{API_ROOT}mutes/"

    def test_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_empty_mutes(self):
        user = User.objects.create_user(email="ml1@t.com", username="ml1", password="p")
        resp = _auth_client(user).get(self.url)
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_with_mutes(self):
        user = User.objects.create_user(email="ml2@t.com", username="ml2", password="p")
        target = User.objects.create_user(email="ml2t@t.com", username="ml2t", password="p")
        NotificationMute.objects.create(
            user=user, mute_type="actor", muted_actor=target,
        )
        resp = _auth_client(user).get(self.url)
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1


class TestMuteActorView:
    url = f"{API_ROOT}mutes/actor/"

    def test_unauthenticated(self):
        resp = APIClient().post(self.url, {"actor_id": "00000000-0000-0000-0000-000000000000"}, format="json")
        assert resp.status_code == 401

    def test_mute_actor(self):
        user = User.objects.create_user(email="ma1@t.com", username="ma1", password="p")
        target = User.objects.create_user(email="ma1t@t.com", username="ma1t", password="p")
        resp = _auth_client(user).post(self.url, {"actor_id": str(target.id)}, format="json")
        assert resp.status_code == 201
        assert NotificationMute.objects.filter(
            user=user, muted_actor=target, mute_type="actor",
        ).exists()


class TestMuteSourceView:
    url = f"{API_ROOT}mutes/source/"

    def test_mute_source(self):
        user = User.objects.create_user(email="ms1@t.com", username="ms1", password="p")
        resp = _auth_client(user).post(
            self.url,
            {"source_model": "Post", "source_id": "00000000-0000-0000-0000-000000000001"},
            format="json",
        )
        assert resp.status_code == 201


class TestUnmuteView:
    def test_unmute(self):
        user = User.objects.create_user(email="um1@t.com", username="um1", password="p")
        target = User.objects.create_user(email="um1t@t.com", username="um1t", password="p")
        mute = NotificationMute.objects.create(
            user=user, mute_type="actor", muted_actor=target,
        )
        resp = _auth_client(user).post(f"{API_ROOT}mutes/{mute.id}/unmute/")
        assert resp.status_code == 200
        assert not NotificationMute.objects.filter(pk=mute.id).exists()

    def test_not_found(self):
        user = User.objects.create_user(email="um2@t.com", username="um2", password="p")
        resp = _auth_client(user).post(
            f"{API_ROOT}mutes/00000000-0000-0000-0000-000000000000/unmute/",
        )
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  Device tokens
# ─────────────────────────────────────────────────────────────────────────────


class TestRegisterDeviceView:
    url = f"{API_ROOT}devices/register/"

    def test_unauthenticated(self):
        resp = APIClient().post(self.url, {"device_token": "abc", "device_fingerprint": "fp1"}, format="json")
        assert resp.status_code == 401

    def test_register_device(self):
        user = User.objects.create_user(email="rd1@t.com", username="rd1", password="p")
        resp = _auth_client(user).post(
            self.url,
            {"device_token": "fcm-token-123", "device_fingerprint": "fp-abc", "platform": "android"},
            format="json",
        )
        assert resp.status_code == 201
        assert UserDevice.objects.filter(
            user=user, push_token="fcm-token-123",
        ).exists()

    def test_update_existing_device(self):
        user = User.objects.create_user(email="rd2@t.com", username="rd2", password="p")
        UserDevice.objects.create(
            user=user, device_fingerprint="fp-abc", push_token="old-token", platform="android",
        )
        resp = _auth_client(user).post(
            self.url,
            {"device_token": "new-token", "device_fingerprint": "fp-abc", "platform": "ios"},
            format="json",
        )
        assert resp.status_code == 200
        device = UserDevice.objects.get(user=user, device_fingerprint="fp-abc")
        assert device.push_token == "new-token"
        assert device.platform == "ios"

    def test_missing_fingerprint(self):
        user = User.objects.create_user(email="rd3@t.com", username="rd3", password="p")
        resp = _auth_client(user).post(
            self.url, {"device_token": "tok"}, format="json",
        )
        assert resp.status_code == 400


class TestUnregisterDeviceView:
    url = f"{API_ROOT}devices/unregister/"

    def test_unauthenticated(self):
        resp = APIClient().delete(self.url, {"device_token": "abc"}, format="json")
        assert resp.status_code == 401

    def test_unregister_device(self):
        user = User.objects.create_user(email="ud1@t.com", username="ud1", password="p")
        UserDevice.objects.create(
            user=user, device_fingerprint="fp-abc", push_token="fcm-token-123",
        )
        resp = _auth_client(user).delete(self.url, {"device_token": "fcm-token-123"}, format="json")
        assert resp.status_code == 200
        device = UserDevice.objects.get(user=user, device_fingerprint="fp-abc")
        assert device.push_token == ""

    def test_missing_token(self):
        user = User.objects.create_user(email="ud2@t.com", username="ud2", password="p")
        resp = _auth_client(user).delete(self.url, {}, format="json")
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  ChatService message notification integration
# ─────────────────────────────────────────────────────────────────────────────


class TestChatMessageNotifications:

    @patch("notifications.tasks.dispatch_notification.delay")
    def test_send_message_creates_notification_for_other_member(self, mock_dispatch):
        from chats.models import Conversation, ConversationMember, Message
        from chats.services.chat_service import ChatService

        sender = User.objects.create_user(email="cmn1s@t.com", username="cmn1s", password="p")
        recipient = User.objects.create_user(email="cmn1r@t.com", username="cmn1r", password="p")
        conv = Conversation.objects.create()
        ConversationMember.objects.create(conversation=conv, user=sender)
        ConversationMember.objects.create(conversation=conv, user=recipient)

        result = ChatService.send_message(
            conversation_id=str(conv.id),
            sender_id=str(sender.id),
            body="Hello!",
        )

        notif = Notification.objects.filter(
            recipient=recipient,
            notification_type=NotificationType.NEW_MESSAGE.value,
        ).first()
        assert notif is not None
        assert sender.username in notif.title
        assert mock_dispatch.called

    @patch("notifications.tasks.dispatch_notification.delay")
    def test_send_message_does_not_notify_sender(self, mock_dispatch):
        from chats.models import Conversation, ConversationMember
        from chats.services.chat_service import ChatService

        user = User.objects.create_user(email="cmn2@t.com", username="cmn2", password="p")
        conv = Conversation.objects.create()
        ConversationMember.objects.create(conversation=conv, user=user)

        ChatService.send_message(
            conversation_id=str(conv.id),
            sender_id=str(user.id),
            body="Hello!",
        )

        sender_notifs = Notification.objects.filter(
            recipient=user,
        )
        assert sender_notifs.count() == 0

    @patch("notifications.tasks.dispatch_notification.delay")
    def test_send_message_skips_muted_members(self, mock_dispatch):
        from chats.models import Conversation, ConversationMember
        from chats.services.chat_service import ChatService

        sender = User.objects.create_user(email="cmn3s@t.com", username="cmn3s", password="p")
        muted = User.objects.create_user(email="cmn3m@t.com", username="cmn3m", password="p")
        conv = Conversation.objects.create()
        ConversationMember.objects.create(conversation=conv, user=sender)
        ConversationMember.objects.create(conversation=conv, user=muted, is_muted=True)

        ChatService.send_message(
            conversation_id=str(conv.id),
            sender_id=str(sender.id),
            body="Hello!",
        )

        muted_notifs = Notification.objects.filter(
            recipient=muted,
            notification_type=NotificationType.NEW_MESSAGE.value,
        )
        assert muted_notifs.count() == 0

    @patch("notifications.tasks.dispatch_notification.delay")
    def test_send_message_notifies_multiple_members(self, mock_dispatch):
        from chats.models import Conversation, ConversationMember
        from chats.services.chat_service import ChatService

        sender = User.objects.create_user(email="cmn4s@t.com", username="cmn4s", password="p")
        member_a = User.objects.create_user(email="cmn4a@t.com", username="cmn4a", password="p")
        member_b = User.objects.create_user(email="cmn4b@t.com", username="cmn4b", password="p")
        conv = Conversation.objects.create()
        ConversationMember.objects.create(conversation=conv, user=sender)
        ConversationMember.objects.create(conversation=conv, user=member_a)
        ConversationMember.objects.create(conversation=conv, user=member_b)

        ChatService.send_message(
            conversation_id=str(conv.id),
            sender_id=str(sender.id),
            body="Group message!",
        )

        assert Notification.objects.filter(
            recipient=member_a, notification_type=NotificationType.NEW_MESSAGE.value,
        ).exists()
        assert Notification.objects.filter(
            recipient=member_b, notification_type=NotificationType.NEW_MESSAGE.value,
        ).exists()
