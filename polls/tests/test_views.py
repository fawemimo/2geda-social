from __future__ import annotations

from datetime import timedelta
from unittest.mock import ANY, patch

import pytest
from django.utils import timezone
from rest_framework import status

from polls.enums import PollStatus
from polls.models import Poll, PollOption, Vote
from polls.services.poll_service import PollService

pytestmark = pytest.mark.django_db

API_ROOT = "/api/v2/polls/"


class TestPollListView:
    url = API_ROOT

    def test_list_authenticated(self, auth_client, poll):
        resp = auth_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["status"] is True
        assert len(resp.data["data"]) == 1

    def test_list_unauthenticated_shows_active_only(self, api_client, poll, closed_poll):
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        poll_ids = [p["id"] for p in resp.data["data"]]
        assert str(poll.id) in poll_ids
        assert str(closed_poll.id) not in poll_ids


class TestPollCreateView:
    url = API_ROOT

    def test_create_success(self, auth_client):
        data = {
            "question": "Best language?",
            "options": ["Python", "JavaScript", "Rust"],
            "ends_at": (timezone.now() + timedelta(days=7)).isoformat(),
        }
        resp = auth_client.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["status"] is True
        assert resp.data["data"]["question"] == "Best language?"
        assert Poll.objects.count() == 1

    def test_create_unauthenticated(self, api_client):
        data = {"question": "Q?", "options": ["A", "B"]}
        resp = api_client.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_less_than_two_options(self, auth_client):
        data = {"question": "Q?", "options": ["Only one"]}
        resp = auth_client.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_empty_options(self, auth_client):
        data = {"question": "Q?", "options": []}
        resp = auth_client.post(self.url, data, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestPollRetrieveView:
    def test_retrieve_increments_view_count(self, auth_client, poll):
        resp = auth_client.get(f"{API_ROOT}{poll.id}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["id"] == str(poll.id)
        poll.refresh_from_db()
        assert poll.total_views == 1

    def test_retrieve_not_found(self, auth_client):
        resp = auth_client.get(f"{API_ROOT}00000000-0000-0000-0000-000000000000/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestPollUpdateView:
    def test_update_own_poll(self, auth_client, poll):
        resp = auth_client.put(
            f"{API_ROOT}{poll.id}/",
            {"question": "Updated?"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        poll.refresh_from_db()
        assert poll.question == "Updated?"

    def test_update_other_poll(self, other_auth_client, poll):
        resp = other_auth_client.put(
            f"{API_ROOT}{poll.id}/",
            {"question": "Hacked?"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_update_closed_poll_fails(self, auth_client, closed_poll):
        resp = auth_client.put(
            f"{API_ROOT}{closed_poll.id}/",
            {"question": "Nope"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_partial_update(self, auth_client, poll):
        resp = auth_client.patch(
            f"{API_ROOT}{poll.id}/",
            {"show_voters": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        poll.refresh_from_db()
        assert poll.show_voters is True


class TestPollDeleteView:
    def test_delete_own_poll(self, auth_client, poll):
        resp = auth_client.delete(f"{API_ROOT}{poll.id}/")
        assert resp.status_code == status.HTTP_200_OK
        poll.refresh_from_db()
        assert poll.is_deleted is True

    def test_delete_other_poll(self, other_auth_client, poll):
        resp = other_auth_client.delete(f"{API_ROOT}{poll.id}/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_unauthenticated(self, api_client, poll):
        resp = api_client.delete(f"{API_ROOT}{poll.id}/")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestPollVoteView:
    url_tpl = API_ROOT + "{poll_id}/vote/"

    def test_vote_success(self, voter_auth_client, poll):
        option = poll.options.first()
        resp = voter_auth_client.post(
            self.url_tpl.format(poll_id=poll.id),
            {"option_id": str(option.id)},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["status"] is True
        assert Vote.objects.filter(poll=poll, voter__email="voter@test.com").count() == 1

    @patch("polls.views.broadcast_poll_event")
    def test_vote_broadcasts_event(self, mock_broadcast, voter_auth_client, poll):
        option = poll.options.first()
        voter_auth_client.post(
            self.url_tpl.format(poll_id=poll.id),
            {"option_id": str(option.id)},
            format="json",
        )
        mock_broadcast.assert_called_once_with(
            str(poll.id),
            {
                "event": "vote.update",
                "poll_id": str(poll.id),
                "option_id": str(option.id),
                "voter_id": ANY,
                "options": ANY,
                "total_votes": ANY,
            },
        )

    def test_vote_own_poll_forbidden(self, auth_client, poll):
        option = poll.options.first()
        resp = auth_client.post(
            self.url_tpl.format(poll_id=poll.id),
            {"option_id": str(option.id)},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_vote_expired_poll(self, voter_auth_client, expired_poll):
        option = expired_poll.options.first()
        resp = voter_auth_client.post(
            self.url_tpl.format(poll_id=expired_poll.id),
            {"option_id": str(option.id)},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_vote_invalid_option(self, voter_auth_client, poll):
        resp = voter_auth_client.post(
            self.url_tpl.format(poll_id=poll.id),
            {"option_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_vote_duplicate_single_choice(self, voter_auth_client, poll):
        option = poll.options.first()
        voter_auth_client.post(
            self.url_tpl.format(poll_id=poll.id),
            {"option_id": str(option.id)},
            format="json",
        )
        resp = voter_auth_client.post(
            self.url_tpl.format(poll_id=poll.id),
            {"option_id": str(option.id)},
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_vote_unauthenticated(self, api_client, poll):
        option = poll.options.first()
        resp = api_client.post(
            self.url_tpl.format(poll_id=poll.id),
            {"option_id": str(option.id)},
            format="json",
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestPollUnvoteView:
    url_tpl = API_ROOT + "{poll_id}/unvote/"

    def test_unvote_single_choice(self, voter_auth_client, poll, voter):
        option = poll.options.first()
        PollService.cast_vote(poll=poll, option_id=str(option.id), voter=voter)
        resp = voter_auth_client.post(self.url_tpl.format(poll_id=poll.id))
        assert resp.status_code == status.HTTP_200_OK
        assert Vote.objects.filter(poll=poll, voter=voter).count() == 0

    @patch("polls.views.broadcast_poll_event")
    def test_unvote_broadcasts_event(self, mock_broadcast, voter_auth_client, poll, voter):
        option = poll.options.first()
        PollService.cast_vote(poll=poll, option_id=str(option.id), voter=voter)
        voter_auth_client.post(self.url_tpl.format(poll_id=poll.id))
        mock_broadcast.assert_called_once()


class TestPollCloseView:
    url_tpl = API_ROOT + "{poll_id}/close/"

    def test_close_own_poll(self, auth_client, poll):
        resp = auth_client.post(self.url_tpl.format(poll_id=poll.id))
        assert resp.status_code == status.HTTP_200_OK
        poll.refresh_from_db()
        assert poll.status == PollStatus.CLOSED.value

    def test_close_other_poll(self, other_auth_client, poll):
        resp = other_auth_client.post(self.url_tpl.format(poll_id=poll.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_close_already_expired(self, auth_client, expired_poll):
        resp = auth_client.post(self.url_tpl.format(poll_id=expired_poll.id))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @patch("polls.views.broadcast_poll_event")
    def test_close_broadcasts_event(self, mock_broadcast, auth_client, poll):
        auth_client.post(self.url_tpl.format(poll_id=poll.id))
        mock_broadcast.assert_called_once_with(
            str(poll.id),
            {"event": "poll.closed", "poll_id": str(poll.id)},
        )


class TestPollResultsView:
    url_tpl = API_ROOT + "{poll_id}/results/"

    def test_results_public(self, voter_auth_client, poll):
        resp = voter_auth_client.get(self.url_tpl.format(poll_id=poll.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"]["question"] == poll.question
        assert len(resp.data["data"]["options"]) == 3

    def test_results_private_for_non_author(self, voter_auth_client, poll):
        poll.show_results = False
        poll.save()
        resp = voter_auth_client.get(self.url_tpl.format(poll_id=poll.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_results_private_author_can_see(self, auth_client, poll):
        poll.show_results = False
        poll.save()
        resp = auth_client.get(self.url_tpl.format(poll_id=poll.id))
        assert resp.status_code == status.HTTP_200_OK
