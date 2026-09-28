from __future__ import annotations

import pytest
from accounts.models import User
from medias.models import Collection, Media
from rest_framework.test import APIClient
from social.models import Comment, Post
from utils.enum import MediaType


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db) -> User:
    """A viewer whose profile genuinely matches 'dancing'.

    social/signals.py auto-creates a UserProfile for every User, so the
    profile is mutated here rather than created.
    """
    user = User.objects.create_user(
        email="dancer@test.com",
        username="dancer",
        password="pass123",
        is_active=True,
    )
    user.profile.display_name = "Sunday dancing"
    user.profile.save()
    return user


@pytest.fixture
def other_user(db) -> User:
    return User.objects.create_user(
        email="choreographer@test.com",
        username="choreographer",
        password="pass123",
        is_active=True,
    )


@pytest.fixture
def auth_client(api_client, user) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def matching_post(db, other_user) -> Post:
    return Post.objects.create(
        author=other_user,
        body="Practising my dancing routine every morning.",
        visibility="public",
    )


@pytest.fixture
def matching_comment(db, other_user, matching_post) -> Comment:
    return Comment.objects.create(
        post=matching_post,
        author=other_user,
        body="Your dancing form is improving fast.",
    )


@pytest.fixture
def matching_media(db, other_user) -> Media:
    return Media.objects.create(
        owner=other_user,
        media_type=MediaType.VIDEO.value,
        visibility="public",
        storage_key="search/dancing.mp4",
        cdn_url="https://cdn.test.com/dancing.mp4",
        original_filename="dancing.mp4",
        caption="Dancing class recap",
        alt_text="A dancer mid-movement",
    )


@pytest.fixture
def matching_collection(db, other_user) -> Collection:
    return Collection.objects.create(
        owner=other_user,
        name="Dancing videos",
        description="Footage from my dancing classes",
        is_public=True,
    )
