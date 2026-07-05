from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from accounts.models import Follow, FollowStatus, UserProfile
from accounts.services.exceptions import ConflictError, NotFoundError, ValidationError
from notifications.models import Notification
from medias.models import Media
from social.models import Comment, Like, Post, PostMedia, Reshare
from social.services import FollowService
from utils.enum import MediaType

User = get_user_model()
pytestmark = pytest.mark.django_db

API_ROOT = "/api/v2/social/"


# ─────────────────────────────────────────────────────────────────────────────
#  FollowService unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFollowService:

    def test_follow_public_user_success(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )

        follow = FollowService.follow(follower, str(following.id))

        assert follow.follower == follower
        assert follow.following == following
        assert follow.status == FollowStatus.ACCEPTED.value
        assert follow.accepted_at is not None

    def test_follow_anyone_still_accepted(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=following, defaults={"is_private": True})

        follow = FollowService.follow(follower, str(following.id))

        assert follow.status == FollowStatus.ACCEPTED.value
        assert follow.accepted_at is not None

    def test_follow_yourself_raises(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        with pytest.raises(ValidationError, match="cannot follow yourself"):
            FollowService.follow(user, str(user.id))

    def test_follow_already_following_raises(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        Follow.objects.create(follower=follower, following=following, status=FollowStatus.ACCEPTED.value)

        with pytest.raises(ConflictError, match="already following"):
            FollowService.follow(follower, str(following.id))

    def test_follow_user_not_found_raises(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        with pytest.raises(NotFoundError, match="not found"):
            FollowService.follow(follower, "00000000-0000-0000-0000-000000000001")

    def test_follow_inactive_user_raises(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=False,
        )
        with pytest.raises(NotFoundError, match="not found"):
            FollowService.follow(follower, str(following.id))

    def test_unfollow_success(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        Follow.objects.create(follower=follower, following=following, status=FollowStatus.ACCEPTED.value)

        FollowService.unfollow(follower, str(following.id))

        assert not Follow.objects.filter(follower=follower, following=following).exists()

    def test_unfollow_not_following_raises(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        with pytest.raises(ValidationError, match="not following"):
            FollowService.unfollow(follower, str(following.id))

    def test_unfollow_user_not_found_raises(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        with pytest.raises(NotFoundError, match="not found"):
            FollowService.unfollow(follower, "00000000-0000-0000-0000-000000000001")


# ─────────────────────────────────────────────────────────────────────────────
#  Notification creation on follow (integration)
# ─────────────────────────────────────────────────────────────────────────────


class TestFollowNotification:

    def test_follow_creates_new_follower_notification(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )

        FollowService.follow(follower, str(following.id))

        notif = Notification.objects.filter(
            recipient=following,
            notification_type="new_follower",
        ).first()
        assert notif is not None
        assert notif.actor == follower
        assert follower.username in notif.title
        assert notif.is_read is False
        assert notif.is_sent_push is False
        assert notif.is_sent_ws is False

    def test_follow_private_still_notifies_new_follower(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=following, defaults={"is_private": True})

        FollowService.follow(follower, str(following.id))

        notif = Notification.objects.filter(
            recipient=following,
            notification_type="new_follower",
        ).first()
        assert notif is not None
        assert notif.actor == follower

    def test_unfollow_does_not_create_notification(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        Follow.objects.create(follower=follower, following=following, status=FollowStatus.ACCEPTED.value)

        before = Notification.objects.count()
        FollowService.unfollow(follower, str(following.id))
        assert Notification.objects.count() == before


# ─────────────────────────────────────────────────────────────────────────────
#  View-level tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFollowUserView:
    url_template = f"{API_ROOT}follow/{{user_id}}/"

    def test_unauthenticated(self):
        resp = APIClient().post(
            self.url_template.format(user_id="00000000-0000-0000-0000-000000000001"),
        )
        assert resp.status_code == 401

    def test_follow_success(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )

        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(self.url_template.format(user_id=following.id))

        assert resp.status_code == 201
        assert resp.data["status"] is True
        assert resp.data["data"]["follower_id"] == str(follower.id)
        assert resp.data["data"]["following_id"] == str(following.id)
        assert resp.data["data"]["status"] == FollowStatus.ACCEPTED.value

    def test_follow_yourself_returns_error(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url_template.format(user_id=user.id))

        assert resp.status_code == 400
        assert resp.data["status"] is False
        assert "cannot follow yourself" in resp.data["message"].lower()

    def test_follow_already_following_returns_error(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        Follow.objects.create(follower=follower, following=following, status=FollowStatus.ACCEPTED.value)

        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(self.url_template.format(user_id=following.id))

        assert resp.status_code == 409
        assert resp.data["status"] is False

    def test_follow_not_found_returns_404(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(
            self.url_template.format(user_id="00000000-0000-0000-0000-000000000001"),
        )

        assert resp.status_code == 404
        assert resp.data["status"] is False

    def test_follow_creates_notification(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )

        client = APIClient()
        client.force_authenticate(user=follower)
        client.post(self.url_template.format(user_id=following.id))

        assert Notification.objects.filter(
            recipient=following,
            notification_type="new_follower",
        ).exists()

    def test_follow_private_still_notifies_new_follower_view(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        UserProfile.objects.update_or_create(user=following, defaults={"is_private": True})

        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(self.url_template.format(user_id=following.id))

        assert resp.status_code == 201
        assert resp.data["data"]["status"] == FollowStatus.ACCEPTED.value
        assert Notification.objects.filter(
            recipient=following,
            notification_type="new_follower",
        ).exists()


class TestUnfollowUserView:
    url_template = f"{API_ROOT}unfollow/{{user_id}}/"

    def test_unauthenticated(self):
        resp = APIClient().post(
            self.url_template.format(user_id="00000000-0000-0000-0000-000000000001"),
        )
        assert resp.status_code == 401

    def test_unfollow_success(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        Follow.objects.create(follower=follower, following=following, status=FollowStatus.ACCEPTED.value)

        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(self.url_template.format(user_id=following.id))

        assert resp.status_code == 200
        assert resp.data["status"] is True
        assert not Follow.objects.filter(follower=follower, following=following).exists()

    def test_unfollow_not_following_returns_error(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )

        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(self.url_template.format(user_id=following.id))

        assert resp.status_code == 400
        assert resp.data["status"] is False

    def test_unfollow_not_found_returns_404(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(
            self.url_template.format(user_id="00000000-0000-0000-0000-000000000001"),
        )

        assert resp.status_code == 404
        assert resp.data["status"] is False


# ─────────────────────────────────────────────────────────────────────────────
#  Counter integrity tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFollowCounters:

    def test_follow_increments_counters(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )

        f_profile = UserProfile.objects.get(user=follower)
        g_profile = UserProfile.objects.get(user=following)
        f_before = f_profile.following_count
        g_before = g_profile.followers_count

        FollowService.follow(follower, str(following.id))

        f_profile.refresh_from_db()
        g_profile.refresh_from_db()
        assert f_profile.following_count == f_before + 1
        assert g_profile.followers_count == g_before + 1

    def test_unfollow_decrements_counters(self):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        Follow.objects.create(follower=follower, following=following, status=FollowStatus.ACCEPTED.value)

        f_profile = UserProfile.objects.get(user=follower)
        g_profile = UserProfile.objects.get(user=following)
        f_before = f_profile.following_count
        g_before = g_profile.followers_count

        FollowService.unfollow(follower, str(following.id))

        f_profile.refresh_from_db()
        g_profile.refresh_from_db()
        assert f_profile.following_count == f_before - 1
        assert g_profile.followers_count == g_before - 1


# ─────────────────────────────────────────────────────────────────────────────
#  Post CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestPostCreate:
    url = f"{API_ROOT}posts/"

    def test_unauthenticated_returns_401(self):
        resp = APIClient().post(self.url, {"body": "hello"}, format="json")
        assert resp.status_code == 401

    def test_create_post_success(self):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {"body": "Hello world"}, format="json")
        assert resp.status_code == 201
        assert resp.data["status"] is True
        assert resp.data["data"]["body"] == "Hello world"
        assert resp.data["data"]["author"]["id"] == str(user.id)

    def test_create_post_empty_body_rejected(self):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {"body": ""}, format="json")
        assert resp.status_code == 400


class TestPostList:
    url = f"{API_ROOT}posts/"

    def test_list_posts_returns_paginated(self):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        Post.objects.create(author=user, body="First")
        Post.objects.create(author=user, body="Second")

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        assert resp.status_code == 200
        assert len(resp.data["data"]) <= 20
        assert resp.data["status"] is True

    def test_list_posts_excludes_deleted(self):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        alive = Post.objects.create(author=user, body="Alive")
        dead = Post.objects.create(author=user, body="Dead")
        dead.delete()

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        ids = [p["id"] for p in resp.data["data"]]
        assert str(alive.id) in ids
        assert str(dead.id) not in ids

    def test_unauthenticated_can_list(self):
        Post.objects.create(
            author=User.objects.create_user(email="p@t.com", username="poster", password="pass", is_active=True),
            body="Public", visibility="public",
        )
        resp = APIClient().get(self.url)
        assert resp.status_code == 200

    def test_list_returns_cached_response_on_repeat_request(self):
        user = User.objects.create_user(
            email="lc@t.com", username="listcache", password="pass", is_active=True,
        )
        Post.objects.create(author=user, body="List cache test")
        client = APIClient()
        client.force_authenticate(user=user)
        resp1 = client.get(self.url)
        assert resp1.status_code == 200
        post_ids_1 = {p["id"] for p in resp1.data["data"]}
        resp2 = client.get(self.url)
        assert resp2.status_code == 200
        import sys; print(f"\nDEBUG resp2.data keys: {list(resp2.data.keys()) if hasattr(resp2.data, 'keys') else 'no keys'}; data type: {type(resp2.data.get('data', 'N/A'))}", file=sys.stderr)
        post_ids_2 = {p["id"] for p in resp2.data["data"]}
        assert post_ids_1 == post_ids_2

    def test_list_cache_invalidated_on_post_create(self):
        user = User.objects.create_user(
            email="lc2@t.com", username="listcache2", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        count_before = len(resp.data["data"])
        client.post(self.url, {"body": "Brand new"}, format="json")
        resp = client.get(self.url)
        assert len(resp.data["data"]) == count_before + 1

    def test_list_cache_invalidated_on_post_delete(self):
        user = User.objects.create_user(
            email="lc3@t.com", username="listcache3", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Delete me from list")
        client = APIClient()
        client.force_authenticate(user=user)
        client.get(self.url)
        client.delete(f"{API_ROOT}posts/{post.id}/")
        resp = client.get(self.url)
        ids = [p["id"] for p in resp.data["data"]]
        assert str(post.id) not in ids


class TestPostDetail:
    def url(self, pk):
        return f"{API_ROOT}posts/{pk}/"

    def test_retrieve_post(self):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Detail test")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url(post.id))
        assert resp.status_code == 200
        assert resp.data["data"]["body"] == "Detail test"

    def test_retrieve_deleted_returns_404(self):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Gone")
        post.delete()
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url(post.id))
        assert resp.status_code == 404

    def test_retrieve_returns_cached_response_on_repeat_request(self):
        user = User.objects.create_user(
            email="dc@t.com", username="detailcache", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Cache me")
        client = APIClient()
        client.force_authenticate(user=user)
        resp1 = client.get(self.url(post.id))
        resp2 = client.get(self.url(post.id))
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.data["data"]["body"] == resp2.data["data"]["body"]
        assert resp1.data["data"]["id"] == resp2.data["data"]["id"]

    def test_retrieve_cache_invalidated_on_post_update(self):
        user = User.objects.create_user(
            email="dc2@t.com", username="detailcache2", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Before")
        client = APIClient()
        client.force_authenticate(user=user)
        client.get(self.url(post.id))
        client.patch(self.url(post.id), {"body": "After"}, format="json")
        resp = client.get(self.url(post.id))
        assert resp.data["data"]["body"] == "After"

    def test_retrieve_cache_invalidated_on_post_delete(self):
        user = User.objects.create_user(
            email="dc3@t.com", username="detailcache3", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Bye")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url(post.id))
        assert resp.status_code == 200
        client.delete(self.url(post.id))
        resp = client.get(self.url(post.id))
        assert resp.status_code == 404

    def test_retrieve_is_liked_patched_on_cache_hit(self):
        user1 = User.objects.create_user(
            email="u1@t.com", username="userone", password="pass", is_active=True,
        )
        user2 = User.objects.create_user(
            email="u2@t.com", username="usertwo", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user1, body="Like check")
        Like.objects.create(
            user=user1,
            content_type=ContentType.objects.get_for_model(Post),
            object_id=post.id,
        )
        client1 = APIClient()
        client1.force_authenticate(user=user1)
        client2 = APIClient()
        client2.force_authenticate(user=user2)
        resp1 = client1.get(self.url(post.id))
        assert resp1.data["data"]["is_liked"] is True
        resp2 = client2.get(self.url(post.id))
        assert resp2.data["data"]["is_liked"] is False

    def test_retrieve_is_liked_false_for_anonymous_on_cache_hit(self):
        user = User.objects.create_user(
            email="anon@t.com", username="anonuser", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Anon check")
        Like.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Post),
            object_id=post.id,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.get(self.url(post.id))
        resp = APIClient().get(self.url(post.id))
        assert resp.data["data"]["is_liked"] is False


class TestPostUpdate:
    def url(self, pk):
        return f"{API_ROOT}posts/{pk}/"

    def test_update_own_post(self):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Original")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.patch(self.url(post.id), {"body": "Updated"}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["body"] == "Updated"

    def test_cannot_update_others_post(self):
        author = User.objects.create_user(
            email="a@t.com", username="author", password="pass", is_active=True,
        )
        other = User.objects.create_user(
            email="o@t.com", username="other", password="pass", is_active=True,
        )
        post = Post.objects.create(author=author, body="Mine")
        client = APIClient()
        client.force_authenticate(user=other)
        resp = client.patch(self.url(post.id), {"body": "Hacked"}, format="json")
        assert resp.status_code == 403

    def test_unauthenticated_cannot_update(self):
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Nope",
        )
        resp = APIClient().patch(self.url(post.id), {"body": "X"}, format="json")
        assert resp.status_code == 401


class TestPostDelete:
    def url(self, pk):
        return f"{API_ROOT}posts/{pk}/"

    def test_delete_own_post(self):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Delete me")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.delete(self.url(post.id))
        assert resp.status_code == 200
        assert Post.objects.get(pk=post.id).is_deleted is True

    def test_cannot_delete_others_post(self):
        author = User.objects.create_user(
            email="a@t.com", username="author", password="pass", is_active=True,
        )
        other = User.objects.create_user(
            email="o@t.com", username="other", password="pass", is_active=True,
        )
        post = Post.objects.create(author=author, body="Safe")
        client = APIClient()
        client.force_authenticate(user=other)
        resp = client.delete(self.url(post.id))
        assert resp.status_code == 403

    def test_unauthenticated_cannot_delete(self):
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Safe",
        )
        resp = APIClient().delete(self.url(post.id))
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
#  Comment CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestCommentCreate:
    def url(self, post_id):
        return f"{API_ROOT}posts/{post_id}/comments/"

    def test_create_comment(self):
        user = User.objects.create_user(
            email="c@t.com", username="commenter", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="My post")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url(post.id), {"body": "Nice post!"}, format="json")
        assert resp.status_code == 201
        assert resp.data["data"]["body"] == "Nice post!"

    def test_create_reply(self):
        user = User.objects.create_user(
            email="c@t.com", username="commenter", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Post")
        comment = Comment.objects.create(post=post, author=user, body="Top")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            self.url(post.id),
            {"body": "Reply", "parent_id": str(comment.id)},
            format="json",
        )
        assert resp.status_code == 201


class TestCommentList:
    def url(self, post_id):
        return f"{API_ROOT}posts/{post_id}/comments/"

    def test_list_top_level_comments(self):
        user = User.objects.create_user(
            email="c@t.com", username="commenter", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Post")
        Comment.objects.create(post=post, author=user, body="Top1")
        Comment.objects.create(post=post, author=user, body="Top2")
        reply = Comment.objects.create(post=post, author=user, body="Reply", parent_id=None)
        reply.parent = Comment.objects.create(post=post, author=user, body="Parent")
        reply.parent_id = reply.parent.id
        reply.save()

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url(post.id))
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 3


class TestReplyList:
    def url(self, post_id, comment_id):
        return f"{API_ROOT}posts/{post_id}/comments/{comment_id}/replies/"

    def test_list_replies(self):
        user = User.objects.create_user(
            email="c@t.com", username="commenter", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Post")
        parent = Comment.objects.create(post=post, author=user, body="Parent")
        Comment.objects.create(post=post, author=user, body="Reply1", parent=parent)
        Comment.objects.create(post=post, author=user, body="Reply2", parent=parent)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url(post.id, parent.id))
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
#  Reshare CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestReshareCreate:
    url = f"{API_ROOT}reshares/"

    def test_create_reshare(self):
        user = User.objects.create_user(
            email="r@t.com", username="resharer", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Original",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {"original_post_id": str(post.id)}, format="json")
        assert resp.status_code == 201
        assert resp.data["status"] is True

    def test_cannot_reshare_twice(self):
        user = User.objects.create_user(
            email="r@t.com", username="resharer", password="pass", is_active=True,
        )
        original = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Original",
        )
        reshare_post = Post.objects.create(author=user, body="", reshare_of=original)
        Reshare.objects.create(user=user, original_post=original, reshare_post=reshare_post)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {"original_post_id": str(original.id)}, format="json")
        assert resp.status_code == 409

    def test_reshare_deleted_post_returns_404(self):
        user = User.objects.create_user(
            email="r@t.com", username="resharer", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Gone",
        )
        post.delete()
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url, {"original_post_id": str(post.id)}, format="json")
        assert resp.status_code == 404


class TestReshareDelete:
    def url(self, pk):
        return f"{API_ROOT}reshares/{pk}/"

    def test_delete_own_reshare(self):
        user = User.objects.create_user(
            email="r@t.com", username="resharer", password="pass", is_active=True,
        )
        original = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Original",
        )
        reshare_post = Post.objects.create(author=user, body="", reshare_of=original)
        reshare = Reshare.objects.create(user=user, original_post=original, reshare_post=reshare_post)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.delete(self.url(reshare.id))
        assert resp.status_code == 200

    def test_cannot_delete_others_reshare(self):
        author = User.objects.create_user(
            email="a@t.com", username="author", password="pass", is_active=True,
        )
        other = User.objects.create_user(
            email="o@t.com", username="other", password="pass", is_active=True,
        )
        original = Post.objects.create(author=author, body="Original")
        reshare_post = Post.objects.create(author=author, body="", reshare_of=original)
        reshare = Reshare.objects.create(user=author, original_post=original, reshare_post=reshare_post)

        client = APIClient()
        client.force_authenticate(user=other)
        resp = client.delete(self.url(reshare.id))
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  Like / Unlike (REST API)
# ─────────────────────────────────────────────────────────────────────────────


class TestPostLike:
    def url(self, pk):
        return f"{API_ROOT}posts/{pk}/like/"

    def test_like_post(self):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Lovable",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url(post.id))
        assert resp.status_code == 200
        assert resp.data["data"]["liked"] is True

    def test_unlike_post(self):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Unlovable",
        )
        Like.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Post),
            object_id=post.id,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url(post.id))
        assert resp.status_code == 200
        assert resp.data["data"]["liked"] is False

    def test_like_unauthorized(self):
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Secret",
        )
        resp = APIClient().post(self.url(post.id))
        assert resp.status_code == 401

    def test_like_deleted_post_returns_404(self):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Gone",
        )
        post.delete()
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url(post.id))
        assert resp.status_code == 404

    def test_like_shows_in_is_liked_field(self):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Check",
        )
        Like.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Post),
            object_id=post.id,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(f"{API_ROOT}posts/{post.id}/")
        assert resp.status_code == 200
        assert resp.data["data"]["is_liked"] is True

    def test_like_invalidates_detail_cache(self):
        user = User.objects.create_user(
            email="l2@t.com", username="liker2", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a2@t.com", username="author2", password="pass", is_active=True),
            body="Invalidate cache",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp_before = client.get(f"{API_ROOT}posts/{post.id}/")
        assert resp_before.status_code == 200
        assert resp_before.data["data"]["is_liked"] is False
        client.post(self.url(post.id))
        resp_after = client.get(f"{API_ROOT}posts/{post.id}/")
        assert resp_after.status_code == 200
        assert resp_after.data["data"]["is_liked"] is True


class TestCommentLike:
    def url(self, post_id, comment_id):
        return f"{API_ROOT}posts/{post_id}/comments/{comment_id}/like/"

    def test_like_comment(self):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Post",
        )
        comment = Comment.objects.create(post=post, author=user, body="Nice")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url(post.id, comment.id))
        assert resp.status_code == 200
        assert resp.data["data"]["liked"] is True

    def test_unlike_comment(self):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(email="a@t.com", username="author", password="pass", is_active=True),
            body="Post",
        )
        comment = Comment.objects.create(post=post, author=user, body="Meh")
        Like.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Comment),
            object_id=comment.id,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(self.url(post.id, comment.id))
        assert resp.status_code == 200
        assert resp.data["data"]["liked"] is False


