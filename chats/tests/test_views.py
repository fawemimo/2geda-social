from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from chats.models import Conversation, ConversationMember, JoinRequest, Message
from chats.services import ChatService
from medias.models import Media
from utils.enum import ConversationType, MemberRole

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


# ─────────────────────────────────────────────────────────────────────────────
#  GroupCreateView
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupCreateView:
    url = f"{API_ROOT}groups/create/"

    def _create_users(self, n: int) -> list[User]:
        return [
            User.objects.create_user(
                email=f"gc{i}@t.com", username=f"gc{i}", password="p",
            )
            for i in range(n)
        ]

    def test_unauthenticated(self):
        resp = APIClient().post(self.url, {}, format="json")
        assert resp.status_code == 401

    def test_too_few_members(self):
        users = self._create_users(2)
        resp = _auth_client(users[0]).post(self.url, {
            "name": "Test Group",
            "member_ids": [str(users[1].pk)],
        }, format="json")
        assert resp.status_code == 400
        assert resp.data["status"] is False

    def test_too_many_members(self):
        users = self._create_users(201)
        ids = [str(u.pk) for u in users[1:]]
        resp = _auth_client(users[0]).post(self.url, {
            "name": "Big Group",
            "member_ids": ids,
        }, format="json")
        assert resp.status_code == 400

    def test_successful_creation(self):
        users = self._create_users(5)
        member_ids = [str(u.pk) for u in users[1:]]
        resp = _auth_client(users[0]).post(self.url, {
            "name": "Test Group",
            "description": "A test group",
            "member_ids": member_ids,
        }, format="json")
        assert resp.status_code == 201
        data = resp.data["data"]
        assert data["conversation_type"] == "group"
        assert data["name"] == "Test Group"
        assert data["description"] == "A test group"
        assert len(data["members"]) == 5

    def test_creator_is_owner(self):
        users = self._create_users(3)
        member_ids = [str(u.pk) for u in users[1:]]
        resp = _auth_client(users[0]).post(self.url, {
            "name": "Owner Test",
            "member_ids": member_ids,
        }, format="json")
        assert resp.status_code == 201
        owner_member = next(
            m for m in resp.data["data"]["members"]
            if m["user_id"] == str(users[0].pk)
        )
        assert owner_member["role"] == "owner"


