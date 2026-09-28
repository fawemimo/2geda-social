from __future__ import annotations

from datetime import timedelta

import pytest
from accounts.models import Follow, User
from django.db import connection
from django.utils import timezone
from medias.models import Collection, Media
from rest_framework import status
from search.enums import SearchType
from social.models import Comment, Post
from utils.enum import FollowStatus

pytestmark = pytest.mark.django_db

API_ROOT = "/api/v2/search/"


def facet_counts(response) -> dict[str, int]:
    return {entry["type"]: entry["count"] for entry in response.data["types"]}


def result_types(response) -> list[str]:
    return [entry["type"] for entry in response.data["data"]]


def result_items(response, search_type: str) -> list[dict]:
    return [entry["item"] for entry in response.data["data"] if entry["type"] == search_type]


class TestSearchValidation:
    url = f"{API_ROOT}"

    def test_missing_query_rejected(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["status"] is False
        assert resp.data["code"] == "query_too_short"

    def test_single_character_query_rejected(self, api_client):
        resp = api_client.get(self.url, {"q": "d"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query_too_short"

    def test_whitespace_only_query_rejected(self, api_client):
        resp = api_client.get(self.url, {"q": "   "})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_type_rejected(self, api_client):
        resp = api_client.get(self.url, {"q": "dancing", "types": "users,unicorns"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid_search_type"
        assert "unicorns" in resp.data["message"]

    def test_invalid_media_type_rejected(self, api_client):
        resp = api_client.get(
            self.url, {"q": "dancing", "types": "media", "media_type": "hologram"}
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid_media_type"

    def test_media_type_without_media_type_filter_rejected(self, api_client):
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts", "media_type": "image"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid_filter_combination"

    def test_invalid_sort_rejected(self, api_client):
        resp = api_client.get(self.url, {"q": "dancing", "sort": "sideways"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid_sort"

    def test_invalid_date_rejected(self, api_client):
        resp = api_client.get(self.url, {"q": "dancing", "date_from": "last-tuesday"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid_date"

    def test_invalid_page_rejected(self, api_client):
        resp = api_client.get(self.url, {"q": "dancing", "page": "0"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid_pagination"

    def test_search_is_publicly_readable(self, api_client, matching_post):
        resp = api_client.get(self.url, {"q": "dancing"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["status"] is True


class TestSearchAcrossTypes:
    url = f"{API_ROOT}"

    def test_finds_every_matching_type(
        self,
        api_client,
        user,
        matching_post,
        matching_comment,
        matching_media,
        matching_collection,
    ):
        resp = api_client.get(self.url, {"q": "dancing"})

        assert resp.status_code == status.HTTP_200_OK
        counts = facet_counts(resp)
        assert counts["users"] == 1        # matched on profile.display_name
        assert counts["posts"] == 1
        assert counts["comments"] == 1
        assert counts["media"] == 1
        assert counts["collections"] == 1
        assert resp.data["totalItem"] == 5

    def test_response_envelope_shape(
        self, api_client, matching_post, matching_media
    ):
        resp = api_client.get(self.url, {"q": "dancing"})

        assert resp.data["status"] is True
        assert resp.data["query"] == "dancing"
        assert resp.data["tokens"] == ["dancing"]
        assert resp.data["currentPage"] == 1
        assert resp.data["nextPage"] is None
        assert resp.data["previousPage"] is None
        assert resp.data["totalPerPage"] == 20
        assert "appliedFilters" in resp.data
        for entry in resp.data["data"]:
            assert set(entry) == {"type", "score", "item"}

    def test_user_hit_carries_profile_fields(self, api_client, db, other_user):
        """A match that lives only on the profile must surface and be readable."""
        other_user.profile.bio = "Dancing instructor"
        other_user.profile.save()
        resp = api_client.get(self.url, {"q": "instructor"})
        items = result_items(resp, "users")
        assert len(items) == 1
        assert items[0]["username"] == "choreographer"
        assert items[0]["bio"] == "Dancing instructor"

    def test_blank_profile_fields_do_not_hide_a_user(self, api_client, db):
        """The profile join must not exclude users whose profile fields are empty.

        social/signals.py gives every user a profile row, so the risky case is
        a profile that exists but has nothing in it -- filtering on those
        columns must not silently drop the user.
        """
        bare = User.objects.create_user(
            email="bare@test.com", username="bare", password="pass123", is_active=True
        )
        assert bare.profile is not None

        resp = api_client.get(self.url, {"q": "bare"})
        usernames = [item["username"] for item in result_items(resp, "users")]
        assert bare.username in usernames

    def test_media_hit_includes_caption_and_cdn_url(self, api_client, matching_media):
        resp = api_client.get(self.url, {"q": "recap"})
        items = result_items(resp, "media")
        assert len(items) == 1
        assert items[0]["caption"] == "Dancing class recap"
        assert items[0]["cdn_url"] == "https://cdn.test.com/dancing.mp4"
        assert "storage_key" not in items[0]

    def test_collection_hit_includes_description(self, api_client, matching_collection):
        resp = api_client.get(self.url, {"q": "footage"})
        items = result_items(resp, "collections")
        assert len(items) == 1
        assert items[0]["name"] == "Dancing videos"
        assert items[0]["description"] == "Footage from my dancing classes"


class TestSearchTypeFilter:
    url = f"{API_ROOT}"

    def test_narrowing_to_one_type(
        self, api_client, matching_post, matching_comment, matching_media
    ):
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert result_types(resp) == ["posts"]
        assert [f["type"] for f in resp.data["types"]] == ["posts"]

    def test_multiple_types_narrowed(self, api_client, matching_post, matching_media):
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts,media"})
        assert set(result_types(resp)) == {"posts", "media"}
        assert resp.data["appliedFilters"]["types"] == ["posts", "media"]

    def test_omitting_types_searches_everything(self, api_client, matching_post):
        resp = api_client.get(self.url, {"q": "dancing"})
        assert set(facet_counts(resp)) == set(SearchType.values())

    def test_types_are_case_insensitive_and_deduped(self, api_client, matching_post):
        resp = api_client.get(self.url, {"q": "dancing", "types": " POSTS , posts "})
        assert resp.data["appliedFilters"]["types"] == ["posts"]


class TestSearchFilters:
    url = f"{API_ROOT}"

    def test_media_type_filter(self, api_client, db, other_user, matching_media):
        Media.objects.create(
            owner=other_user,
            media_type="image",
            visibility="public",
            storage_key="search/dancing.png",
            cdn_url="https://cdn.test.com/dancing.png",
            original_filename="dancing.png",
            caption="Dancing pose",
        )
        resp = api_client.get(
            self.url, {"q": "dancing", "types": "media", "media_type": "video"}
        )
        items = result_items(resp, "media")
        assert len(items) == 1
        assert items[0]["media_type"] == "video"

    def test_date_from_excludes_older_items(self, api_client, db, other_user):
        old = Post.objects.create(
            author=other_user, body="dancing yesterday", visibility="public"
        )
        Post.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        Post.objects.create(author=other_user, body="dancing today", visibility="public")

        cutoff = timezone.now() - timedelta(days=1)
        resp = api_client.get(
            self.url, {"q": "dancing", "types": "posts", "date_from": cutoff.isoformat()}
        )
        bodies = [item["body"] for item in result_items(resp, "posts")]
        assert bodies == ["dancing today"]

    def test_date_to_excludes_newer_items(self, api_client, db, other_user):
        Post.objects.create(author=other_user, body="dancing today", visibility="public")
        old = Post.objects.create(
            author=other_user, body="dancing long ago", visibility="public"
        )
        Post.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )

        cutoff = timezone.now() - timedelta(days=1)
        resp = api_client.get(
            self.url, {"q": "dancing", "types": "posts", "date_to": cutoff.isoformat()}
        )
        bodies = [item["body"] for item in result_items(resp, "posts")]
        assert bodies == ["dancing long ago"]

    def test_date_only_string_accepted(self, api_client, matching_post):
        resp = api_client.get(
            self.url, {"q": "dancing", "date_from": "2020-01-01", "date_to": "2999-01-01"}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["totalItem"] == 1

    def test_sort_recent_overrides_relevance(self, api_client, db, other_user):
        exact = Post.objects.create(
            author=other_user, body="dancing", visibility="public"
        )
        loose = Post.objects.create(
            author=other_user, body="I was dancing earlier", visibility="public"
        )
        Post.objects.filter(pk=loose.pk).update(created_at=timezone.now())
        Post.objects.filter(pk=exact.pk).update(
            created_at=timezone.now() - timedelta(days=5)
        )

        by_relevance = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert result_items(by_relevance, "posts")[0]["body"] == "dancing"

        by_recency = api_client.get(
            self.url, {"q": "dancing", "types": "posts", "sort": "recent"}
        )
        assert result_items(by_recency, "posts")[0]["body"] == "I was dancing earlier"


class TestSearchRanking:
    url = f"{API_ROOT}"

    def test_exact_match_outranks_substring(self, api_client, db, other_user):
        Post.objects.create(author=other_user, body="dancing", visibility="public")
        Post.objects.create(
            author=other_user, body="dancing is my hobby", visibility="public"
        )
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        items = result_items(resp, "posts")
        assert items[0]["body"] == "dancing"
        assert resp.data["data"][0]["score"] > 0

    def test_prefix_outranks_mid_word(self, api_client, db, other_user):
        Post.objects.create(
            author=other_user, body="dancing shoes", visibility="public"
        )
        Post.objects.create(
            author=other_user, body="the art of dancing", visibility="public"
        )
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert result_items(resp, "posts")[0]["body"] == "dancing shoes"

    def test_matching_case_insensitively(self, api_client, matching_post):
        resp = api_client.get(self.url, {"q": "DaNcInG"})
        assert resp.data["totalItem"] >= 1

    def test_all_tokens_must_match(self, api_client, db, other_user):
        Post.objects.create(
            author=other_user, body="dancing on tuesday", visibility="public"
        )
        Post.objects.create(author=other_user, body="dancing every day", visibility="public")

        both = api_client.get(self.url, {"q": "dancing tuesday", "types": "posts"})
        assert both.data["totalItem"] == 1
        assert result_items(both, "posts")[0]["body"] == "dancing on tuesday"

    def test_token_order_does_not_matter(self, api_client, matching_post):
        forward = api_client.get(self.url, {"q": "dancing routine"})
        reverse = api_client.get(self.url, {"q": "routine dancing"})
        assert forward.data["totalItem"] == reverse.data["totalItem"] == 1

    def test_token_matched_across_different_fields(self, api_client, matching_post):
        """'choreographer' is the author, 'routine' is the body -- both count."""
        resp = api_client.get(
            self.url, {"q": "choreographer routine", "types": "posts"}
        )
        assert resp.data["totalItem"] == 1

    def test_row_matching_every_token_beats_partial_tightness(
        self, api_client, db, other_user
    ):
        Post.objects.create(
            author=other_user, body="dancing routine", visibility="public"
        )
        Post.objects.create(
            author=other_user, body="dancing with the whole routine show", visibility="public"
        )
        resp = api_client.get(self.url, {"q": "dancing routine", "types": "posts"})
        assert result_items(resp, "posts")[0]["body"] == "dancing routine"

    def test_intact_phrase_outranks_scattered_tokens(
        self, api_client, db, other_user
    ):
        """Phrase contiguity must dominate per-token tightness.

        Both rows contain both tokens and both have a word-initial token, so
        only the phrase tier separates them.
        """
        intact = Post.objects.create(
            author=other_user, body="dancing routine", visibility="public"
        )
        scattered = Post.objects.create(
            author=other_user,
            body="routine of the dancing kind",
            visibility="public",
        )
        # Newer row, so only rank can put `intact` first.
        Post.objects.filter(pk=scattered.pk).update(
            created_at=timezone.now() + timedelta(minutes=5)
        )
        resp = api_client.get(self.url, {"q": "dancing routine", "types": "posts"})
        bodies = [item["body"] for item in result_items(resp, "posts")]
        assert bodies[0] == intact.body
        scores = [entry["score"] for entry in resp.data["data"]]
        assert scores == sorted(scores, reverse=True), "scores must be descending"


class TestSearchResultBalancing:
    url = f"{API_ROOT}"

    def test_page_is_not_dominated_by_one_type(self, api_client, db, other_user):
        for index in range(10):
            Post.objects.create(
                author=other_user, body=f"dancing post {index}", visibility="public"
            )
        other_user.profile.display_name = "dancing persona"
        other_user.profile.save()

        resp = api_client.get(self.url, {"q": "dancing", "page_size": 4})
        types = result_types(resp)
        assert "posts" in types and "users" in types
        # Round-robin means the single user hit is not pushed off page one.
        assert len(types) == 4
        assert types.count("users") == 1 and types.count("posts") == 3

    def test_requested_type_order_decides_who_leads(self, api_client, db, other_user):
        for index in range(3):
            Post.objects.create(
                author=other_user, body=f"dancing post {index}", visibility="public"
            )
        other_user.profile.display_name = "dancing persona"
        other_user.profile.save()

        posts_first = api_client.get(
            self.url, {"q": "dancing", "types": "posts,users"}
        )
        users_first = api_client.get(
            self.url, {"q": "dancing", "types": "users,posts"}
        )
        assert result_types(posts_first)[0] == "posts"
        assert result_types(users_first)[0] == "users"

    def test_total_item_counts_every_match_not_just_the_window(
        self, api_client, db, other_user
    ):
        for index in range(7):
            Post.objects.create(
                author=other_user, body=f"dancing {index}", visibility="public"
            )
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts", "page_size": 2})
        assert resp.data["totalItem"] == 7
        assert resp.data["totalPages"] == 4
        assert resp.data["nextPage"] == 2

    def test_pagination_walks_stable_pages(self, api_client, db, other_user):
        for index in range(5):
            Post.objects.create(
                author=other_user, body=f"dancing {index}", visibility="public"
            )
        first = api_client.get(
            self.url, {"q": "dancing", "types": "posts", "page_size": 2, "page": 1}
        )
        second = api_client.get(
            self.url, {"q": "dancing", "types": "posts", "page_size": 2, "page": 2}
        )
        assert len(first.data["data"]) == 2
        assert len(second.data["data"]) == 2
        assert second.data["previousPage"] == 1
        first_ids = {item["id"] for item in result_items(first, "posts")}
        second_ids = {item["id"] for item in result_items(second, "posts")}
        assert not (first_ids & second_ids)

    def test_page_size_is_capped(self, api_client, matching_post):
        resp = api_client.get(self.url, {"q": "dancing", "page_size": 100000})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["totalPerPage"] == 200

    def test_page_beyond_end_is_empty_but_valid(self, api_client, matching_post):
        resp = api_client.get(self.url, {"q": "dancing", "page": 99})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["data"] == []
        assert resp.data["totalItem"] == 1

    def test_facet_counts_stay_true_beyond_the_scan_window(self, api_client, db, other_user):
        """Counts are real COUNTs, so they must not be capped by the window."""
        for index in range(12):
            Post.objects.create(
                author=other_user, body=f"dancing {index}", visibility="public"
            )
        resp = api_client.get(
            self.url, {"q": "dancing", "types": "posts", "page_size": 2, "page": 3}
        )
        assert resp.data["totalItem"] == 12
        assert facet_counts(resp)["posts"] == 12
        assert len(resp.data["data"]) == 2


class TestSearchVisibilityScoping:
    url = f"{API_ROOT}"

    def test_soft_deleted_rows_are_hidden(self, api_client, db, other_user, matching_post):
        matching_post.delete()  # SoftDeleteMixin.delete() flags, never removes
        Comment.objects.create(post=matching_post, author=other_user, body="dancing here")

        resp = api_client.get(self.url, {"q": "dancing"})
        assert resp.data["totalItem"] == 0

    def test_inactive_users_are_hidden(self, api_client, db):
        ghost = User.objects.create_user(
            email="ghosted@test.com", username="ghosted", password="pass123",
            is_active=False,
        )
        ghost.profile.bio = "dancing in spirit"
        ghost.profile.save()
        resp = api_client.get(self.url, {"q": "dancing", "types": "users"})
        assert resp.data["totalItem"] == 0

    def test_private_posts_hidden_from_others(self, api_client, db, other_user, user):
        Post.objects.create(
            author=other_user, body="dancing diary", visibility="private"
        )
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert resp.data["totalItem"] == 0

    def test_private_posts_visible_to_their_author(self, auth_client, db, user):
        Post.objects.create(
            author=user, body="dancing diary", visibility="private"
        )
        resp = auth_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert resp.data["totalItem"] == 1

    def test_followers_only_post_hidden_from_stranger(self, api_client, db, other_user):
        Post.objects.create(
            author=other_user, body="dancing rehearsal", visibility="followers"
        )
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert resp.data["totalItem"] == 0

    def test_followers_only_post_visible_to_accepted_follower(
        self, api_client, db, other_user, user
    ):
        Post.objects.create(
            author=other_user, body="dancing rehearsal", visibility="followers"
        )
        api_client.force_authenticate(user=user)

        before = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert before.data["totalItem"] == 0

        Follow.objects.create(
            follower=user, following=other_user, status=FollowStatus.ACCEPTED.value
        )
        after = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert after.data["totalItem"] == 1

    def test_pending_follow_does_not_grant_access(self, api_client, db, other_user, user):
        Post.objects.create(
            author=other_user, body="dancing rehearsal", visibility="followers"
        )
        Follow.objects.create(
            follower=user, following=other_user, status=FollowStatus.PENDING.value
        )
        api_client.force_authenticate(user=user)
        resp = api_client.get(self.url, {"q": "dancing", "types": "posts"})
        assert resp.data["totalItem"] == 0

    def test_comments_require_a_public_parent_post(self, api_client, db, other_user, user):
        private_post = Post.objects.create(
            author=user, body="private", visibility="private"
        )
        Comment.objects.create(
            post=private_post, author=other_user, body="dancing whisper"
        )
        resp = api_client.get(self.url, {"q": "whisper", "types": "comments"})
        assert resp.data["totalItem"] == 0

    def test_private_media_hidden_from_others(self, api_client, db, other_user):
        Media.objects.create(
            owner=other_user,
            media_type="image",
            visibility="private",
            storage_key="search/private.png",
            caption="dancing privately",
        )
        resp = api_client.get(self.url, {"q": "dancing", "types": "media"})
        assert resp.data["totalItem"] == 0

    def test_private_collection_hidden_from_others(self, api_client, db, other_user):
        Collection.objects.create(
            owner=other_user,
            name="secret dancing",
            is_public=False,
        )
        resp = api_client.get(self.url, {"q": "secret", "types": "collections"})
        assert resp.data["totalItem"] == 0


class TestSearchTypesEndpoint:
    url = f"{API_ROOT}types/"

    def test_lists_all_types(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == status.HTTP_200_OK
        values = [entry["value"] for entry in resp.data["data"]]
        assert values == SearchType.values()
        assert all("label" in entry for entry in resp.data["data"])


class TestSearchEngine:
    """The response says which implementation served the request.

    Without this, a PostgreSQL run whose triggers were missing would quietly
    fall back to substring matching and still pass every ordering test, so the
    full-text path would ship unexercised.
    """

    url = f"{API_ROOT}"

    def test_engine_reported_matches_backend(self, api_client, matching_post):
        resp = api_client.get(self.url, {"q": "dancing"})
        expected = (
            "postgres_fulltext" if connection.vendor == "postgresql" else "portable_substring"
        )
        assert resp.data["engine"] == expected

    def test_stopword_only_query_falls_back(self, api_client, db, other_user):
        """'the' stems away to nothing, so the vector cannot serve it.

        An empty tsquery matches zero rows, so the service has to notice and
        hand the query to the substring matcher instead.
        """
        Post.objects.create(author=other_user, body="the latest", visibility="public")
        resp = api_client.get(self.url, {"q": "the", "types": "posts"})
        assert resp.data["engine"] == "portable_substring"
        assert resp.data["totalItem"] == 1

    @pytest.mark.skipif(
        connection.vendor != "postgresql", reason="full-text stemming is PostgreSQL only"
    )
    def test_stemming_matches_across_verb_forms(self, api_client, db, other_user):
        """'danced' and 'dancing' both stem to 'danc'.

        The substring matcher cannot do this, so it is proof the vector is
        really being queried.
        """
        Post.objects.create(author=other_user, body="dancing", visibility="public")
        resp = api_client.get(self.url, {"q": "danced", "types": "posts"})
        assert resp.data["engine"] == "postgres_fulltext"
        assert resp.data["totalItem"] == 1

    @pytest.mark.skipif(
        connection.vendor != "postgresql", reason="author handles need the trigger"
    )
    def test_author_handle_is_searchable_from_their_posts(
        self, api_client, db, other_user
    ):
        """One token naming the author, one naming the content.

        This only works because the trigger denormalises the handle into the
        post's vector.
        """
        other_user.username = "choreographer"
        other_user.save()
        Post.objects.create(author=other_user, body="a tight five", visibility="public")
        resp = api_client.get(self.url, {"q": "choreographer five", "types": "posts"})
        assert resp.data["totalItem"] == 1