class TestRealTimeLikeBroadcast:
    """Tests for real-time WebSocket broadcasting on like/unlike."""

    def url(self, pk):
        return f"{API_ROOT}posts/{pk}/like/"

    @patch("social.services.like.broadcast_post_event")
    def test_like_post_broadcasts_event(self, mock_broadcast):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(
                email="a@t.com", username="author", password="pass", is_active=True,
            ),
            body="Real-time test",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.post(self.url(post.id))

        post.refresh_from_db()
        mock_broadcast.assert_called_once_with(
            str(post.id),
            {
                "event": "like_update",
                "action": "liked",
                "user_id": str(user.id),
                "username": "liker",
                "likes_count": post.likes_count,
            },
        )

    @patch("social.services.like.broadcast_post_event")
    def test_unlike_post_broadcasts_event(self, mock_broadcast):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(
                email="a@t.com", username="author", password="pass", is_active=True,
            ),
            body="Real-time unlike",
        )
        Like.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Post),
            object_id=post.id,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.post(self.url(post.id))

        mock_broadcast.assert_called_once()
        post_id_arg, event_arg = mock_broadcast.call_args[0]
        assert post_id_arg == str(post.id)
        assert event_arg["event"] == "like_update"
        assert event_arg["action"] == "unliked"
        assert event_arg["user_id"] == str(user.id)
        assert event_arg["username"] == "liker"

    @patch("social.services.like.broadcast_post_event")
    def test_comment_like_broadcasts_to_parent_post(self, mock_broadcast):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(
                email="a@t.com", username="author", password="pass", is_active=True,
            ),
            body="Post",
        )
        comment = Comment.objects.create(post=post, author=user, body="Nice")
        client = APIClient()
        client.force_authenticate(user=user)
        client.post(f"{API_ROOT}posts/{post.id}/comments/{comment.id}/like/")

        comment.refresh_from_db()
        mock_broadcast.assert_called_once_with(
            str(post.id),
            {
                "event": "comment_like_update",
                "action": "liked",
                "user_id": str(user.id),
                "username": "liker",
                "likes_count": comment.likes_count,
                "comment_id": str(comment.id),
            },
        )

    @patch("social.services.like.broadcast_post_event")
    def test_comment_unlike_broadcasts_to_parent_post(self, mock_broadcast):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(
                email="a@t.com", username="author", password="pass", is_active=True,
            ),
            body="Post",
        )
        comment = Comment.objects.create(post=post, author=user, body="Meh")
        Like.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Comment),
            object_id=comment.id,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.post(f"{API_ROOT}posts/{post.id}/comments/{comment.id}/like/")

        mock_broadcast.assert_called_once()
        post_id_arg, event_arg = mock_broadcast.call_args[0]
        assert post_id_arg == str(post.id)
        assert event_arg["event"] == "comment_like_update"
        assert event_arg["action"] == "unliked"
        assert event_arg["user_id"] == str(user.id)
        assert event_arg["comment_id"] == str(comment.id)