# ─────────────────────────────────────────────────────────────────────────────
#  GroupManageMembersView (add / remove)
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupManageMembersView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.owner = User.objects.create_user(email="gm_o@t.com", username="gm_o", password="p")
        self.admin = User.objects.create_user(email="gm_a@t.com", username="gm_a", password="p")
        self.member1 = User.objects.create_user(email="gm_m1@t.com", username="gm_m1", password="p")
        self.member2 = User.objects.create_user(email="gm_m2@t.com", username="gm_m2", password="p")
        self.outsider = User.objects.create_user(email="gm_x@t.com", username="gm_x", password="p")
        self.conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="Test Group",
            created_by=self.owner,
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.owner, role=MemberRole.OWNER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.admin, role=MemberRole.ADMIN.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member1, role=MemberRole.MEMBER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member2, role=MemberRole.MEMBER.value)

    def add_url(self):
        return f"{API_ROOT}groups/{self.conv.pk}/members/"

    def test_unauthenticated(self):
        resp = APIClient().post(self.add_url(), {}, format="json")
        assert resp.status_code == 401

    def test_add_members_success(self):
        resp = _auth_client(self.owner).post(self.add_url(), {
            "member_ids": [str(self.outsider.pk)],
        }, format="json")
        assert resp.status_code == 200
        uuids = [m["user_id"] for m in resp.data["data"]["members"]]
        assert str(self.outsider.pk) in uuids

    def test_add_members_non_admin_fails(self):
        resp = _auth_client(self.member1).post(self.add_url(), {
            "member_ids": [str(self.outsider.pk)],
        }, format="json")
        assert resp.status_code == 403

    def test_add_members_admin_can_add(self):
        resp = _auth_client(self.admin).post(self.add_url(), {
            "member_ids": [str(self.outsider.pk)],
        }, format="json")
        assert resp.status_code == 200

    def test_remove_member_success(self):
        resp = _auth_client(self.owner).delete(
            self.add_url(),
            {"user_id": str(self.member2.pk)},
            format="json",
        )
        assert resp.status_code == 200

    def test_remove_member_non_admin_fails(self):
        resp = _auth_client(self.member1).delete(
            self.add_url(),
            {"user_id": str(self.member2.pk)},
            format="json",
        )
        assert resp.status_code == 403

    def test_remove_owner_fails(self):
        resp = _auth_client(self.admin).delete(
            self.add_url(),
            {"user_id": str(self.owner.pk)},
            format="json",
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  GroupLockToggleView
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupLockToggleView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.owner = User.objects.create_user(email="gl_o@t.com", username="gl_o", password="p")
        self.admin = User.objects.create_user(email="gl_a@t.com", username="gl_a", password="p")
        self.member = User.objects.create_user(email="gl_m@t.com", username="gl_m", password="p")
        self.conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="Lock Test",
            created_by=self.owner,
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.owner, role=MemberRole.OWNER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.admin, role=MemberRole.ADMIN.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member, role=MemberRole.MEMBER.value)

    def lock_url(self):
        return f"{API_ROOT}groups/{self.conv.pk}/lock/"

    def test_unauthenticated(self):
        resp = APIClient().post(self.lock_url(), {}, format="json")
        assert resp.status_code == 401

    def test_owner_can_lock(self):
        resp = _auth_client(self.owner).post(self.lock_url(), {}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["is_locked"] is True

    def test_owner_can_unlock(self):
        self.conv.is_locked = True
        self.conv.save(update_fields=["is_locked"])
        resp = _auth_client(self.owner).post(self.lock_url(), {}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["is_locked"] is False

    def test_admin_can_lock(self):
        resp = _auth_client(self.admin).post(self.lock_url(), {}, format="json")
        assert resp.status_code == 200

    def test_member_cannot_lock(self):
        resp = _auth_client(self.member).post(self.lock_url(), {}, format="json")
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  MessageDeleteView
# ─────────────────────────────────────────────────────────────────────────────


class TestMessageDeleteView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.owner = User.objects.create_user(email="md_o@t.com", username="md_o", password="p")
        self.admin = User.objects.create_user(email="md_a@t.com", username="md_a", password="p")
        self.member = User.objects.create_user(email="md_m@t.com", username="md_m", password="p")
        self.conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="Delete Test",
            created_by=self.owner,
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.owner, role=MemberRole.OWNER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.admin, role=MemberRole.ADMIN.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member, role=MemberRole.MEMBER.value)

    def _msg(self, sender: User) -> Message:
        return Message.objects.create(conversation=self.conv, sender=sender, body="test")

    def delete_url(self, msg: Message) -> str:
        return f"{API_ROOT}messages/{msg.pk}/delete/"

    def test_unauthenticated(self):
        msg = self._msg(self.member)
        resp = APIClient().delete(self.delete_url(msg), {}, format="json")
        assert resp.status_code == 401

    def test_author_can_delete_own_message(self):
        msg = self._msg(self.member)
        resp = _auth_client(self.member).delete(self.delete_url(msg), {}, format="json")
        assert resp.status_code == 200

    def test_admin_can_delete_any_message(self):
        msg = self._msg(self.member)
        resp = _auth_client(self.admin).delete(self.delete_url(msg), {}, format="json")
        assert resp.status_code == 200

    def test_owner_can_delete_any_message(self):
        msg = self._msg(self.member)
        resp = _auth_client(self.owner).delete(self.delete_url(msg), {}, format="json")
        assert resp.status_code == 200

    def test_other_member_cannot_delete_others_message(self):
        msg = self._msg(self.member)
        other = User.objects.create_user(email="md_other@t.com", username="md_other", password="p")
        ConversationMember.objects.create(conversation=self.conv, user=other, role=MemberRole.MEMBER.value)
        resp = _auth_client(other).delete(self.delete_url(msg), {}, format="json")
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  GroupJoinRequestView
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupJoinRequestView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.owner = User.objects.create_user(email="jr_o@t.com", username="jr_o", password="p")
        self.member = User.objects.create_user(email="jr_m@t.com", username="jr_m", password="p")
        self.new_user = User.objects.create_user(email="jr_n@t.com", username="jr_n", password="p")
        self.conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="Join Test",
            created_by=self.owner,
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.owner, role=MemberRole.OWNER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member, role=MemberRole.MEMBER.value)

    def join_url(self):
        return f"{API_ROOT}groups/{self.conv.pk}/join/"

    def test_unauthenticated(self):
        resp = APIClient().post(self.join_url(), {}, format="json")
        assert resp.status_code == 401

    def test_successful_join_request(self):
        resp = _auth_client(self.new_user).post(self.join_url(), {}, format="json")
        assert resp.status_code == 201

    def test_existing_member_cannot_request(self):
        resp = _auth_client(self.member).post(self.join_url(), {}, format="json")
        assert resp.status_code == 403

    def test_duplicate_pending_request_fails(self):
        _auth_client(self.new_user).post(self.join_url(), {}, format="json")
        resp = _auth_client(self.new_user).post(self.join_url(), {}, format="json")
        assert resp.status_code == 403

    def test_direct_conversation_rejects_join(self):
        direct = Conversation.objects.create(created_by=self.owner)
        ConversationMember.objects.create(conversation=direct, user=self.owner)
        ConversationMember.objects.create(conversation=direct, user=self.member)
        url = f"{API_ROOT}groups/{direct.pk}/join/"
        resp = _auth_client(self.new_user).post(url, {}, format="json")
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  GroupJoinRequestListView
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupJoinRequestListView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.owner = User.objects.create_user(email="jrl_o@t.com", username="jrl_o", password="p")
        self.admin = User.objects.create_user(email="jrl_a@t.com", username="jrl_a", password="p")
        self.member = User.objects.create_user(email="jrl_m@t.com", username="jrl_m", password="p")
        self.applicant = User.objects.create_user(email="jrl_n@t.com", username="jrl_n", password="p")
        self.conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="List Test",
            created_by=self.owner,
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.owner, role=MemberRole.OWNER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.admin, role=MemberRole.ADMIN.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member, role=MemberRole.MEMBER.value)

    def list_url(self):
        return f"{API_ROOT}groups/{self.conv.pk}/join-requests/"

    def test_owner_can_view_pending(self):
        JoinRequest.objects.create(conversation=self.conv, user=self.applicant)
        resp = _auth_client(self.owner).get(self.list_url())
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1

    def test_admin_can_view_pending(self):
        JoinRequest.objects.create(conversation=self.conv, user=self.applicant)
        resp = _auth_client(self.admin).get(self.list_url())
        assert resp.status_code == 200

    def test_member_cannot_view_pending(self):
        JoinRequest.objects.create(conversation=self.conv, user=self.applicant)
        resp = _auth_client(self.member).get(self.list_url())
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  GroupJoinRequestProcessView
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupJoinRequestProcessView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.owner = User.objects.create_user(email="jrp_o@t.com", username="jrp_o", password="p")
        self.admin = User.objects.create_user(email="jrp_a@t.com", username="jrp_a", password="p")
        self.member = User.objects.create_user(email="jrp_m@t.com", username="jrp_m", password="p")
        self.applicant = User.objects.create_user(email="jrp_n@t.com", username="jrp_n", password="p")
        self.conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="Process Test",
            created_by=self.owner,
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.owner, role=MemberRole.OWNER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.admin, role=MemberRole.ADMIN.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member, role=MemberRole.MEMBER.value)

    def _create_request(self) -> str:
        jr = JoinRequest.objects.create(conversation=self.conv, user=self.applicant)
        return str(jr.pk)

    def process_url(self, request_id: str, action: str = "approve") -> str:
        return f"{API_ROOT}groups/{self.conv.pk}/join-requests/{request_id}/process/?action={action}"

    def test_owner_can_approve(self):
        req_id = self._create_request()
        resp = _auth_client(self.owner).post(self.process_url(req_id, "approve"), {}, format="json")
        assert resp.status_code == 200

    def test_admin_can_approve(self):
        req_id = self._create_request()
        resp = _auth_client(self.admin).post(self.process_url(req_id, "approve"), {}, format="json")
        assert resp.status_code == 200

    def test_member_cannot_approve(self):
        req_id = self._create_request()
        resp = _auth_client(self.member).post(self.process_url(req_id, "approve"), {}, format="json")
        assert resp.status_code == 403

    def test_approve_adds_as_member(self):
        req_id = self._create_request()
        _auth_client(self.owner).post(self.process_url(req_id, "approve"), {}, format="json")
        is_member = ConversationMember.objects.filter(
            conversation=self.conv, user=self.applicant, left_at__isnull=True
        ).exists()
        assert is_member is True

    def test_owner_can_reject(self):
        req_id = self._create_request()
        resp = _auth_client(self.owner).post(self.process_url(req_id, "reject"), {}, format="json")
        assert resp.status_code == 200

    def test_process_twice_fails(self):
        req_id = self._create_request()
        _auth_client(self.owner).post(self.process_url(req_id, "approve"), {}, format="json")
        resp = _auth_client(self.owner).post(self.process_url(req_id, "approve"), {}, format="json")
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  GroupPromoteAdminView
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupPromoteAdminView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.owner = User.objects.create_user(email="gp_o@t.com", username="gp_o", password="p")
        self.admin = User.objects.create_user(email="gp_a@t.com", username="gp_a", password="p")
        self.member = User.objects.create_user(email="gp_m@t.com", username="gp_m", password="p")
        self.conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="Promote Test",
            created_by=self.owner,
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.owner, role=MemberRole.OWNER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.admin, role=MemberRole.ADMIN.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member, role=MemberRole.MEMBER.value)

    def promote_url(self):
        return f"{API_ROOT}groups/{self.conv.pk}/promote/"

    def test_owner_can_promote(self):
        resp = _auth_client(self.owner).post(self.promote_url(), {"user_id": str(self.member.pk)}, format="json")
        assert resp.status_code == 200

    def test_admin_can_promote(self):
        resp = _auth_client(self.admin).post(self.promote_url(), {"user_id": str(self.member.pk)}, format="json")
        assert resp.status_code == 200

    def test_member_cannot_promote(self):
        resp = _auth_client(self.member).post(self.promote_url(), {"user_id": str(self.member.pk)}, format="json")
        assert resp.status_code == 403

    def test_promote_owner_fails(self):
        resp = _auth_client(self.admin).post(self.promote_url(), {"user_id": str(self.owner.pk)}, format="json")
        assert resp.status_code == 400

    def test_promote_existing_admin_fails(self):
        resp = _auth_client(self.owner).post(self.promote_url(), {"user_id": str(self.admin.pk)}, format="json")
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  Auto-assign admin on admin leave (service layer)
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoAssignAdmin:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.owner = User.objects.create_user(email="aa_o@t.com", username="aa_o", password="p")
        self.admin = User.objects.create_user(email="aa_a@t.com", username="aa_a", password="p")
        self.member1 = User.objects.create_user(email="aa_m1@t.com", username="aa_m1", password="p")
        self.member2 = User.objects.create_user(email="aa_m2@t.com", username="aa_m2", password="p")
        self.conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="AutoAdmin Test",
            created_by=self.owner,
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.owner, role=MemberRole.OWNER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.admin, role=MemberRole.ADMIN.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member1, role=MemberRole.MEMBER.value)
        ConversationMember.objects.create(conversation=self.conv, user=self.member2, role=MemberRole.MEMBER.value)

    def test_oldest_member_promoted_when_no_admins_remain(self):
        ConversationMember.objects.filter(
            conversation=self.conv,
            user__in=[self.owner, self.admin],
        ).update(left_at=timezone.now())

        ChatService._auto_assign_admin_on_leave(str(self.conv.pk))

        promoted = ConversationMember.objects.get(
            conversation=self.conv, user=self.member1,
        )
        assert promoted.role == MemberRole.ADMIN.value

    def test_no_promotion_when_other_admins_remain(self):
        another_admin = User.objects.create_user(email="aa_extra@t.com", username="aa_extra", password="p")
        ConversationMember.objects.create(conversation=self.conv, user=another_admin, role=MemberRole.ADMIN.value)

        ConversationMember.objects.filter(
            conversation=self.conv, user=self.owner,
        ).update(left_at=timezone.now())

        ChatService._auto_assign_admin_on_leave(str(self.conv.pk))

        remaining = ConversationMember.objects.filter(
            conversation=self.conv, left_at__isnull=True,
            role__in=[MemberRole.ADMIN.value, MemberRole.OWNER.value],
        )
        assert remaining.count() == 1
        assert remaining.first().user_id == another_admin.pk

    def test_no_promotion_when_other_admins_remain(self):
        another_admin = User.objects.create_user(email="aa_extra@t.com", username="aa_extra", password="p")
        ConversationMember.objects.create(conversation=self.conv, user=another_admin, role=MemberRole.ADMIN.value)

        ChatService.remove_group_member(
            conversation_id=str(self.conv.pk),
            actor_id=str(self.owner.pk),
            target_user_id=str(self.admin.pk),
        )
        remaining_admins = ConversationMember.objects.filter(
            conversation=self.conv, left_at__isnull=True,
            role__in=[MemberRole.ADMIN.value, MemberRole.OWNER.value],
        )
        assert remaining_admins.count() == 2


