from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from chats.models import Conversation, ConversationMember

pytestmark = pytest.mark.django_db

API_ROOT = "/api/v2/chats/"


def _auth_client(user: User) -> APIClient:
    user.is_active = True
    user.save(update_fields=["is_active"])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


# ─────────────────────────────────────────────────────────────────────────────
#  ConversationListView
# ─────────────────────────────────────────────────────────────────────────────


class TestConversationListView:
    url = f"{API_ROOT}conversations/"

    def test_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_success_empty(self):
        user = User.objects.create_user(email="cl1@t.com", username="cl1", password="p")
        resp = _auth_client(user).get(self.url)
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_success_with_conversations(self):
        user_a = User.objects.create_user(email="cl2a@t.com", username="cl2a", password="p")
        user_b = User.objects.create_user(email="cl2b@t.com", username="cl2b", password="p")
        conv = Conversation.objects.create(created_by=user_a)
        ConversationMember.objects.create(conversation=conv, user=user_a)
        ConversationMember.objects.create(conversation=conv, user=user_b)
        resp = _auth_client(user_a).get(self.url)
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.data["data"]]
        assert str(conv.id) in ids


# ─────────────────────────────────────────────────────────────────────────────
#  ConversationCreateView
# ─────────────────────────────────────────────────────────────────────────────


class TestConversationCreateView:
    url = f"{API_ROOT}conversations/create/"

    def test_unauthenticated(self):
        resp = APIClient().post(self.url, {"recipient_id": "00000000-0000-0000-0000-000000000000"}, format="json")
        assert resp.status_code == 401

    def test_create_new(self):
        user_a = User.objects.create_user(email="cc1a@t.com", username="cc1a", password="p")
        user_b = User.objects.create_user(email="cc1b@t.com", username="cc1b", password="p")
        resp = _auth_client(user_a).post(self.url, {"recipient_id": str(user_b.pk)}, format="json")
        assert resp.status_code == 201
        assert resp.data["data"]["conversation_type"] == "direct"

    def test_return_existing(self):
        user_a = User.objects.create_user(email="cc2a@t.com", username="cc2a", password="p")
        user_b = User.objects.create_user(email="cc2b@t.com", username="cc2b", password="p")
        conv = Conversation.objects.create(created_by=user_a)
        ConversationMember.objects.create(conversation=conv, user=user_a)
        ConversationMember.objects.create(conversation=conv, user=user_b)
        resp = _auth_client(user_a).post(self.url, {"recipient_id": str(user_b.pk)}, format="json")
        assert resp.status_code == 200

    def test_missing_recipient(self):
        user = User.objects.create_user(email="cc3@t.com", username="cc3", password="p")
        resp = _auth_client(user).post(self.url, {}, format="json")
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  ConversationMessagesView
# ─────────────────────────────────────────────────────────────────────────────


class TestConversationMessagesView:
    def test_unauthenticated(self):
        resp = APIClient().get(
            f"{API_ROOT}conversations/00000000-0000-0000-0000-000000000000/messages/",
        )
        assert resp.status_code == 401

    def test_conversation_not_found(self):
        user = User.objects.create_user(email="cm1@t.com", username="cm1", password="p")
        resp = _auth_client(user).get(
            f"{API_ROOT}conversations/00000000-0000-0000-0000-000000000000/messages/",
        )
        assert resp.status_code == 404

    def test_access_denied_not_member(self):
        owner = User.objects.create_user(email="cm2o@t.com", username="cm2o", password="p")
        intruder = User.objects.create_user(email="cm2i@t.com", username="cm2i", password="p")
        conv = Conversation.objects.create(created_by=owner)
        ConversationMember.objects.create(conversation=conv, user=owner)
        resp = _auth_client(intruder).get(
            f"{API_ROOT}conversations/{conv.pk}/messages/",
        )
        assert resp.status_code == 404

    def test_success_empty(self):
        user = User.objects.create_user(email="cm3@t.com", username="cm3", password="p")
        conv = Conversation.objects.create(created_by=user)
        ConversationMember.objects.create(conversation=conv, user=user)
        resp = _auth_client(user).get(
            f"{API_ROOT}conversations/{conv.pk}/messages/",
        )
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_success_with_messages(self):
        user = User.objects.create_user(email="cm4@t.com", username="cm4", password="p")
        conv = Conversation.objects.create(created_by=user)
        ConversationMember.objects.create(conversation=conv, user=user)
        from chats.models import Message

        for i in range(3):
            Message.objects.create(conversation=conv, sender=user, body=f"msg{i}")
        resp = _auth_client(user).get(
            f"{API_ROOT}conversations/{conv.pk}/messages/",
        )
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 3


# ─────────────────────────────────────────────────────────────────────────────
#  UserPresenceView
# ─────────────────────────────────────────────────────────────────────────────


class TestUserPresenceView:
    url = f"{API_ROOT}presence/"

    def test_unauthenticated(self):
        resp = APIClient().get(self.url)
        assert resp.status_code == 401

    def test_empty_user_ids(self):
        user = User.objects.create_user(email="pv1@t.com", username="pv1", password="p")
        resp = _auth_client(user).get(self.url)
        assert resp.status_code == 200
        assert resp.data["data"]["online_users"] == []

    def test_with_user_ids(self):
        user = User.objects.create_user(email="pv2@t.com", username="pv2", password="p")
        resp = _auth_client(user).get(self.url, {"user_ids": "00000000-0000-0000-0000-000000000001"})
        assert resp.status_code == 200
        assert isinstance(resp.data["data"]["online_users"], list)