class TestRealTimeCommentBroadcast:
    """Items 1, 2, 7: Live comment + count broadcast on create/delete."""

    @patch("social.services.comment.broadcast_post_event")
    @patch("social.services.comment.broadcast_trending_event")
    def test_comment_create_broadcasts_event(self, mock_trending, mock_broadcast):
        user = User.objects.create_user(
            email="c@t.com", username="commenter", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(
                email="a@t.com", username="author", password="pass", is_active=True,
            ),
            body="Commentable",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(f"{API_ROOT}posts/{post.id}/comments/", {"body": "Nice post!"}, format="json")
        assert resp.status_code == 201

        post.refresh_from_db()
        mock_broadcast.assert_called_once()
        post_id_arg, event_arg = mock_broadcast.call_args[0]
        assert post_id_arg == str(post.id)
        assert event_arg["event"] == "comment.new"
        assert event_arg["body"] == "Nice post!"
        assert event_arg["author_id"] == str(user.id)
        assert event_arg["comments_count"] == post.comments_count

        mock_trending.assert_called_once()
        trending_arg = mock_trending.call_args[0][0]
        assert trending_arg["event"] == "trending.updated"
        assert trending_arg["post_id"] == str(post.id)

    @patch("social.services.comment.broadcast_post_event")
    def test_comment_delete_broadcasts_event(self, mock_broadcast):
        user = User.objects.create_user(
            email="c@t.com", username="commenter", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(
                email="a@t.com", username="author", password="pass", is_active=True,
            ),
            body="Deletable",
        )
        comment = Comment.objects.create(post=post, author=user, body="Bye")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.delete(f"{API_ROOT}posts/{post.id}/comments/{comment.id}/")
        assert resp.status_code == 200

        mock_broadcast.assert_called_once()
        post_id_arg, event_arg = mock_broadcast.call_args[0]
        assert post_id_arg == str(post.id)
        assert event_arg["event"] == "comment.deleted"
        assert event_arg["comment_id"] == str(comment.id)

    @patch("social.services.comment.broadcast_post_event")
    def test_comment_reply_broadcasts_event(self, mock_broadcast):
        user = User.objects.create_user(
            email="c@t.com", username="commenter", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(
                email="a@t.com", username="author", password="pass", is_active=True,
            ),
            body="Reply test",
        )
        parent = Comment.objects.create(post=post, author=user, body="Parent")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            f"{API_ROOT}posts/{post.id}/comments/",
            {"body": "Reply!", "parent_id": str(parent.id)},
            format="json",
        )
        assert resp.status_code == 201

        mock_broadcast.assert_called_once()
        _, event_arg = mock_broadcast.call_args[0]
        assert event_arg["event"] == "comment.new"
        assert event_arg["parent_id"] == str(parent.id)