# ─────────────────────────────────────────────────────────────────────────────
#  Chat Search Views
# ─────────────────────────────────────────────────────────────────────────────


class TestChatSearchMessagesView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.user = User.objects.create_user(email="sm1@t.com", username="sm1", password="p")
        self.other = User.objects.create_user(email="sm2@t.com", username="sm2", password="p")
        self.conv = Conversation.objects.create(created_by=self.user)
        ConversationMember.objects.create(conversation=self.conv, user=self.user)
        ConversationMember.objects.create(conversation=self.conv, user=self.other)
        self.url = f"{API_ROOT}search/messages/"

    def _msg(self, body: str) -> Message:
        return Message.objects.create(conversation=self.conv, sender=self.user, body=body)

    def test_unauthenticated(self):
        resp = APIClient().get(self.url, {"q": "hello"})
        assert resp.status_code == 401

    def test_empty_query_returns_empty(self):
        resp = _auth_client(self.user).get(self.url, {"q": ""})
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_search_finds_messages(self):
        self._msg("hello world")
        self._msg("goodbye")
        resp = _auth_client(self.user).get(self.url, {"q": "hello"})
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["body"] == "hello world"

    def test_search_ignores_other_conversations(self):
        other_conv = Conversation.objects.create(created_by=self.other)
        ConversationMember.objects.create(conversation=other_conv, user=self.other)
        Message.objects.create(conversation=other_conv, sender=self.other, body="secret")
        resp = _auth_client(self.user).get(self.url, {"q": "secret"})
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_search_in_specific_conversation(self):
        self._msg("hello in conv1")
        conv2 = Conversation.objects.create(created_by=self.user)
        ConversationMember.objects.create(conversation=conv2, user=self.user)
        Message.objects.create(conversation=conv2, sender=self.user, body="hello in conv2")
        resp = _auth_client(self.user).get(
            self.url, {"q": "hello", "conversation_id": str(self.conv.pk)},
        )
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1
        assert str(resp.data["data"][0]["conversation_id"]) == str(self.conv.pk)


