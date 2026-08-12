"""End-to-end coverage for the async profile-image upload/delete flow."""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import User, UserProfile
from medias.models import Media
from utils import images
from utils.enum import ProcessingStatus


def _png(size=(1200, 800), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(raw: bytes, name="pic.png", content_type="image/png"):
    return SimpleUploadedFile(name, raw, content_type=content_type)


@pytest.fixture
def user(db):
    u = User.objects.create(username="imguser", email="img@example.com")
    UserProfile.objects.get_or_create(user=u)
    return u


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


URLS = {
    "avatar": "/api/v2/accounts/me/profile/avatar/",
    "cover_photo": "/api/v2/accounts/me/profile/cover/",
    "display_photo": "/api/v2/accounts/me/profile/display-photo/",
}


@pytest.mark.django_db(transaction=True)
class TestProfileImageUpload:

    @patch("accounts.tasks.process_profile_image.delay")
    def test_returns_202_without_touching_s3(self, mock_delay, client, user):
        """The request path must not perform the S3 upload itself."""
        with patch("clients.aws.storage.upload_fileobj_to_key") as mock_s3:
            resp = client.put(
                URLS["avatar"], {"file": _upload(_png())}, format="multipart"
            )

        assert resp.status_code == 202, resp.data
        assert mock_s3.call_count == 0, "S3 must not be hit in the request path"
        assert mock_delay.call_count == 1

        body = resp.data
        assert body["status"] is True
        assert body["data"]["processing_status"] == ProcessingStatus.PENDING.value
        assert body["data"]["avatar"].endswith(".jpg")

        media = Media.objects.get(pk=body["data"]["media_id"])
        assert media.processing_status == ProcessingStatus.PENDING.value
        assert media.owner_id == user.id

        # Task got the staging key, not the bytes.
        kwargs = mock_delay.call_args.kwargs
        assert set(kwargs) == {"media_id", "user_id", "field", "staging_key"}
        assert kwargs["staging_key"].startswith("staging:blob:")

    @patch("accounts.tasks.process_profile_image.delay")
    def test_profile_field_not_set_until_task_runs(self, _mock, client, user):
        client.put(URLS["avatar"], {"file": _upload(_png())}, format="multipart")
        user.profile.refresh_from_db()
        assert user.profile.avatar is None

    @pytest.mark.parametrize("field", ["avatar", "cover_photo", "display_photo"])
    @patch("accounts.tasks.process_profile_image.delay")
    def test_all_three_slots(self, mock_delay, field, client):
        resp = client.put(URLS[field], {"file": _upload(_png())}, format="multipart")
        assert resp.status_code == 202
        assert mock_delay.call_args.kwargs["field"] == field
        assert field in resp.data["data"]


@pytest.mark.django_db(transaction=True)
class TestProfileImageValidation:

    @pytest.mark.parametrize(
        "name,blob,content_type",
        [
            ("doc.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3", "application/pdf"),
            ("evil.sh", b"#!/bin/sh\nrm -rf /", "text/x-sh"),
            ("fake.png", b"not an image at all", "image/png"),
            ("empty.png", b"", "image/png"),
        ],
    )
    def test_rejects_non_images(self, name, blob, content_type, client):
        resp = client.put(
            URLS["avatar"],
            {"file": _upload(blob, name=name, content_type=content_type)},
            format="multipart",
        )
        assert resp.status_code == 400, f"{name} was accepted"
        assert Media.objects.count() == 0

    def test_rejects_oversized_image(self, client):
        from utils import images

        big = _png(size=(60, 60))
        upload = _upload(big)
        # Pretend it is over the byte ceiling without allocating 8 MB.
        with patch.object(images, "MAX_UPLOAD_BYTES", 10):
            resp = client.put(URLS["avatar"], {"file": upload}, format="multipart")
        assert resp.status_code == 400
        assert "MB or smaller" in str(resp.data)

    @pytest.mark.parametrize("fmt,ext", [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")])
    @patch("accounts.tasks.process_profile_image.delay")
    def test_accepts_common_image_formats(self, _m, fmt, ext, client):
        buf = io.BytesIO()
        Image.new("RGB", (300, 300), (5, 5, 5)).save(buf, format=fmt)
        resp = client.put(
            URLS["avatar"],
            {"file": _upload(buf.getvalue(), name=f"a.{ext}", content_type=f"image/{ext}")},
            format="multipart",
        )
        assert resp.status_code == 202, resp.data


@pytest.mark.skipif(
    not images.HEIF_SUPPORTED, reason="pillow-heif not installed in this environment"
)
@pytest.mark.django_db(transaction=True)
class TestHeicUploads:
    """iOS cameras shoot HEIC by default, so it must survive the whole path."""

    @staticmethod
    def _heic(size=(4032, 3024)) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", size, (180, 90, 40)).save(buf, format="HEIF", quality=80)
        return buf.getvalue()

    def test_probe_reports_heif(self):
        assert images.probe(self._heic())["format"] == "HEIF"

    def test_heic_is_transcoded_to_jpeg_and_downscaled(self):
        out = images.normalize(self._heic(), max_edge=images.max_edge_for("avatar"))
        assert out["source_format"] == "HEIF"
        assert out["content_type"] == "image/jpeg"
        assert max(out["width"], out["height"]) == 512
        assert Image.open(out["buffer"]).format == "JPEG"

    @pytest.mark.parametrize("name", ["IMG_0042.heic", "photo.HEIC", "shot.heif"])
    @patch("accounts.tasks.process_profile_image.delay")
    def test_endpoint_accepts_heic(self, _m, name, client):
        resp = client.put(
            URLS["avatar"],
            {"file": _upload(self._heic((800, 600)), name=name, content_type="image/heic")},
            format="multipart",
        )
        assert resp.status_code == 202, resp.data

    def test_heic_extension_does_not_bypass_content_check(self, client):
        resp = client.put(
            URLS["avatar"],
            {"file": _upload(b"%PDF-1.4 not an image", name="fake.heic",
                             content_type="image/heic")},
            format="multipart",
        )
        assert resp.status_code == 400

    @patch("accounts.tasks.send_user_push_notification.delay")
    @patch("clients.aws.storage.upload_fileobj_to_key")
    def test_heic_end_to_end_through_task(self, mock_s3, _push, user):
        from accounts.tasks import process_profile_image
        from clients.aws.storage import build_key
        from utils.staging import stage_blob

        media = Media.objects.create(
            owner=user, media_type="image", storage_key=build_key("image", ".jpg"),
            processing_status=ProcessingStatus.PENDING.value,
        )
        result = process_profile_image(
            media_id=str(media.id), user_id=str(user.id), field="avatar",
            staging_key=stage_blob(self._heic((1600, 1200))),
        )
        assert result["success"] is True
        assert mock_s3.call_args.kwargs["content_type"] == "image/jpeg"

        media.refresh_from_db()
        assert media.mime_type == "image/jpeg"
        assert media.storage_key.endswith(".jpg")
        assert max(media.width_px, media.height_px) == 512


@pytest.mark.django_db(transaction=True)
class TestProcessProfileImageTask:

    def _stage_and_row(self, user, field="avatar", raw=None):
        from clients.aws.storage import build_key
        from utils.staging import stage_blob

        key = build_key("image", ".jpg")
        media = Media.objects.create(
            owner=user, media_type="image", storage_key=key,
            processing_status=ProcessingStatus.PENDING.value,
        )
        staging_key = stage_blob(raw if raw is not None else _png())
        return media, staging_key

    @patch("accounts.tasks.send_user_push_notification.delay")
    @patch("clients.aws.storage.upload_fileobj_to_key")
    def test_uploads_downscales_and_attaches(self, mock_s3, _push, user):
        from accounts.tasks import process_profile_image

        media, staging_key = self._stage_and_row(user)
        result = process_profile_image(
            media_id=str(media.id), user_id=str(user.id),
            field="avatar", staging_key=staging_key,
        )

        assert result["success"] is True
        assert mock_s3.call_count == 1

        # Uploaded to the key reserved by the view, as JPEG.
        args, kwargs = mock_s3.call_args
        assert args[1] == media.storage_key
        assert kwargs["content_type"] == "image/jpeg"

        media.refresh_from_db()
        assert media.processing_status == ProcessingStatus.READY.value
        assert media.cdn_url.endswith(media.storage_key)
        assert max(media.width_px, media.height_px) == 512  # downscaled
        assert media.mime_type == "image/jpeg"

        user.profile.refresh_from_db()
        assert user.profile.avatar_id == media.id

    @patch("accounts.tasks.send_user_push_notification.delay")
    @patch("clients.aws.storage.upload_fileobj_to_key")
    def test_staging_blob_is_consumed(self, _s3, _push, user):
        from accounts.tasks import process_profile_image
        from utils.staging import peek_blob

        media, staging_key = self._stage_and_row(user)
        process_profile_image(
            media_id=str(media.id), user_id=str(user.id),
            field="avatar", staging_key=staging_key,
        )
        assert peek_blob(staging_key) is None, "staged bytes must be reclaimed"

    @patch("accounts.tasks.cleanup_old_profile_image.delay")
    @patch("clients.aws.storage.upload_fileobj_to_key")
    def test_replacing_queues_cleanup_of_previous(self, _s3, mock_cleanup, user):
        from accounts.tasks import process_profile_image

        first, k1 = self._stage_and_row(user)
        process_profile_image(
            media_id=str(first.id), user_id=str(user.id),
            field="avatar", staging_key=k1,
        )
        second, k2 = self._stage_and_row(user)
        process_profile_image(
            media_id=str(second.id), user_id=str(user.id),
            field="avatar", staging_key=k2,
        )

        user.profile.refresh_from_db()
        assert user.profile.avatar_id == second.id
        assert mock_cleanup.call_args.kwargs["media_id"] == str(first.id)

    def test_expired_staging_marks_media_failed(self, user):
        from accounts.tasks import process_profile_image

        media, _ = self._stage_and_row(user)
        result = process_profile_image(
            media_id=str(media.id), user_id=str(user.id),
            field="avatar", staging_key="staging:blob:does-not-exist",
        )
        assert result == {"success": False, "error": "staging_expired"}
        media.refresh_from_db()
        assert media.processing_status == ProcessingStatus.FAILED.value
        assert media.processing_error

    @patch("clients.aws.storage.upload_fileobj_to_key")
    def test_s3_failure_raises_so_celery_retries(self, mock_s3, user):
        from accounts.tasks import process_profile_image

        mock_s3.side_effect = ValueError("S3 exploded")
        media, staging_key = self._stage_and_row(user)

        with pytest.raises(Exception):
            process_profile_image(
                media_id=str(media.id), user_id=str(user.id),
                field="avatar", staging_key=staging_key,
            )

        # Bytes must survive so the retry can use them.
        from utils.staging import peek_blob
        assert peek_blob(staging_key) is not None


@pytest.mark.django_db(transaction=True)
class TestProfileImageDelete:

    @patch("accounts.tasks.cleanup_old_profile_image.delay")
    @patch("clients.aws.storage.upload_fileobj_to_key")
    def test_detaches_now_and_defers_s3(self, _s3, mock_cleanup, client, user):
        from accounts.tasks import process_profile_image
        from clients.aws.storage import build_key
        from utils.staging import stage_blob

        media = Media.objects.create(
            owner=user, media_type="image", storage_key=build_key("image", ".jpg"),
            processing_status=ProcessingStatus.PENDING.value,
        )
        process_profile_image(
            media_id=str(media.id), user_id=str(user.id),
            field="avatar", staging_key=stage_blob(_png()),
        )
        mock_cleanup.reset_mock()

        # The task attached the avatar via its own UserProfile instance; re-auth
        # with a fresh User so request.user does not serve a cached relation.
        client.force_authenticate(user=User.objects.get(pk=user.pk))

        with patch("clients.aws.storage.delete_object") as mock_del:
            resp = client.delete(URLS["avatar"])

        assert resp.status_code == 200
        assert mock_del.call_count == 0, "S3 delete must not run in the request"
        assert mock_cleanup.call_count == 1
        assert mock_cleanup.call_args.kwargs["media_id"] == str(media.id)

        user.profile.refresh_from_db()
        assert user.profile.avatar is None
        assert resp.data["data"]["avatar"] is None

    def test_delete_when_nothing_set(self, client):
        resp = client.delete(URLS["avatar"])
        assert resp.status_code == 200
        assert resp.data["data"]["avatar"] is None

    @patch("accounts.tasks.send_user_push_notification.delay")
    def test_cleanup_task_removes_object_and_row(self, _push, user):
        from accounts.tasks import cleanup_old_profile_image

        media = Media.objects.create(
            owner=user, media_type="image", storage_key="images/abc.jpg",
            processing_status=ProcessingStatus.READY.value,
        )
        with patch("clients.aws.storage.delete_object") as mock_del:
            cleanup_old_profile_image(
                media_id=str(media.id), user_id=str(user.id),
                field="avatar", notify=False,
            )
        mock_del.assert_called_once_with("images/abc.jpg")
        media.refresh_from_db()
        assert media.is_deleted is True
