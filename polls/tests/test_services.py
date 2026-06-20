from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from polls.enums import PollStatus, PollType
from polls.models import Poll, PollOption, PollView, Vote
from polls.services.exceptions import (
    DuplicateVoteError,
    PollExpiredError,
    ValidationError,
    VoteAlreadyCastError,
)
from polls.services.poll_service import PollService

pytestmark = pytest.mark.django_db


class TestPollServiceCreate:
    def test_create_basic(self, user):
        data = {
            "question": "Best framework?",
            "options": ["Django", "FastAPI", "Flask"],
            "ends_at": timezone.now() + timedelta(days=7),
        }
        poll = PollService.create(author=user, validated_data=data)
        assert poll.question == "Best framework?"
        assert poll.poll_type == PollType.SINGLE_CHOICE.value
        assert poll.author == user
        assert poll.options.count() == 3
        assert poll.options_count == 3
        assert poll.status == PollStatus.ACTIVE.value

    def test_create_multiple_choice(self, user):
        data = {
            "question": "Pick languages?",
            "poll_type": PollType.MULTIPLE_CHOICE.value,
            "options": ["Python", "JavaScript", "Rust"],
        }
        poll = PollService.create(author=user, validated_data=data)
        assert poll.poll_type == PollType.MULTIPLE_CHOICE.value
        assert poll.options.count() == 3

    def test_create_rejects_less_than_two_options(self, user):
        data = {"question": "Q?", "options": ["Only one"]}
        with pytest.raises(ValidationError, match="at least 2 options"):
            PollService.create(author=user, validated_data=data)

    def test_create_rejects_empty_options(self, user):
        data = {"question": "Q?", "options": []}
        with pytest.raises(ValidationError, match="at least 2 options"):
            PollService.create(author=user, validated_data=data)

    def test_create_rejects_past_ends_at(self, user):
        data = {
            "question": "Q?",
            "options": ["A", "B"],
            "ends_at": timezone.now() - timedelta(hours=1),
        }
        with pytest.raises(ValidationError, match="future"):
            PollService.create(author=user, validated_data=data)

    def test_create_with_preferences(self, user):
        data = {
            "question": "Q?",
            "options": ["A", "B"],
            "show_results": False,
            "show_voters": True,
            "show_vote_counts": False,
            "show_view_counts": False,
        }
        poll = PollService.create(author=user, validated_data=data)
        assert poll.show_results is False
        assert poll.show_voters is True
        assert poll.show_vote_counts is False
        assert poll.show_view_counts is False


class TestPollServiceUpdate:
    def test_update_basic(self, poll):
        data = {"question": "Updated question?"}
        updated = PollService.update(instance=poll, validated_data=data)
        assert updated.question == "Updated question?"

    def test_update_options(self, poll):
        data = {"options": ["X", "Y", "Z"]}
        PollService.update(instance=poll, validated_data=data)
        assert poll.options.count() == 3
        texts = list(poll.options.values_list("text", flat=True))
        assert texts == ["X", "Y", "Z"]

    def test_update_rejects_closed_poll(self, closed_poll):
        data = {"question": "Nope"}
        with pytest.raises(ValidationError, match="closed"):
            PollService.update(instance=closed_poll, validated_data=data)


class TestPollServiceClose:
    def test_close_sets_status(self, poll):
        assert poll.status == PollStatus.ACTIVE.value
        PollService.close(instance=poll)
        poll.refresh_from_db()
        assert poll.status == PollStatus.CLOSED.value

    def test_close_sets_ends_at(self, poll):
        PollService.close(instance=poll)
        poll.refresh_from_db()
        assert poll.ends_at is not None


class TestPollServiceDelete:
    def test_soft_delete(self, poll):
        PollService.delete(instance=poll)
        poll.refresh_from_db()
        assert poll.is_deleted is True


