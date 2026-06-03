from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import User
from chats.models import Conversation, ConversationMember, Message, MessageReaction
from utils.enum import (
    ConversationType,
    DeliveryStatus,
    MemberRole,
    MessageType,
)

pytestmark = pytest.mark.django_db


# ─────────────────────────────────────────────────────────────────────────────
#  Conversation
# ─────────────────────────────────────────────────────────────────────────────


class TestConversationModel:
    def test_create_direct(self):
        user = User.objects.create_user(email="c1@t.com", username="c1", password="p")
        conv = Conversation.objects.create(created_by=user)
        assert conv.conversation_type == ConversationType.DIRECT.value
        assert conv.pk is not None
        assert conv.created_at is not None

    def test_create_group(self):
        user = User.objects.create_user(email="c2@t.com", username="c2", password="p")
        conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="Test Group",
            description="A test group",
            created_by=user,
        )
        assert conv.conversation_type == "group"
        assert conv.name == "Test Group"
        assert conv.description == "A test group"

    def test_channel_group_name(self):
        user = User.objects.create_user(email="c3@t.com", username="c3", password="p")
        conv = Conversation.objects.create(created_by=user)
        assert conv.get_channel_group_name() == f"chat_{conv.id}"

    def test_str_direct(self):
        user = User.objects.create_user(email="c4@t.com", username="c4", password="p")
        conv = Conversation.objects.create(created_by=user)
        assert "Direct" in str(conv)

    def test_str_group(self):
        user = User.objects.create_user(email="c5@t.com", username="c5", password="p")
        conv = Conversation.objects.create(
            conversation_type=ConversationType.GROUP.value,
            name="My Group",
            created_by=user,
        )
        assert "My Group" in str(conv)

    def test_default_ordering(self):
        user = User.objects.create_user(email="c6@t.com", username="c6", password="p")
        old = Conversation.objects.create(created_by=user)
        new = Conversation.objects.create(created_by=user)
        Conversation.objects.filter(pk=old.pk).update(
            last_message_at=timezone.now() - timezone.timedelta(hours=1),
        )
        Conversation.objects.filter(pk=new.pk).update(
            last_message_at=timezone.now(),
        )
        qs = Conversation.objects.all()
        assert qs[0] == new
        assert qs[1] == old


# ─────────────────────────────────────────────────────────────────────────────
#  ConversationMember
# ─────────────────────────────────────────────────────────────────────────────


class TestConversationMemberModel:
    def test_create_member(self):
        user = User.objects.create_user(email="m1@t.com", username="m1", password="p")
        conv = Conversation.objects.create(created_by=user)
        member = ConversationMember.objects.create(conversation=conv, user=user)
        assert member.role == MemberRole.MEMBER.value
        assert member.is_muted is False
        assert member.unread_count == 0
        assert member.is_active is True
        assert member.pk is not None

    def test_unique_together(self):
        user = User.objects.create_user(email="m2@t.com", username="m2", password="p")
        conv = Conversation.objects.create(created_by=user)
        ConversationMember.objects.create(conversation=conv, user=user)
        with pytest.raises(IntegrityError):
            ConversationMember.objects.create(conversation=conv, user=user)

    def test_is_active_false_when_left(self):
        user = User.objects.create_user(email="m3@t.com", username="m3", password="p")
        conv = Conversation.objects.create(created_by=user)
        member = ConversationMember.objects.create(
            conversation=conv, user=user, left_at=timezone.now(),
        )
        assert member.is_active is False

    def test_str(self):
        user = User.objects.create_user(email="m4@t.com", username="m4", password="p")
        conv = Conversation.objects.create(created_by=user)
        member = ConversationMember.objects.create(conversation=conv, user=user)
        assert "m4" in str(member)
        assert "member" in str(member)

    def test_default_role_is_member(self):
        user = User.objects.create_user(email="m5@t.com", username="m5", password="p")
        conv = Conversation.objects.create(created_by=user)
        member = ConversationMember.objects.create(conversation=conv, user=user)
        assert member.role == "member"


# ─────────────────────────────────────────────────────────────────────────────
#  Message
# ─────────────────────────────────────────────────────────────────────────────


