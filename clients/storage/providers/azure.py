"""Azure Blob Storage backend.

Configure with either:

    AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...

or the account name plus key:

    AZURE_STORAGE_ACCOUNT_NAME=myaccount
    AZURE_STORAGE_ACCOUNT_KEY=...
    AZURE_STORAGE_CONTAINER=media
    AZURE_STORAGE_CUSTOM_DOMAIN=https://cdn.example.net 
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from django.conf import settings

from clients.storage.base import (
    DEFAULT_CACHE_CONTROL,
    PresignedUpload,
    StorageError,
    StorageNotConfigured,
    StorageProvider,
    StoredObject,
)

logger = logging.getLogger(__name__)


def _setting(name: str, default: str | None = None) -> str | None:
    return getattr(settings, name, None) or os.getenv(name, default)


def _resolve(explicit: str | None, setting_name: str, default: str = "") -> str:
    if explicit is not None:
        return explicit
    return _setting(setting_name) or default


class AzureBlobProvider(StorageProvider):

    name = "azure"

    def __init__(
        self,
        *,
        connection_string: str | None = None,
        account_name: str | None = None,
        account_key: str | None = None,
        container: str | None = None,
        custom_domain: str | None = None,
        service_client=None,
    ) -> None:
        self.connection_string = _resolve(
            connection_string, "AZURE_STORAGE_CONNECTION_STRING"
        )
        self.account_name = _resolve(account_name, "AZURE_STORAGE_ACCOUNT_NAME")
        self.account_key = _resolve(account_key, "AZURE_STORAGE_ACCOUNT_KEY")
        self.container = _resolve(container, "AZURE_STORAGE_CONTAINER", "media")
        self._custom_domain = _resolve(custom_domain, "AZURE_STORAGE_CUSTOM_DOMAIN")
        self._service_client = service_client

    @property
    def custom_domain(self) -> str:
        return (
            self._custom_domain or f"https://{self.account_name}.blob.core.windows.net"
        ).rstrip("/")

    @property
    def service_client(self):
        # Imported lazily so an S3-only deployment never loads the Azure SDK.
        if self._service_client is None:
            from azure.storage.blob import BlobServiceClient

            if self.connection_string:
                self._service_client = BlobServiceClient.from_connection_string(
                    self.connection_string
                )
            else:
                self._service_client = BlobServiceClient(
                    account_url=f"https://{self.account_name}.blob.core.windows.net",
                    credential=self.account_key,
                )
        return self._service_client

    def _blob(self, key: str):
        return self.service_client.get_blob_client(container=self.container, blob=key)

    def is_configured(self) -> bool:
        if not self.container:
            return False
        return bool(self.connection_string or (self.account_name and self.account_key))

    def _require_config(self) -> None:
        if not self.is_configured():
            raise StorageNotConfigured(
                self.name,
                "Set AZURE_STORAGE_CONNECTION_STRING, or "
                "AZURE_STORAGE_ACCOUNT_NAME + AZURE_STORAGE_ACCOUNT_KEY, "
                "plus AZURE_STORAGE_CONTAINER.",
            )


    def url_for(self, key: str) -> str:
        return f"{self.custom_domain}/{self.container}/{key}"

    def upload(
        self,
        fileobj,
        key: str,
        *,
        content_type: str,
        cache_control: str = DEFAULT_CACHE_CONTROL,
    ) -> StoredObject:
        from azure.core.exceptions import AzureError
        from azure.storage.blob import ContentSettings

        self._require_config()
        try:
            self._blob(key).upload_blob(
                fileobj,
                overwrite=True,
                content_settings=ContentSettings(
                    content_type=content_type,
                    content_disposition="inline",
                    cache_control=cache_control,
                ),
            )
        except AzureError as exc:
            logger.exception("Azure upload failed for key %s: %s", key, exc)
            raise StorageError(
                f"Azure upload failed: {exc}", provider=self.name, key=key
            ) from exc

        return StoredObject(
            key=key,
            url=self.url_for(key),
            content_type=content_type,
            provider=self.name,
        )

    def delete(self, key: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        if not key:
            return False
        self._require_config()
        try:
            self._blob(key).delete_blob()
        except ResourceNotFoundError:
            logger.info("Azure blob already absent: %s", key)
            return True
        except Exception as exc:
            logger.exception("Azure delete failed for key %s: %s", key, exc)
            return False
        logger.info("Azure delete success: %s", key)
        return True

    def presigned_upload(
        self,
        key: str,
        *,
        content_type: str,
        expires_in: int = 3600,
    ) -> PresignedUpload:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        self._require_config()
        if not (self.account_name and self.account_key):
            raise StorageError(
                "Azure SAS generation needs AZURE_STORAGE_ACCOUNT_NAME and "
                "AZURE_STORAGE_ACCOUNT_KEY (a connection string alone is not enough).",
                provider=self.name,
                key=key,
                retryable=False,
            )

        try:
            token = generate_blob_sas(
                account_name=self.account_name,
                container_name=self.container,
                blob_name=key,
                account_key=self.account_key,
                permission=BlobSasPermissions(write=True, create=True),
                expiry=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            )
        except Exception as exc:
            logger.exception("Azure SAS generation failed for key %s: %s", key, exc)
            raise StorageError(
                "Failed to generate upload URL", provider=self.name, key=key
            ) from exc

        return PresignedUpload(
            url=f"{self.url_for(key)}?{token}",
            key=key,
            content_type=content_type,
            expires_in=expires_in,
            # Azure rejects a block-blob PUT without this header.
            headers={
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": content_type,
            },
            provider=self.name,
        )
