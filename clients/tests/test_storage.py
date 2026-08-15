"""Contract tests for clients.storage.

The provider suite runs identical assertions against S3, Azure Blob and the
in-memory backend — the executable form of the substitutability guarantee.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.base import ContentFile
from PIL import Image

from clients.storage import (
    PresignedUpload,
    StorageError,
    StorageNotConfigured,
    StorageProvider,
    StorageService,
    StoredObject,
    available_providers,
    build_key,
    classify,
    get_provider,
    register_provider,
)
from clients.storage.providers.azure import AzureBlobProvider
from clients.storage.providers.local import FailingProvider, MemoryProvider
from clients.storage.providers.s3 import S3Provider


def png_bytes(size=(400, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def django_file(name="pic.png", data=None):
    return ContentFile(data if data is not None else png_bytes(), name=name)


# --------------------------------------------------------------------------
# Provider factories for the shared contract suite
# --------------------------------------------------------------------------

def _memory():
    return MemoryProvider()


def _s3():
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://s3.test/signed"
    return S3Provider(
        access_key_id="AK", secret_access_key="SK", bucket="bucket",
        region="eu-west-1", client=client,
    )


def _azure():
    service = MagicMock()
    return AzureBlobProvider(
        account_name="acct", account_key="a2V5", container="media",
        service_client=service,
    )


PROVIDERS = [
    pytest.param(_memory, id="memory"),
    pytest.param(_s3, id="s3"),
    pytest.param(_azure, id="azure"),
]


@pytest.mark.parametrize("factory", PROVIDERS)
class TestProviderContract:

    def test_is_a_storage_provider(self, factory):
        assert isinstance(factory(), StorageProvider)

    def test_has_a_stable_name(self, factory):
        name = factory().name
        assert isinstance(name, str) and name and name != "base"

    def test_upload_returns_a_stored_object(self, factory):
        provider = factory()
        result = provider.upload(
            io.BytesIO(b"data"), "images/x.jpg", content_type="image/jpeg"
        )
        assert isinstance(result, StoredObject)
        assert result.key == "images/x.jpg"
        assert result.provider == provider.name
        assert result.url.endswith("images/x.jpg")

    def test_url_for_is_pure_and_stable(self, factory):
        provider = factory()
        assert provider.url_for("a/b.jpg") == provider.url_for("a/b.jpg")
        assert provider.url_for("a/b.jpg").startswith("http")

    def test_delete_returns_true_on_success(self, factory):
        assert factory().delete("images/x.jpg") is True

    def test_delete_of_missing_key_is_idempotent(self, factory):
        """Contract: deleting an absent object is a successful delete."""
        assert factory().delete("images/never-existed.jpg") is True

    def test_delete_of_empty_key_is_false(self, factory):
        assert factory().delete("") is False

    def test_presigned_upload_shape(self, factory):
        signed = factory().presigned_upload(
            "images/x.jpg", content_type="image/jpeg", expires_in=600
        )
        assert isinstance(signed, PresignedUpload)
        assert signed.key == "images/x.jpg"
        assert signed.url.startswith("http")
        assert signed.expires_in == 600


class TestProviderWireDetails:
    """Each backend is driven the way its SDK expects."""

    def test_s3_passes_content_type_and_cache_headers(self):
        client = MagicMock()
        provider = S3Provider(
            access_key_id="AK", secret_access_key="SK", bucket="bkt",
            region="eu-west-1", client=client,
        )
        provider.upload(io.BytesIO(b"x"), "images/a.jpg", content_type="image/jpeg")

        args, kwargs = client.upload_fileobj.call_args
        assert args[1] == "bkt" and args[2] == "images/a.jpg"
        extra = kwargs["ExtraArgs"]
        assert extra["ContentType"] == "image/jpeg"
        assert extra["ContentDisposition"] == "inline"
        assert "immutable" in extra["CacheControl"]

    def test_s3_url_layout(self):
        # custom_domain="" means "explicitly none" -> derive from bucket+region.
        provider = S3Provider(
            access_key_id="AK", secret_access_key="SK",
            bucket="bkt", region="eu-west-1", custom_domain="", client=MagicMock(),
        )
        assert provider.url_for("images/a.jpg") == (
            "https://bkt.s3.eu-west-1.amazonaws.com/images/a.jpg"
        )

    def test_azure_url_layout_includes_the_container(self):
        provider = AzureBlobProvider(
            account_name="acct", account_key="k", container="media",
            service_client=MagicMock(),
        )
        assert provider.url_for("images/a.jpg") == (
            "https://acct.blob.core.windows.net/media/images/a.jpg"
        )

    def test_azure_honours_a_cdn_domain(self):
        provider = AzureBlobProvider(
            account_name="acct", account_key="k", container="media",
            custom_domain="https://cdn.example.net", service_client=MagicMock(),
        )
        assert provider.url_for("a.jpg") == "https://cdn.example.net/media/a.jpg"

    def test_azure_sets_content_settings(self):
        service = MagicMock()
        provider = AzureBlobProvider(
            account_name="acct", account_key="k", container="media",
            service_client=service,
        )
        provider.upload(io.BytesIO(b"x"), "images/a.jpg", content_type="image/jpeg")

        blob = service.get_blob_client.return_value
        kwargs = blob.upload_blob.call_args.kwargs
        assert kwargs["overwrite"] is True
        settings_obj = kwargs["content_settings"]
        assert settings_obj.content_type == "image/jpeg"
        assert settings_obj.cache_control and "immutable" in settings_obj.cache_control

    def test_azure_presigned_upload_requires_the_blob_type_header(self):
        provider = AzureBlobProvider(
            account_name="acct", account_key="a2V5", container="media",
            service_client=MagicMock(),
        )
        with patch("azure.storage.blob.generate_blob_sas", return_value="sig=1"):
            signed = provider.presigned_upload(
                "images/a.jpg", content_type="image/jpeg"
            )
        assert signed.headers["x-ms-blob-type"] == "BlockBlob"
        assert "sig=1" in signed.url


class TestFailureContract:

    def test_s3_error_is_wrapped(self):
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.upload_fileobj.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "PutObject"
        )
        provider = S3Provider(
            access_key_id="AK", secret_access_key="SK", bucket="b", client=client
        )
        with pytest.raises(StorageError) as exc:
            provider.upload(io.BytesIO(b"x"), "k.jpg", content_type="image/jpeg")
        assert exc.value.provider == "s3"
        assert exc.value.key == "k.jpg"

    def test_azure_error_is_wrapped(self):
        from azure.core.exceptions import AzureError

        service = MagicMock()
        service.get_blob_client.return_value.upload_blob.side_effect = AzureError("boom")
        provider = AzureBlobProvider(
            account_name="a", account_key="k", container="c", service_client=service
        )
        with pytest.raises(StorageError) as exc:
            provider.upload(io.BytesIO(b"x"), "k.jpg", content_type="image/jpeg")
        assert exc.value.provider == "azure"

    def test_azure_missing_blob_delete_is_still_success(self):
        from azure.core.exceptions import ResourceNotFoundError

        service = MagicMock()
        service.get_blob_client.return_value.delete_blob.side_effect = (
            ResourceNotFoundError("gone")
        )
        provider = AzureBlobProvider(
            account_name="a", account_key="k", container="c", service_client=service
        )
        assert provider.delete("images/a.jpg") is True

    def test_delete_failure_returns_false_rather_than_raising(self):
        service = MagicMock()
        service.get_blob_client.return_value.delete_blob.side_effect = RuntimeError("x")
        provider = AzureBlobProvider(
            account_name="a", account_key="k", container="c", service_client=service
        )
        assert provider.delete("images/a.jpg") is False

    def test_unconfigured_provider_raises_a_clear_error(self):
        with pytest.raises(StorageNotConfigured):
            S3Provider(access_key_id="", secret_access_key="", bucket="").upload(
                io.BytesIO(b"x"), "k.jpg", content_type="image/jpeg"
            )
        with pytest.raises(StorageNotConfigured):
            AzureBlobProvider(
                connection_string="", account_name="", account_key="", container="c"
            ).upload(io.BytesIO(b"x"), "k.jpg", content_type="image/jpeg")

    def test_is_configured_reports_honestly(self):
        assert S3Provider(access_key_id="A", secret_access_key="S", bucket="b").is_configured()
        assert not S3Provider(access_key_id="", secret_access_key="", bucket="").is_configured()
        assert AzureBlobProvider(
            account_name="a", account_key="k", container="c"
        ).is_configured()
        assert not AzureBlobProvider(
            connection_string="", account_name="", account_key="", container=""
        ).is_configured()

    def test_provider_without_presigned_support_says_so(self):
        class NoSigning(StorageProvider):
            name = "nosign"

            def upload(self, fileobj, key, *, content_type, **kw):
                return StoredObject(key=key, url="x", provider=self.name)

            def delete(self, key):
                return True

            def url_for(self, key):
                return f"https://nosign.test/{key}"

        with pytest.raises(StorageError, match="does not support presigned"):
            NoSigning().presigned_upload("k", content_type="image/jpeg")


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

class TestRegistry:

    def test_builtins_registered(self):
        for name in ("s3", "azure", "memory"):
            assert name in available_providers()

    def test_unknown_provider_is_a_clear_error(self):
        with pytest.raises(ValueError, match="Unknown storage provider"):
            get_provider("dropbox")

    def test_settings_select_the_provider(self, settings):
        settings.STORAGE_PROVIDER = "memory"
        assert isinstance(get_provider(), MemoryProvider)

    def test_legacy_storage_type_aws_still_resolves_to_s3(self, settings):
        """Existing deployments set STORAGE_TYPE=AWS; that must keep working."""
        settings.STORAGE_PROVIDER = ""
        settings.STORAGE_TYPE = "AWS"
        assert isinstance(get_provider(), S3Provider)

    def test_azure_selectable_by_name(self, settings):
        settings.STORAGE_PROVIDER = "azure"
        assert isinstance(get_provider(), AzureBlobProvider)

    def test_a_new_backend_needs_no_existing_code_change(self):
        class CloudinaryProvider(StorageProvider):
            name = "cloudinary-test"

            def upload(self, fileobj, key, *, content_type, **kw):
                return StoredObject(key=key, url=self.url_for(key), provider=self.name)

            def delete(self, key):
                return True

            def url_for(self, key):
                return f"https://res.cloudinary.com/demo/{key}"

        register_provider("cloudinary-test", CloudinaryProvider, replace=True)
        provider = get_provider("cloudinary-test")
        assert isinstance(provider, StorageProvider)
        assert provider.upload(io.BytesIO(b"x"), "a.jpg", content_type="image/jpeg").key == "a.jpg"

    def test_duplicate_registration_rejected(self):
        with pytest.raises(ValueError, match="already registered"):
            register_provider("s3", MemoryProvider)


# --------------------------------------------------------------------------
# Classification is backend-independent
# --------------------------------------------------------------------------

class TestClassification:

    @pytest.mark.parametrize(
        "name,media_type,mime",
        [
            ("a.jpg", "image", "image/jpeg"),
            ("a.mp4", "video", "video/mp4"),
            ("a.mp3", "audio", "audio/mpeg"),
            ("a.pdf", "document", "application/pdf"),
        ],
    )
    def test_classify(self, name, media_type, mime):
        info = classify(name)
        assert info["media_type"] == media_type and info["mime"] == mime

    def test_unsupported_extension_rejected(self):
        with pytest.raises(ValueError, match="Unsupported file format"):
            classify("virus.exe")

    def test_key_layout_is_foldered_and_unique(self):
        a, b = build_key("image", ".jpg"), build_key("image", ".jpg")
        assert a.startswith("images/") and a.endswith(".jpg")
        assert a != b

    def test_key_layout_is_identical_regardless_of_backend(self):
        """Same input -> same folder on S3 and Azure."""
        for provider in (_s3(), _azure(), _memory()):
            svc = StorageService(provider=provider)
            assert svc.build_key("video", ".mp4").startswith("videos/")


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------

class TestStorageService:

    def test_upload_classifies_normalises_and_stores(self):
        provider = MemoryProvider()
        result = StorageService(provider=provider).upload(django_file("pic.png"))

        assert isinstance(result, StoredObject)
        assert result.media_type == "image"
        assert result.key.startswith("images/") and result.key.endswith(".png")
        assert result.content_type == "image/png"
        assert (result.width, result.height) == (400, 300)
        assert result.key in provider.objects

    def test_non_image_is_stored_untouched(self):
        provider = MemoryProvider()
        result = StorageService(provider=provider).upload(
            django_file("notes.pdf", b"%PDF-1.4 hello")
        )
        assert result.media_type == "document"
        assert result.content_type == "application/pdf"
        assert provider.objects[result.key]["data"] == b"%PDF-1.4 hello"

    def test_oversized_file_rejected_before_any_upload(self):
        provider = MemoryProvider()
        big = django_file("big.png")
        big.size = 999 * 1024 * 1024
        with pytest.raises(ValueError, match="exceeds"):
            StorageService(provider=provider).upload(big)
        assert provider.objects == {}

    def test_unsupported_type_rejected_before_any_upload(self):
        provider = MemoryProvider()
        with pytest.raises(ValueError, match="Unsupported file format"):
            StorageService(provider=provider).upload(django_file("x.exe", b"MZ"))
        assert provider.objects == {}

    def test_upload_to_key_skips_processing(self):
        provider = MemoryProvider()
        result = StorageService(provider=provider).upload_to_key(
            io.BytesIO(b"ready"), "images/fixed.jpg", content_type="image/jpeg"
        )
        assert result.key == "images/fixed.jpg"
        assert provider.objects["images/fixed.jpg"]["data"] == b"ready"

    def test_delete_and_url_for(self):
        provider = MemoryProvider()
        svc = StorageService(provider=provider)
        stored = svc.upload(django_file())
        assert svc.url_for(stored.key) == stored.url
        assert svc.delete(stored.key) is True
        assert stored.key not in provider.objects

    def test_delete_url_round_trips(self):
        provider = MemoryProvider()
        svc = StorageService(provider=provider)
        stored = svc.upload(django_file())
        assert svc.delete_url(stored.url) is True

    def test_presigned_upload_carries_media_type(self):
        signed = StorageService(provider=MemoryProvider()).presigned_upload("clip.mp4")
        assert signed.media_type == "video"
        assert signed.content_type == "video/mp4"
        assert signed.key.startswith("videos/")

    def test_upload_failure_propagates(self):
        with pytest.raises(StorageError):
            StorageService(provider=FailingProvider()).upload(django_file())

    def test_same_file_produces_same_shape_on_every_backend(self):
        """LSP payoff: only the URL host differs."""
        results = {}
        for factory in (_memory, _s3, _azure):
            provider = factory()
            svc = StorageService(provider=provider)
            results[provider.name] = svc.upload(django_file("pic.png"))

        shapes = {
            (r.media_type, r.content_type, r.width, r.height, r.key.split("/")[0])
            for r in results.values()
        }
        assert len(shapes) == 1, f"backends disagreed: {shapes}"