class TestRealTimePostUpdateDelete:
    """Item 4: Post updated/deleted broadcasts."""

    @patch("social.services.post.broadcast_post_event")
    def test_post_update_broadcasts_event(self, mock_broadcast):
        user = User.objects.create_user(
            email="u@t.com", username="updater", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Old body")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.patch(f"{API_ROOT}posts/{post.id}/", {"body": "New body"}, format="json")
        assert resp.status_code == 200

        mock_broadcast.assert_called_once()
        post_id_arg, event_arg = mock_broadcast.call_args[0]
        assert post_id_arg == str(post.id)
        assert event_arg["event"] == "post.updated"
        assert event_arg["post_id"] == str(post.id)

    @patch("social.services.post.broadcast_post_event")
    def test_post_delete_broadcasts_event(self, mock_broadcast):
        user = User.objects.create_user(
            email="u@t.com", username="deleter", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Gone")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.delete(f"{API_ROOT}posts/{post.id}/")
        assert resp.status_code == 200

        mock_broadcast.assert_called_once()
        post_id_arg, event_arg = mock_broadcast.call_args[0]
        assert post_id_arg == str(post.id)
        assert event_arg["event"] == "post.deleted"


class TestRealTimePostCreateFeedBroadcast:
    """Item 3: New post enqueues broadcast_post_to_followers task."""

    @patch("social.services.post.broadcast_post_to_followers.delay")
    def test_post_create_enqueues_follower_broadcast(self, mock_task):
        user = User.objects.create_user(
            email="p@t.com", username="poster", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(f"{API_ROOT}posts/", {"body": "Hello feed!"}, format="json")
        assert resp.status_code == 201

        post_id = resp.data["data"]["id"]
        mock_task.assert_called_once()
        args = mock_task.call_args[1]
        assert args["post_id"] == post_id
        assert args["author_id"] == str(user.id)
        assert args["event"]["event"] == "post.new"


class TestRealTimeReshareBroadcast:
    """Items 2, 9: Reshare broadcasts to original post group."""

    @patch("social.services.reshare.broadcast_post_event")
    @patch("social.services.reshare.broadcast_trending_event")
    def test_reshare_create_broadcasts_event(self, mock_trending, mock_broadcast):
        user = User.objects.create_user(
            email="r@t.com", username="resha rer", password="pass", is_active=True,
        )
        author = User.objects.create_user(
            email="a2@t.com", username="author2", password="pass", is_active=True,
        )
        post = Post.objects.create(author=author, body="Reshareable")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(f"{API_ROOT}reshares/", {"original_post_id": str(post.id)}, format="json")
        assert resp.status_code == 201

        post.refresh_from_db()
        mock_broadcast.assert_called_once()
        post_id_arg, event_arg = mock_broadcast.call_args[0]
        assert post_id_arg == str(post.id)
        assert event_arg["event"] == "reshare.new"
        assert event_arg["user_id"] == str(user.id)
        assert event_arg["reshares_count"] == post.reshares_count

        mock_trending.assert_called_once()
        trending_arg = mock_trending.call_args[0][0]
        assert trending_arg["event"] == "trending.updated"
        assert trending_arg["post_id"] == str(post.id)

    @patch("social.services.reshare.broadcast_post_event")
    def test_reshare_delete_broadcasts_event(self, mock_broadcast):
        user = User.objects.create_user(
            email="r@t.com", username="resharer", password="pass", is_active=True,
        )
        author = User.objects.create_user(
            email="a3@t.com", username="author3", password="pass", is_active=True,
        )
        post = Post.objects.create(author=author, body="Unshareable")
        reshare_resp = APIClient()
        reshare_resp.force_authenticate(user=user)
        create_resp = reshare_resp.post(f"{API_ROOT}reshares/", {"original_post_id": str(post.id)}, format="json")
        reshare_id = create_resp.data["data"]["id"]

        mock_broadcast.reset_mock()
        resp = reshare_resp.delete(f"{API_ROOT}reshares/{reshare_id}/")
        assert resp.status_code == 200

        mock_broadcast.assert_called_once()
        post_id_arg, event_arg = mock_broadcast.call_args[0]
        assert post_id_arg == str(post.id)
        assert event_arg["event"] == "reshare.deleted"


class TestRealTimeFollowPresence:
    """Item 6: Follow/unfollow broadcasts presence event."""

    @patch("social.services.follow.broadcast_presence_event")
    def test_follow_broadcasts_presence(self, mock_presence):
        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(f"{API_ROOT}follow/{following.id}/")
        assert resp.status_code == 201

        mock_presence.assert_called_once_with(
            str(following.id),
            {
                "event": "presence.follow",
                "follower_id": str(follower.id),
                "follower_username": "follower",
            },
        )

    @patch("social.services.follow.broadcast_presence_event")
    def test_unfollow_broadcasts_presence(self, mock_presence):
        from accounts.models import Follow

        follower = User.objects.create_user(
            email="f@t.com", username="follower", password="pass", is_active=True,
        )
        following = User.objects.create_user(
            email="g@t.com", username="following", password="pass", is_active=True,
        )
        Follow.objects.create(
            follower=follower,
            following=following,
            status="accepted",
            accepted_at="2024-01-01T00:00:00Z",
        )
        client = APIClient()
        client.force_authenticate(user=follower)
        resp = client.post(f"{API_ROOT}unfollow/{following.id}/")
        assert resp.status_code == 200

        mock_presence.assert_called_once_with(
            str(following.id),
            {
                "event": "presence.unfollow",
                "follower_id": str(follower.id),
                "follower_username": "follower",
            },
        )


class TestPostTrending:
    url = f"{API_ROOT}posts/trending/"

    def test_trending_returns_only_public_posts(self):
        user = User.objects.create_user(
            email="tr@t.com", username="trender", password="pass", is_active=True,
        )
        Post.objects.create(author=user, body="Public post", visibility="public")
        Post.objects.create(author=user, body="Private post", visibility="private")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        bodies = [p["body"] for p in resp.data["data"]]
        assert "Public post" in bodies
        assert "Private post" not in bodies

    def test_trending_limits_to_10(self):
        user = User.objects.create_user(
            email="tr2@t.com", username="trender2", password="pass", is_active=True,
        )
        for i in range(15):
            Post.objects.create(author=user, body=f"Post {i}", visibility="public")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self.url)
        assert len(resp.data["data"]) <= 10

    def test_trending_returns_cached_response_on_repeat_request(self):
        user = User.objects.create_user(
            email="tr3@t.com", username="trender3", password="pass", is_active=True,
        )
        Post.objects.create(author=user, body="Trending cached", visibility="public")
        client = APIClient()
        client.force_authenticate(user=user)
        resp1 = client.get(self.url)
        resp2 = client.get(self.url)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        bodies_1 = {(p["body"], p["id"]) for p in resp1.data["data"]}
        bodies_2 = {(p["body"], p["id"]) for p in resp2.data["data"]}
        assert bodies_1 == bodies_2

    def test_trending_cache_invalidated_on_new_post(self):
        user = User.objects.create_user(
            email="tr4@t.com", username="trender4", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.get(self.url)
        Post.objects.create(author=user, body="New trending", visibility="public")
        resp = client.get(self.url)
        bodies = [p["body"] for p in resp.data["data"]]
        assert "New trending" in bodies

    def test_trending_cache_invalidated_on_post_delete(self):
        user = User.objects.create_user(
            email="tr5@t.com", username="trender5", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="To delete from trending", visibility="public")
        client = APIClient()
        client.force_authenticate(user=user)
        client.get(self.url)
        client.delete(f"{API_ROOT}posts/{post.id}/")
        resp = client.get(self.url)
        bodies = [p["body"] for p in resp.data["data"]]
        assert "To delete from trending" not in bodies


class TestRealTimeTrendingBroadcast:
    """Item 5: Trending updates broadcast on engagement."""

    @patch("social.services.like.broadcast_trending_event")
    def test_like_triggers_trending_broadcast(self, mock_trending):
        user = User.objects.create_user(
            email="l@t.com", username="liker", password="pass", is_active=True,
        )
        post = Post.objects.create(
            author=User.objects.create_user(
                email="a@t.com", username="author", password="pass", is_active=True,
            ),
            body="Trending test",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.post(f"{API_ROOT}posts/{post.id}/like/")

        post.refresh_from_db()
        mock_trending.assert_called_once()
        event_arg = mock_trending.call_args[0][0]
        assert event_arg["event"] == "trending.updated"
        assert event_arg["post_id"] == str(post.id)
        assert event_arg["likes_count"] == post.likes_count


# ─────────────────────────────────────────────────────────────────────────────
#  UserPostViewSet tests
# ─────────────────────────────────────────────────────────────────────────────


class TestUserPostList:
    url_template = f"{API_ROOT}users/{{user_id}}/posts/"

    def _url(self, user_id):
        return self.url_template.format(user_id=user_id)

    def test_returns_only_that_users_posts(self):
        user1 = User.objects.create_user(
            email="u1@t.com", username="user1", password="pass", is_active=True,
        )
        user2 = User.objects.create_user(
            email="u2@t.com", username="user2", password="pass", is_active=True,
        )
        p1 = Post.objects.create(author=user1, body="User1 post")
        Post.objects.create(author=user2, body="User2 post")

        client = APIClient()
        client.force_authenticate(user=user1)
        resp = client.get(self._url(user1.id))

        assert resp.status_code == 200
        ids = [p["id"] for p in resp.data["data"]]
        assert str(p1.id) in ids
        assert len(ids) == 1

    def test_excludes_deleted_posts(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        alive = Post.objects.create(author=user, body="Alive")
        dead = Post.objects.create(author=user, body="Dead")
        dead.delete()

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self._url(user.id))

        ids = [p["id"] for p in resp.data["data"]]
        assert str(alive.id) in ids
        assert str(dead.id) not in ids

    def test_unauthenticated_can_list(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        Post.objects.create(author=user, body="Public")
        resp = APIClient().get(self._url(user.id))
        assert resp.status_code == 200

    def test_empty_for_user_with_no_posts(self):
        user = User.objects.create_user(
            email="u@t.com", username="no_posts", password="pass", is_active=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self._url(user.id))
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_filter_by_media_type(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        image_media = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value,
            storage_key="img/key.jpg", original_filename="img.jpg",
        )
        video_media = Media.objects.create(
            owner=user, media_type=MediaType.VIDEO.value,
            storage_key="vid/key.mp4", original_filename="vid.mp4",
        )
        post_with_image = Post.objects.create(author=user, body="Has image")
        PostMedia.objects.create(post=post_with_image, media=image_media, position=0)
        post_with_video = Post.objects.create(author=user, body="Has video")
        PostMedia.objects.create(post=post_with_video, media=video_media, position=0)
        post_no_media = Post.objects.create(author=user, body="No media")

        client = APIClient()
        client.force_authenticate(user=user)

        resp = client.get(self._url(user.id), {"media_type": MediaType.IMAGE.value})
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.data["data"]]
        assert str(post_with_image.id) in ids
        assert str(post_with_video.id) not in ids
        assert str(post_no_media.id) not in ids

        resp = client.get(self._url(user.id), {"media_type": MediaType.VIDEO.value})
        ids = [p["id"] for p in resp.data["data"]]
        assert str(post_with_video.id) in ids
        assert str(post_with_image.id) not in ids

    def test_filter_by_media_type_unknown_returns_empty(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        media = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value,
            storage_key="img/key.jpg", original_filename="img.jpg",
        )
        post = Post.objects.create(author=user, body="Has image")
        PostMedia.objects.create(post=post, media=media, position=0)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self._url(user.id), {"media_type": "unknown"})
        assert resp.status_code == 200
        assert resp.data["data"] == []


class TestUserPostDetail:
    url_template = f"{API_ROOT}users/{{user_id}}/posts/{{pk}}/"

    def _url(self, user_id, pk):
        return self.url_template.format(user_id=user_id, pk=pk)

    def test_retrieve_post(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Detail test")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self._url(user.id, post.id))
        assert resp.status_code == 200
        assert resp.data["data"]["body"] == "Detail test"

    def test_retrieve_post_of_other_user_returns_404(self):
        author = User.objects.create_user(
            email="a@t.com", username="author", password="pass", is_active=True,
        )
        viewer = User.objects.create_user(
            email="v@t.com", username="viewer", password="pass", is_active=True,
        )
        post = Post.objects.create(author=author, body="Not yours")
        client = APIClient()
        client.force_authenticate(user=viewer)
        resp = client.get(self._url(viewer.id, post.id))
        assert resp.status_code == 404

    def test_retrieve_deleted_returns_404(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Gone")
        post.delete()
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(self._url(user.id, post.id))
        assert resp.status_code == 404

    def test_unauthenticated_can_retrieve(self):
        user = User.objects.create_user(
            email="u@t.com", username="user", password="pass", is_active=True,
        )
        post = Post.objects.create(author=user, body="Public")
        resp = APIClient().get(self._url(user.id, post.id))
        assert resp.status_code == 200