class TestPollServiceCastVote:
    def test_single_choice_vote(self, poll, voter):
        option = poll.options.first()
        vote = PollService.cast_vote(poll=poll, option_id=str(option.id), voter=voter)
        assert vote.poll == poll
        assert vote.option == option
        assert vote.voter == voter
        poll.refresh_from_db()
        option.refresh_from_db()
        assert poll.total_votes == 1
        assert option.vote_count == 1

    def test_single_choice_duplicate_rejected(self, poll, voter):
        option = poll.options.first()
        PollService.cast_vote(poll=poll, option_id=str(option.id), voter=voter)
        with pytest.raises(VoteAlreadyCastError):
            PollService.cast_vote(poll=poll, option_id=str(option.id), voter=voter)

    def test_single_choice_rejects_vote_on_different_option(self, poll, voter):
        opt1 = poll.options.first()
        opt2 = poll.options.last()
        PollService.cast_vote(poll=poll, option_id=str(opt1.id), voter=voter)
        with pytest.raises(VoteAlreadyCastError):
            PollService.cast_vote(poll=poll, option_id=str(opt2.id), voter=voter)

    def test_multiple_choice_allows_multiple_votes(self, multi_choice_poll, voter):
        opts = list(multi_choice_poll.options.all())
        v1 = PollService.cast_vote(poll=multi_choice_poll, option_id=str(opts[0].id), voter=voter)
        v2 = PollService.cast_vote(poll=multi_choice_poll, option_id=str(opts[1].id), voter=voter)
        assert v1 is not None
        assert v2 is not None
        multi_choice_poll.refresh_from_db()
        assert multi_choice_poll.total_votes == 2

    def test_multiple_choice_duplicate_option_rejected(self, multi_choice_poll, voter):
        option = multi_choice_poll.options.first()
        PollService.cast_vote(poll=multi_choice_poll, option_id=str(option.id), voter=voter)
        with pytest.raises(DuplicateVoteError):
            PollService.cast_vote(poll=multi_choice_poll, option_id=str(option.id), voter=voter)

    def test_expired_poll_rejected(self, expired_poll, voter):
        option = expired_poll.options.first()
        with pytest.raises(PollExpiredError):
            PollService.cast_vote(poll=expired_poll, option_id=str(option.id), voter=voter)

    def test_closed_poll_rejected(self, closed_poll, voter):
        option = closed_poll.options.first()
        with pytest.raises(PollExpiredError):
            PollService.cast_vote(poll=closed_poll, option_id=str(option.id), voter=voter)

    def test_invalid_option_rejected(self, poll, voter):
        with pytest.raises(ValidationError, match="not found"):
            PollService.cast_vote(poll=poll, option_id="00000000-0000-0000-0000-000000000000", voter=voter)

    def test_same_user_cannot_vote_twice_on_same_option(self, poll, voter):
        option = poll.options.first()
        PollService.cast_vote(poll=poll, option_id=str(option.id), voter=voter)
        with pytest.raises(VoteAlreadyCastError):
            PollService.cast_vote(poll=poll, option_id=str(option.id), voter=voter)


class TestPollServiceRemoveVote:
    def test_remove_single_choice_vote(self, poll, voter):
        option = poll.options.first()
        PollService.cast_vote(poll=poll, option_id=str(option.id), voter=voter)
        Vote.objects.filter(poll=poll, voter=voter).delete()
        with transaction.atomic():
            PollService.remove_vote(poll=poll, voter=voter)
        assert Vote.objects.filter(poll=poll, voter=voter).count() == 0

    def test_remove_nonexistent_vote_does_not_error(self, poll, voter):
        PollService.remove_vote(poll=poll, voter=voter)


class TestPollServiceRecordView:
    def test_authenticated_view(self, poll, voter):
        PollService.record_view(poll=poll, viewer=voter)
        poll.refresh_from_db()
        assert poll.total_views == 1
        assert PollView.objects.filter(poll=poll, viewer=voter).count() == 1

    def test_anonymous_view(self, poll):
        PollService.record_view(poll=poll, viewer=None, ip_address="10.0.0.1")
        poll.refresh_from_db()
        assert poll.total_views == 1

    def test_dedup_same_viewer(self, poll, voter):
        PollService.record_view(poll=poll, viewer=voter)
        PollService.record_view(poll=poll, viewer=voter)
        poll.refresh_from_db()
        assert poll.total_views == 1


class TestPollServiceGetOptionsData:
    def test_returns_ordered_dicts(self, poll):
        data = PollService.get_options_data(poll)
        assert len(data) == 3
        assert data[0]["text"] == "Red"
        assert data[1]["text"] == "Blue"
        assert data[2]["text"] == "Green"
        for entry in data:
            assert "id" in entry
            assert "text" in entry
            assert "vote_count" in entry
            assert "position" in entry
