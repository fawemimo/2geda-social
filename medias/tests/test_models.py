from __future__ import annotations

import pytest
from django.db import IntegrityError

from accounts.models import User
from medias.models import Collection, CollectionItem, Media, MediaVariant
from utils.enum import MediaType, MediaVisibility, ProcessingStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="mediauser@t.com", username="mediauser", password="p",
    )


@pytest.fixture
def media(db, user):
    return Media.objects.create(
        owner=user,
        media_type=MediaType.IMAGE.value,
        storage_key="uploads/test/image.jpg",
        original_filename="photo.jpg",
        mime_type="image/jpeg",
        file_size_bytes=102400,
    )



#  Media



class TestMediaModel:
    def test_create_media(self, user):
        m = Media.objects.create(
            owner=user,
            media_type=MediaType.VIDEO.value,
            storage_key="uploads/test/video.mp4",
        )
        assert m.media_type == "video"
        assert m.pk is not None
        assert m.created_at is not None

    def test_default_visibility(self, user):
        m = Media.objects.create(
            owner=user,
            media_type=MediaType.IMAGE.value,
            storage_key="uploads/test/default.jpg",
        )
        assert m.visibility == MediaVisibility.PUBLIC.value

    def test_default_processing_status(self, user):
        m = Media.objects.create(
            owner=user,
            media_type=MediaType.IMAGE.value,
            storage_key="uploads/test/pending.jpg",
        )
        assert m.processing_status == ProcessingStatus.PENDING.value

    def test_storage_key_unique(self, user):
        Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value,
            storage_key="dup-key",
        )
        with pytest.raises(IntegrityError):
            Media.objects.create(
                owner=user, media_type=MediaType.IMAGE.value,
                storage_key="dup-key",
            )

    def test_str_with_filename(self, media):
        assert "image" in str(media)
        assert "photo.jpg" in str(media)

    def test_str_without_filename_falls_back_to_id(self, user):
        m = Media.objects.create(
            owner=user, media_type=MediaType.AUDIO.value,
            storage_key="uploads/test/noname.mp3",
        )
        assert str(m.id) in str(m)

    def test_soft_delete(self, media):
        media.delete()
        media.refresh_from_db()
        assert media.is_deleted is True
        assert media.deleted_at is not None

    def test_cdn_url_optional(self, user):
        m = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value,
            storage_key="cdn-test.jpg",
        )
        assert m.cdn_url == ""

    def test_dimensions_optional(self, user):
        m = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value,
            storage_key="dims-test.jpg",
            width_px=1920, height_px=1080,
        )
        assert m.width_px == 1920
        assert m.height_px == 1080

    def test_duration(self, user):
        m = Media.objects.create(
            owner=user, media_type=MediaType.VIDEO.value,
            storage_key="dur-test.mp4",
            duration_seconds=120.5,
        )
        assert m.duration_seconds == 120.5

    def test_blurhash(self, user):
        m = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value,
            storage_key="blur-test.jpg",
            blurhash="LFE.@D9F01?b~qMxR*j?",
        )
        assert m.blurhash == "LFE.@D9F01?b~qMxR*j?"

    def test_alt_text_and_caption(self, user):
        m = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value,
            storage_key="alt-test.jpg",
            alt_text="A beautiful sunset",
            caption="Sunset at the beach",
        )
        assert m.alt_text == "A beautiful sunset"
        assert m.caption == "Sunset at the beach"

    def test_processing_error_default(self, user):
        m = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value,
            storage_key="err-test.jpg",
        )
        assert m.processing_error == ""

    def test_owner_on_delete_cascade(self, user, media):
        uid = media.owner_id
        user.delete()
        assert Media.objects.filter(owner_id=uid).count() == 0



#  MediaVariant



class TestMediaVariantModel:
    def test_create_variant(self, media):
        v = MediaVariant.objects.create(
            media=media,
            label="thumbnail",
            storage_key="variants/test/thumb.jpg",
        )
        assert v.label == "thumbnail"
        assert v.pk is not None
        assert v.created_at is not None

    def test_unique_together_media_and_label(self, media):
        MediaVariant.objects.create(
            media=media, label="thumbnail", storage_key="vars/t1.jpg",
        )
        with pytest.raises(IntegrityError):
            MediaVariant.objects.create(
                media=media, label="thumbnail", storage_key="vars/t2.jpg",
            )

    def test_storage_key_unique(self, media):
        MediaVariant.objects.create(
            media=media, label="thumb", storage_key="vars/unique.jpg",
        )
        other_media = Media.objects.create(
            owner=media.owner, media_type=MediaType.IMAGE.value,
            storage_key="other.jpg",
        )
        with pytest.raises(IntegrityError):
            MediaVariant.objects.create(
                media=other_media, label="thumb", storage_key="vars/unique.jpg",
            )

    def test_str(self, media):
        v = MediaVariant.objects.create(
            media=media, label="medium", storage_key="vars/med.jpg",
        )
        assert str(media.id) in str(v)
        assert "medium" in str(v)

    def test_cdn_url_optional(self, media):
        v = MediaVariant.objects.create(
            media=media, label="thumb", storage_key="vars/cdn.jpg",
        )
        assert v.cdn_url == ""

    def test_dimensions_optional(self, media):
        v = MediaVariant.objects.create(
            media=media, label="thumb", storage_key="vars/dims.jpg",
            width_px=400, height_px=300,
        )
        assert v.width_px == 400

    def test_hard_delete(self, media):
        v = MediaVariant.objects.create(
            media=media, label="thumb", storage_key="vars/del.jpg",
        )
        pk = v.pk
        v.delete()
        assert MediaVariant.objects.filter(pk=pk).count() == 0



