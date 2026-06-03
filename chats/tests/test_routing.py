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