class TestChatSearchConversationsView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.user = User.objects.create_user(email="sc1@t.com", username="sc1", password="p")
        self.url = f"{API_ROOT}search/conversations/"

    def test_unauthenticated(self):
        resp = APIClient().get(self.url, {"q": "test"})
        assert resp.status_code == 401

    def test_finds_group_by_name(self):
        conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="Football Fans",
            created_by=self.user,
        )
        ConversationMember.objects.create(conversation=conv, user=self.user)
        resp = _auth_client(self.user).get(self.url, {"q": "football"})
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["name"] == "Football Fans"

    def test_does_not_return_direct(self):
        conv = Conversation.objects.create(created_by=self.user)
        ConversationMember.objects.create(conversation=conv, user=self.user)
        resp = _auth_client(self.user).get(self.url, {"q": ""})
        assert resp.status_code == 200


class TestChatSearchUsersView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.user = User.objects.create_user(
            email="su1@t.com", username="su1", password="p", is_active=True,
        )
        self.url = f"{API_ROOT}search/users/"

    def test_unauthenticated(self):
        resp = APIClient().get(self.url, {"q": "test"})
        assert resp.status_code == 401

    def test_finds_by_username(self):
        target = User.objects.create_user(
            email="findme@t.com", username="john_doe", password="p", is_active=True,
        )
        resp = _auth_client(self.user).get(self.url, {"q": "john"})
        assert resp.status_code == 200
        usernames = [u["username"] for u in resp.data["data"]]
        assert "john_doe" in usernames

    def test_finds_by_email(self):
        target = User.objects.create_user(
            email="findme@t.com", username="someone", password="p", is_active=True,
        )
        resp = _auth_client(self.user).get(self.url, {"q": "findme"})
        assert resp.status_code == 200
        emails = [u["email"] for u in resp.data["data"]]
        assert "findme@t.com" in emails

    def test_finds_by_display_name(self):
        target = User.objects.create_user(
            email="dn@t.com", username="dn_user", password="p", is_active=True,
        )
        target.profile.display_name = "Alice Wonderland"
        target.profile.save()
        resp = _auth_client(self.user).get(self.url, {"q": "alice"})
        assert resp.status_code == 200
        usernames = [u["username"] for u in resp.data["data"]]
        assert "dn_user" in usernames

    def test_does_not_return_inactive_users(self):
        User.objects.create_user(
            email="inactive@t.com", username="inactive_user", password="p", is_active=False,
        )
        resp = _auth_client(self.user).get(self.url, {"q": "inactive"})
        assert resp.status_code == 200
        assert resp.data["data"] == []