#  Collection



class TestCollectionModel:
    def test_create_collection(self, user):
        c = Collection.objects.create(owner=user, name="My Album")
        assert c.name == "My Album"
        assert c.pk is not None
        assert c.created_at is not None

    def test_default_is_public(self, user):
        c = Collection.objects.create(owner=user, name="Default Album")
        assert c.is_public is True

    def test_default_items_count(self, user):
        c = Collection.objects.create(owner=user, name="Empty Album")
        assert c.items_count == 0

    def test_str(self, user):
        c = Collection.objects.create(owner=user, name="Vacation Pics")
        assert "mediauser" in str(c)
        assert "Vacation Pics" in str(c)

    def test_cover_media_nullable(self, user, media):
        c = Collection.objects.create(owner=user, name="Covered", cover_media=media)
        assert c.cover_media == media

    def test_soft_delete(self, user):
        c = Collection.objects.create(owner=user, name="Temp")
        c.delete()
        c.refresh_from_db()
        assert c.is_deleted is True
        assert c.deleted_at is not None

    def test_owner_on_delete_cascade(self, user):
        c = Collection.objects.create(owner=user, name="ToGo")
        uid = user.pk
        user.delete()
        assert Collection.objects.filter(owner_id=uid).count() == 0

    def test_description_optional(self, user):
        c = Collection.objects.create(owner=user, name="NoDesc",
                                       description="Some description")
        assert c.description == "Some description"



#  CollectionItem



class TestCollectionItemModel:
    def test_create_item(self, user, media):
        c = Collection.objects.create(owner=user, name="Album")
        item = CollectionItem.objects.create(collection=c, media=media)
        assert item.position == 0
        assert item.pk is not None
        assert item.created_at is not None

    def test_unique_together_collection_and_media(self, user, media):
        c = Collection.objects.create(owner=user, name="Unique")
        CollectionItem.objects.create(collection=c, media=media)
        with pytest.raises(IntegrityError):
            CollectionItem.objects.create(collection=c, media=media)

    def test_default_ordering_by_position(self, user):
        c = Collection.objects.create(owner=user, name="Ordered")
        m1 = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value, storage_key="ord1.jpg",
        )
        m2 = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value, storage_key="ord2.jpg",
        )
        i1 = CollectionItem.objects.create(collection=c, media=m1, position=2)
        i2 = CollectionItem.objects.create(collection=c, media=m2, position=1)
        items = list(CollectionItem.objects.all())
        assert items == [i2, i1]

    def test_str(self, user, media):
        c = Collection.objects.create(owner=user, name="StrTest")
        item = CollectionItem.objects.create(collection=c, media=media, position=3)
        assert "StrTest" in str(item)
        assert "pos=3" in str(item)

    def test_caption_optional(self, user, media):
        c = Collection.objects.create(owner=user, name="CapTest")
        item = CollectionItem.objects.create(collection=c, media=media,
                                              caption="Nice shot!")
        assert item.caption == "Nice shot!"

    def test_hard_delete(self, user, media):
        c = Collection.objects.create(owner=user, name="DelTest")
        item = CollectionItem.objects.create(collection=c, media=media)
        pk = item.pk
        item.delete()
        assert CollectionItem.objects.filter(pk=pk).count() == 0

    def test_media_cascade(self, user):
        c = Collection.objects.create(owner=user, name="MediaDel")
        m = Media.objects.create(
            owner=user, media_type=MediaType.IMAGE.value, storage_key="cascade.jpg",
        )
        CollectionItem.objects.create(collection=c, media=m)
        m.delete()
        m.refresh_from_db()
        assert m.is_deleted is True
        # CollectionItem should still exist (FK cascades on DB level, but
        # soft_delete does not trigger CASCADE; the FK still points to the
        # soft-deleted Media row)
        assert CollectionItem.objects.filter(
            collection=c, media=m,
        ).count() == 1
