from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from polls.enums import PollStatus, PollType
from polls.models import Poll, PollOption, PollView, Vote

pytestmark = pytest.mark.django_db


class TestPollModel:
    def test_create_poll(self, user):
        poll = Poll.objects.create(
            author=user,
            question="Test question?",
            poll_type=PollType.SINGLE_CHOICE.value,
            ends_at=timezone.now() + timedelta(hours=24),
        )
        assert poll.author == user
        assert poll.question == "Test question?"
        assert poll.poll_type == PollType.SINGLE_CHOICE.value
        assert poll.status == PollStatus.ACTIVE.value
        assert poll.total_votes == 0
        assert poll.total_views == 0
        assert poll.options_count == 0
        assert poll.show_results is True
        assert poll.show_voters is False
        assert poll.show_vote_counts is True
        assert poll.show_view_counts is True
        assert poll.media is None
        assert poll.is_deleted is False

    def test_is_active_property(self, user):
        active = Poll.objects.create(author=user, question="Active?")
        assert active.is_active is True
        assert active.is_expired is False

        expired = Poll.objects.create(
            author=user, question="Expired?",
            ends_at=timezone.now() - timedelta(hours=1),
        )
        assert expired.is_active is False
        assert expired.is_expired is True

        closed = Poll.objects.create(
            author=user, question="Closed?",
            status=PollStatus.CLOSED.value,
        )
        assert closed.is_active is False
        assert closed.is_expired is True

    def test_str_representation(self, user):
        poll = Poll.objects.create(author=user, question="Hello world?")
        assert "Hello world?" in str(poll)
        assert poll.status in str(poll)

    def test_soft_delete(self, user):
        poll = Poll.objects.create(author=user, question="Delete?")
        poll.delete()
        poll.refresh_from_db()
        assert poll.is_deleted is True
        assert poll.deleted_at is not None

    def test_media_nullable(self, user):
        poll = Poll.objects.create(author=user, question="No media?")
        assert poll.media is None


class TestPollOptionModel:
    def test_create_option(self, poll):
        option = PollOption.objects.create(poll=poll, text="Red", position=0)
        assert option.poll == poll
        assert option.text == "Red"
        assert option.position == 0
        assert option.vote_count == 0
        assert option.is_deleted is False

    def test_str_representation(self, poll):
        option = PollOption.objects.create(poll=poll, text="Blue")
        assert str(option) == "Blue"

    def test_ordering(self, user):
        p = Poll.objects.create(author=user, question="Order?")
        opt_a = PollOption.objects.create(poll=p, text="A", position=2)
        opt_b = PollOption.objects.create(poll=p, text="B", position=0)
        opt_c = PollOption.objects.create(poll=p, text="C", position=1)
        options = list(p.options.all())
        assert options == [opt_b, opt_c, opt_a]

    def test_soft_delete(self, poll):
        option = PollOption.objects.create(poll=poll, text="Temp")
        option.delete()
        option.refresh_from_db()
        assert option.is_deleted is True


class TestVoteModel:
    def test_create_vote(self, poll, voter):
        option = poll.options.first()
        vote = Vote.objects.create(poll=poll, option=option, voter=voter)
        assert vote.poll == poll
        assert vote.option == option
        assert vote.voter == voter
        assert vote.created_at is not None

    def test_str_representation(self, poll, voter):
        option = poll.options.first()
        vote = Vote.objects.create(poll=poll, option=option, voter=voter)
        assert str(vote.voter.username) in str(vote)
        assert str(option.text[:30]) in str(vote)

    def test_cascade_on_option_hard_delete(self, poll, voter):
        option = poll.options.first()
        opt_id = option.id
        Vote.objects.create(poll=poll, option=option, voter=voter)
        option.hard_delete()
        assert Vote.objects.filter(option_id=opt_id).count() == 0


class TestPollViewModel:
    def test_create_view(self, poll, voter):
        pv = PollView.objects.create(poll=poll, viewer=voter)
        assert pv.poll == poll
        assert pv.viewer == voter
        assert pv.ip_address is None

    def test_anonymous_view(self, poll):
        pv = PollView.objects.create(poll=poll, viewer=None, ip_address="192.168.1.1")
        assert pv.viewer is None
        assert pv.ip_address == "192.168.1.1"

    def test_str(self, poll):
        pv = PollView.objects.create(poll=poll, ip_address="10.0.0.1")
        assert "10.0.0.1" in str(pv)