class TestMessageModel:
    def test_create_text_message(self):
        user = User.objects.create_user(email="msg1@t.com", username="msg1", password="p")
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(
            conversation=conv, sender=user, body="Hello!",
        )
        assert msg.message_type == MessageType.TEXT.value
        assert msg.body == "Hello!"
        assert msg.delivery_status == DeliveryStatus.SENT.value
        assert msg.is_edited is False
        assert msg.pk is not None

    def test_soft_delete_clears_content(self):
        user = User.objects.create_user(email="msg2@t.com", username="msg2", password="p")
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(
            conversation=conv, sender=user, body="Sensitive content",
        )
        msg.soft_delete()
        msg.refresh_from_db()
        assert msg.body == ""
        assert msg.is_deleted is True
        assert msg.deleted_at is not None

    def test_to_event_payload(self):
        user = User.objects.create_user(
            email="msg3@t.com", username="msg3", password="p",
            is_active=True,
        )
        user.save()
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(
            conversation=conv, sender=user, body="Hi",
        )
        payload = msg.to_event_payload()
        assert payload["body"] == "Hi"
        assert payload["sender_id"] == str(user.id)
        assert payload["conversation_id"] == str(conv.id)
        assert payload["message_type"] == "text"
        assert payload["is_edited"] is False
        assert payload["reply_to_id"] is None
        assert payload["media_url"] is None

    def test_reply_to(self):
        user = User.objects.create_user(email="msg4@t.com", username="msg4", password="p")
        conv = Conversation.objects.create(created_by=user)
        original = Message.objects.create(conversation=conv, sender=user, body="Original")
        reply = Message.objects.create(
            conversation=conv, sender=user, body="Reply", reply_to=original,
        )
        assert reply.reply_to == original

    def test_str(self):
        user = User.objects.create_user(email="msg5@t.com", username="msg5", password="p")
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(conversation=conv, sender=user, body="Test")
        assert "msg5" in str(msg)
        assert str(conv.id) in str(msg)

    def test_default_ordering_oldest_first(self):
        user = User.objects.create_user(email="msg6@t.com", username="msg6", password="p")
        conv = Conversation.objects.create(created_by=user)
        m1 = Message.objects.create(conversation=conv, sender=user, body="First")
        m2 = Message.objects.create(conversation=conv, sender=user, body="Second")
        qs = Message.objects.all()
        assert list(qs) == [m1, m2]

    def test_location_coordinates(self):
        user = User.objects.create_user(email="msg7@t.com", username="msg7", password="p")
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(
            conversation=conv, sender=user,
            message_type=MessageType.LOCATION.value,
            latitude=Decimal("48.8566"),
            longitude=Decimal("2.3522"),
        )
        assert float(msg.latitude) == 48.8566


# ─────────────────────────────────────────────────────────────────────────────
#  MessageReaction
# ─────────────────────────────────────────────────────────────────────────────


class TestMessageReactionModel:
    def test_create_reaction(self):
        user = User.objects.create_user(email="r1@t.com", username="r1", password="p")
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(conversation=conv, sender=user, body="Hi")
        react = MessageReaction.objects.create(message=msg, user=user, emoji="👍")
        assert react.emoji == "👍"
        assert react.pk is not None

    def test_unique_together_message_user_emoji(self):
        user = User.objects.create_user(email="r2@t.com", username="r2", password="p")
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(conversation=conv, sender=user, body="Hi")
        MessageReaction.objects.create(message=msg, user=user, emoji="👍")
        with pytest.raises(IntegrityError):
            MessageReaction.objects.create(message=msg, user=user, emoji="👍")

    def test_same_user_different_emoji_allowed(self):
        user = User.objects.create_user(email="r3@t.com", username="r3", password="p")
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(conversation=conv, sender=user, body="Hi")
        MessageReaction.objects.create(message=msg, user=user, emoji="👍")
        MessageReaction.objects.create(message=msg, user=user, emoji="❤️")
        assert MessageReaction.objects.count() == 2

    def test_str(self):
        user = User.objects.create_user(email="r4@t.com", username="r4", password="p")
        conv = Conversation.objects.create(created_by=user)
        msg = Message.objects.create(conversation=conv, sender=user, body="Hi")
        react = MessageReaction.objects.create(message=msg, user=user, emoji="🔥")
        assert "🔥" in str(react)
        assert "r4" in str(react)
