"""Central social location snapshot: capture, cache reuse, geocoding."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from social.models import Comment, Post, Reshare, SocialLocation
from social.services import (
    CommentService,
    PostService,
    ReshareService,
    SocialLocationService,
)
from social.tasks import resolve_social_location
from utils.enum import LocationStatus

User = get_user_model()

LAGOS = {"latitude": Decimal("6.453056"), "longitude": Decimal("3.395833")}
GOOGLE_RESULT = {
    "formatted_address": "Victoria Island, Lagos, Nigeria",
    "city": "Lagos",
    "state": "Lagos",
    "country": "Nigeria",
}
GEOCODER = "clients.google.location_address.GoogleLocation.get_address"


@pytest.fixture
def author(db):
    return User.objects.create(username="poster", email="poster@example.com")


@pytest.fixture
def other(db):
    return User.objects.create(username="other", email="other@example.com")


@pytest.fixture(autouse=True)
def _clear_geo_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestCapture:

    def test_returns_none_without_coordinates(self):
        assert SocialLocationService.capture(latitude=None, longitude=None) is None

    def test_creates_a_pending_snapshot(self):
        with patch(GEOCODER, return_value=None):
            loc = SocialLocationService.capture(**LAGOS, label="Eko Hotel")
        assert loc.label == "Eko Hotel"
        assert loc.cell_key == "6.4531,3.3958"

    def test_rejects_out_of_range_coordinates(self):
        assert SocialLocationService.capture(latitude=95, longitude=0) is None
        assert SocialLocationService.capture(latitude=0, longitude=200) is None

    def test_rejects_unparseable_coordinates(self):
        assert SocialLocationService.capture(latitude="north", longitude="west") is None

    def test_nearby_coordinates_share_a_cell(self):
        a = SocialLocation.build_cell_key(Decimal("6.4530561"), Decimal("3.3958331"))
        b = SocialLocation.build_cell_key(Decimal("6.4530612"), Decimal("3.3958402"))
        assert a == b


@pytest.mark.django_db
class TestGeocodingIsCached:

    def test_first_capture_calls_google_once(self):
        with patch(GEOCODER, return_value=GOOGLE_RESULT) as geocode:
            loc = SocialLocationService.capture(**LAGOS)
            resolve_social_location(str(loc.id))
        assert geocode.call_count == 1
        loc.refresh_from_db()
        assert loc.city == "Lagos"
        assert loc.status == LocationStatus.RESOLVED.value

    def test_same_coordinates_never_call_google_again(self):
        """The headline requirement: unchanged coordinates hit Redis, not Google."""
        with patch(GEOCODER, return_value=GOOGLE_RESULT) as geocode:
            first = SocialLocationService.capture(**LAGOS)
            resolve_social_location(str(first.id))
            assert geocode.call_count == 1

            for _ in range(5):
                again = SocialLocationService.capture(**LAGOS)
                resolve_social_location(str(again.id))

            assert geocode.call_count == 1, "cache should have served every repeat"

        assert again.is_resolved
        assert again.formatted_address == GOOGLE_RESULT["formatted_address"]

    def test_capture_resolves_inline_when_the_cell_is_cached(self):
        with patch(GEOCODER, return_value=GOOGLE_RESULT):
            first = SocialLocationService.capture(**LAGOS)
            resolve_social_location(str(first.id))

        with patch(GEOCODER) as geocode:
            second = SocialLocationService.capture(**LAGOS)
        # Resolved before the task even runs.
        assert second.is_resolved
        assert geocode.call_count == 0

    def test_different_coordinates_do_call_google(self):
        with patch(GEOCODER, return_value=GOOGLE_RESULT) as geocode:
            a = SocialLocationService.capture(**LAGOS)
            resolve_social_location(str(a.id))
            b = SocialLocationService.capture(
                latitude=Decimal("9.057850"), longitude=Decimal("7.495080")
            )
            resolve_social_location(str(b.id))
        assert geocode.call_count == 2

    def test_falls_back_to_a_sibling_row_when_redis_is_cold(self):
        with patch(GEOCODER, return_value=GOOGLE_RESULT) as geocode:
            first = SocialLocationService.capture(**LAGOS)
            resolve_social_location(str(first.id))
            cache.clear()  # Redis evicted the entry
            second = SocialLocationService.capture(**LAGOS)
            resolve_social_location(str(second.id))
        assert geocode.call_count == 1
        second.refresh_from_db()
        assert second.city == "Lagos"

    def test_no_result_marks_the_snapshot_failed(self):
        with patch(GEOCODER, return_value=None):
            loc = SocialLocationService.capture(**LAGOS)
            resolve_social_location(str(loc.id))
        loc.refresh_from_db()
        assert loc.status == LocationStatus.FAILED.value

    def test_missing_api_key_leaves_it_pending(self):
        with patch(GEOCODER, side_effect=ValueError("no key")):
            loc = SocialLocationService.capture(**LAGOS)
            result = resolve_social_location(str(loc.id))
        loc.refresh_from_db()
        assert result["reason"] == "not_configured"
        assert loc.status == LocationStatus.PENDING.value

    def test_task_is_idempotent(self):
        with patch(GEOCODER, return_value=GOOGLE_RESULT) as geocode:
            loc = SocialLocationService.capture(**LAGOS)
            resolve_social_location(str(loc.id))
            assert resolve_social_location(str(loc.id))["reason"] == "already_resolved"
        assert geocode.call_count == 1

    def test_missing_snapshot_is_handled(self):
        import uuid
        assert resolve_social_location(str(uuid.uuid4()))["resolved"] is False


@pytest.mark.django_db(transaction=True)
class TestSocialObjectsAreTagged:

    def test_post_is_tagged(self, author):
        with patch(GEOCODER, return_value=GOOGLE_RESULT):
            post = PostService.create(
                author=author,
                validated_data={"body": "hi", **LAGOS, "location_label": "Eko"},
            )
        post.refresh_from_db()
        assert post.location.city == "Lagos"
        assert post.location.label == "Eko"

    def test_comment_is_tagged(self, author):
        with patch(GEOCODER, return_value=GOOGLE_RESULT):
            post = PostService.create(author=author, validated_data={"body": "hi"})
            comment = CommentService.create(
                author=author, post_id=str(post.id),
                validated_data={"body": "nice", **LAGOS},
            )
        comment.refresh_from_db()
        assert comment.location is not None
        assert comment.location.city == "Lagos"

    def test_reshare_is_tagged(self, author, other):
        with patch(GEOCODER, return_value=GOOGLE_RESULT):
            post = PostService.create(author=author, validated_data={"body": "hi"})
            reshare = ReshareService.create(
                user=other,
                validated_data={"original_post_id": str(post.id), **LAGOS},
            )
        reshare.refresh_from_db()
        assert reshare.location is not None
        assert reshare.location.country == "Nigeria"

    def test_untagged_objects_stay_null(self, author):
        post = PostService.create(author=author, validated_data={"body": "no geo"})
        assert post.location is None
        assert SocialLocation.objects.count() == 0

    def test_a_whole_session_geocodes_once(self, author, other):
        """Post + comment + reshare from one spot = a single Google call."""
        with patch(GEOCODER, return_value=GOOGLE_RESULT) as geocode:
            post = PostService.create(
                author=author, validated_data={"body": "hi", **LAGOS}
            )
            CommentService.create(
                author=other, post_id=str(post.id),
                validated_data={"body": "nice", **LAGOS},
            )
            ReshareService.create(
                user=other,
                validated_data={"original_post_id": str(post.id), **LAGOS},
            )
        assert geocode.call_count == 1


# transaction=True so the on_commit hook that queues geocoding actually fires.
@pytest.mark.django_db(transaction=True)
class TestApiSurface:

    @staticmethod
    def _client(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_create_post_with_coordinates(self, author):
        with patch(GEOCODER, return_value=GOOGLE_RESULT):
            resp = self._client(author).post(
                "/api/v2/social/posts/",
                {"body": "hello", "latitude": "6.453056", "longitude": "3.395833",
                 "location_label": "Eko"},
                format="json",
            )
        assert resp.status_code == 201, resp.data
        post = Post.objects.get(pk=resp.data["data"]["id"])
        assert post.location.label == "Eko"
        assert post.location.city == "Lagos"

    def test_latitude_without_longitude_is_rejected(self, author):
        resp = self._client(author).post(
            "/api/v2/social/posts/",
            {"body": "hello", "latitude": "6.453056"},
            format="json",
        )
        assert resp.status_code == 400
        assert "together" in str(resp.data)

    def test_post_without_coordinates_still_works(self, author):
        resp = self._client(author).post(
            "/api/v2/social/posts/", {"body": "plain"}, format="json",
        )
        assert resp.status_code == 201, resp.data
        assert Post.objects.get(pk=resp.data["data"]["id"]).location is None