class TestChatSearchMediaView:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        self.user = User.objects.create_user(email="smd1@t.com", username="smd1", password="p")
        self.url = f"{API_ROOT}search/media/"
        self.conv = Conversation.objects.create(created_by=self.user)
        ConversationMember.objects.create(conversation=self.conv, user=self.user)

    def _media(self, filename: str, media_type: str = "image") -> Media:
        return Media.objects.create(
            owner=self.user,
            media_type=media_type,
            original_filename=filename,
            storage_key=f"uploads/{filename}",
        )

    def _msg_with_media(self, body: str, media) -> Message:
        return Message.objects.create(
            conversation=self.conv, sender=self.user,
            body=body, media=media,
        )

    def test_unauthenticated(self):
        resp = APIClient().get(self.url, {"q": "photo"})
        assert resp.status_code == 401

    def test_empty_query_returns_empty(self):
        resp = _auth_client(self.user).get(self.url, {"q": ""})
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_finds_by_filename(self):
        media = self._media("vacation_photo.jpg")
        self._msg_with_media("Check this out", media)
        resp = _auth_client(self.user).get(self.url, {"q": "vacation"})
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["media_filename"] == "vacation_photo.jpg"

    def test_filters_by_media_type(self):
        img = self._media("photo.jpg", "image")
        vid = self._media("video.mp4", "video")
        self._msg_with_media("photo msg", img)
        self._msg_with_media("video msg", vid)
        resp = _auth_client(self.user).get(self.url, {"q": ".", "media_type": "video"})
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["media_type"] == "video"

    def test_ignores_messages_without_media(self):
        Message.objects.create(conversation=self.conv, sender=self.user, body="no media")
        resp = _auth_client(self.user).get(self.url, {"q": "no"})
        assert resp.status_code == 200
        assert resp.data["data"] == []
