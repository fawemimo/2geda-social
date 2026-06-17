from __future__ import annotations

from uuid import UUID

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from chats import views


class TestURLs(SimpleTestCase):
    def test_conversations_url_resolves(self):
        url = "/api/v2/chats/conversations/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.ConversationListView

    def test_conversation_create_url_resolves(self):
        url = "/api/v2/chats/conversations/create/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.ConversationCreateView

    def test_conversation_messages_url_resolves(self):
        url = "/api/v2/chats/conversations/00000000-0000-0000-0000-000000000000/messages/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.ConversationMessagesView

    def test_conversation_messages_url_captures_uuid(self):
        url = "/api/v2/chats/conversations/11111111-1111-1111-1111-111111111111/messages/"
        resolver = resolve(url)
        assert resolver.kwargs["conversation_id"] == UUID("11111111-1111-1111-1111-111111111111")

    def test_reverse_conversations(self):
        url = reverse("chats:conversations")
        assert url == "/api/v2/chats/conversations/"

    def test_reverse_conversation_create(self):
        url = reverse("chats:conversation-create")
        assert url == "/api/v2/chats/conversations/create/"

    def test_group_create_url_resolves(self):
        url = "/api/v2/chats/groups/create/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.GroupCreateView

    def test_group_members_url_resolves(self):
        url = "/api/v2/chats/groups/00000000-0000-0000-0000-000000000000/members/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.GroupManageMembersView

    def test_group_lock_url_resolves(self):
        url = "/api/v2/chats/groups/00000000-0000-0000-0000-000000000000/lock/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.GroupLockToggleView

    def test_message_delete_url_resolves(self):
        url = "/api/v2/chats/messages/00000000-0000-0000-0000-000000000000/delete/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.MessageDeleteView

    def test_group_join_url_resolves(self):
        url = "/api/v2/chats/groups/00000000-0000-0000-0000-000000000000/join/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.GroupJoinRequestView

    def test_group_join_requests_url_resolves(self):
        url = "/api/v2/chats/groups/00000000-0000-0000-0000-000000000000/join-requests/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.GroupJoinRequestListView

    def test_group_join_request_process_url_resolves(self):
        url = "/api/v2/chats/groups/00000000-0000-0000-0000-000000000000/join-requests/11111111-1111-1111-1111-111111111111/process/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.GroupJoinRequestProcessView

    def test_group_promote_url_resolves(self):
        url = "/api/v2/chats/groups/00000000-0000-0000-0000-000000000000/promote/"
        resolver = resolve(url)
        assert resolver.func.view_class is views.GroupPromoteAdminView
