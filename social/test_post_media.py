"""Post <-> Media attachment: linking only, never re-uploading."""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from medias.models import Media
from social.models import Post, PostMedia
from social.services.post import PostService
from social.tasks import process_post_media
from utils.enum import ProcessingStatus

User = get_user_model()
POSTS_URL = "/api/v2/social/posts/"


@pytest.fixture
def author(db):
    return User.objects.create(username="author", email="author@example.com")


@pytest.fixture
def other_user(db):
    return User.objects.create(username="intruder", email="intruder@example.com")


def make_media(owner, *, status=ProcessingStatus.READY.value, deleted=False):
    media = Media.objects.create(
        owner=owner,
        media_type="image",
        storage_key=f"images/{uuid.uuid4()}.jpg",
        cdn_url="https://cdn.test/x.jpg",
        processing_status=status,
    )
    if deleted:
        media.delete()
    return media


@pytest.mark.django_db
class TestProcessPostMediaTask:

    def test_creates_postmedia_rows_in_order(self, author):
        post = Post.objects.create(author=author, body="hi")
        ids = [str(make_media(author).id) for _ in range(3)]

        result = process_post_media(str(post.id), ids)

        assert result["attached"] == 3
        rows = list(PostMedia.objects.filter(post=post).order_by("position"))
        assert [str(r.media_id) for r in rows] == ids
        assert [r.position for r in rows] == [0, 1, 2]

    def test_does_not_touch_storage(self, author, storage_objects):
        """The media endpoint already stored the bytes — nothing to upload."""
        post = Post.objects.create(author=author, body="hi")
        process_post_media(str(post.id), [str(make_media(author).id)])
        assert storage_objects.objects == {}

    def test_does_not_mutate_media_processing_status(self, author):
        """A PENDING upload must not be force-marked READY by attaching it."""
        post = Post.objects.create(author=author, body="hi")
        media = make_media(author, status=ProcessingStatus.PENDING.value)

        process_post_media(str(post.id), [str(media.id)])

        media.refresh_from_db()
        assert media.processing_status == ProcessingStatus.PENDING.value

    def test_failed_media_status_is_preserved(self, author):
        post = Post.objects.create(author=author, body="hi")
        media = make_media(author, status=ProcessingStatus.FAILED.value)
        process_post_media(str(post.id), [str(media.id)])
        media.refresh_from_db()
        assert media.processing_status == ProcessingStatus.FAILED.value

    def test_skips_media_owned_by_someone_else(self, author, other_user):
        post = Post.objects.create(author=author, body="hi")
        mine, theirs = make_media(author), make_media(other_user)

        result = process_post_media(str(post.id), [str(mine.id), str(theirs.id)])

        assert result["attached"] == 1
        assert str(theirs.id) in result["skipped"]
        assert not PostMedia.objects.filter(media=theirs).exists()

    def test_skips_deleted_and_missing_media(self, author):
        post = Post.objects.create(author=author, body="hi")
        gone = make_media(author, deleted=True)
        missing = str(uuid.uuid4())

        result = process_post_media(str(post.id), [str(gone.id), missing])

        assert result["attached"] == 0
        assert set(result["skipped"]) == {str(gone.id), missing}

    def test_is_idempotent_across_retries(self, author):
        post = Post.objects.create(author=author, body="hi")
        ids = [str(make_media(author).id) for _ in range(2)]

        process_post_media(str(post.id), ids)
        process_post_media(str(post.id), ids)  # Celery retry

        assert PostMedia.objects.filter(post=post).count() == 2

    def test_missing_post_is_handled(self, author):
        result = process_post_media(str(uuid.uuid4()), [str(make_media(author).id)])
        assert result["attached"] == 0

    def test_empty_media_list_is_a_noop(self, author):
        post = Post.objects.create(author=author, body="hi")
        assert process_post_media(str(post.id), []) == {"attached": 0, "skipped": []}


@pytest.mark.django_db(transaction=True)
class TestPostServiceMediaWiring:

    def test_create_attaches_via_the_task(self, author):
        ids = [str(make_media(author).id) for _ in range(2)]

        post = PostService.create(
            author=author, validated_data={"body": "hello", "media_ids": ids}
        )

        assert PostMedia.objects.filter(post=post).count() == 2

    def test_update_replaces_attachments(self, author):
        first, second = make_media(author), make_media(author)
        post = PostService.create(
            author=author, validated_data={"body": "hi", "media_ids": [str(first.id)]}
        )
        assert [str(r.media_id) for r in post.attachments.all()] == [str(first.id)]

        PostService.update(instance=post, validated_data={"media_ids": [str(second.id)]})

        assert [str(r.media_id) for r in post.attachments.all()] == [str(second.id)]

    def test_update_does_not_delete_detached_media_from_storage(
        self, author, storage_objects
    ):
        """Media is a reusable user asset — editing a post must not destroy it."""
        first, second = make_media(author), make_media(author)
        post = PostService.create(
            author=author, validated_data={"body": "hi", "media_ids": [str(first.id)]}
        )

        PostService.update(instance=post, validated_data={"media_ids": [str(second.id)]})

        first.refresh_from_db()
        assert first.is_deleted is False
        assert first.storage_key


@pytest.mark.django_db
class TestPostCreateMediaValidation:

    @staticmethod
    def _client(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_rejects_media_owned_by_another_user(self, author, other_user):
        theirs = make_media(other_user)
        resp = self._client(author).post(
            POSTS_URL, {"body": "hi", "media_ids": [str(theirs.id)]}, format="json"
        )
        assert resp.status_code == 400
        assert "not owned by you" in str(resp.data)
        assert Post.objects.count() == 0

    def test_rejects_unknown_media(self, author):
        resp = self._client(author).post(
            POSTS_URL, {"body": "hi", "media_ids": [str(uuid.uuid4())]}, format="json"
        )
        assert resp.status_code == 400

    def test_rejects_duplicate_ids(self, author):
        media = make_media(author)
        resp = self._client(author).post(
            POSTS_URL,
            {"body": "hi", "media_ids": [str(media.id), str(media.id)]},
            format="json",
        )
        assert resp.status_code == 400
        assert "Duplicate" in str(resp.data)

    def test_rejects_too_many_media(self, author):
        ids = [str(make_media(author).id) for _ in range(11)]
        resp = self._client(author).post(
            POSTS_URL, {"body": "hi", "media_ids": ids}, format="json"
        )
        assert resp.status_code == 400
        assert "at most" in str(resp.data)

    def test_accepts_own_media(self, author):
        ids = [str(make_media(author).id) for _ in range(2)]
        resp = self._client(author).post(
            POSTS_URL, {"body": "hi", "media_ids": ids}, format="json"
        )
        assert resp.status_code == 201, resp.data

    def test_post_without_media_still_works(self, author):
        resp = self._client(author).post(POSTS_URL, {"body": "no media"}, format="json")
        assert resp.status_code == 201, resp.data
