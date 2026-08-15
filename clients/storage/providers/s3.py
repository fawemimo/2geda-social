from __future__ import annotations

import logging
import os

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


class S3Provider(StorageProvider):

    name = "s3"

    def __init__(
        self,
        *,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        bucket: str | None = None,
        region: str | None = None,
        custom_domain: str | None = None,
        client=None,
    ) -> None:
        self.access_key_id = _resolve(access_key_id, "AWS_ACCESS_KEY_ID")
        self.secret_access_key = _resolve(secret_access_key, "AWS_SECRET_ACCESS_KEY")
        self.bucket = _resolve(bucket, "AWS_STORAGE_BUCKET_NAME")
        self.region = _resolve(region, "AWS_S3_REGION_NAME", "us-east-1")
        self._custom_domain = _resolve(custom_domain, "AWS_S3_CUSTOM_DOMAIN")
        self._client = client

    @property
    def custom_domain(self) -> str:
        return (
            self._custom_domain
            or f"https://{self.bucket}.s3.{self.region}.amazonaws.com"
        ).rstrip("/")

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name=self.region,
            )
        return self._client

    def is_configured(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key and self.bucket)

    def _require_config(self) -> None:
        if not self.is_configured():
            raise StorageNotConfigured(
                self.name, "AWS credentials or bucket name missing."
            )
        
    def url_for(self, key: str) -> str:
        return f"{self.custom_domain}/{key}"

    def upload(
        self,
        fileobj,
        key: str,
        *,
        content_type: str,
        cache_control: str = DEFAULT_CACHE_CONTROL,
    ) -> StoredObject:
        from botocore.exceptions import BotoCoreError, ClientError

        self._require_config()
        try:
            self.client.upload_fileobj(
                fileobj,
                self.bucket,
                key,
                ExtraArgs={
                    "ContentType": content_type,
                    "ContentDisposition": "inline",
                    "CacheControl": cache_control,
                },
            )
        except (ClientError, BotoCoreError) as exc:
            logger.exception("S3 upload failed for key %s: %s", key, exc)
            raise StorageError(
                f"S3 upload failed: {exc}", provider=self.name, key=key
            ) from exc

        return StoredObject(
            key=key,
            url=self.url_for(key),
            content_type=content_type,
            provider=self.name,
        )

    def delete(self, key: str) -> bool:
        if not key:
            return False
        self._require_config()
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            logger.exception("S3 delete failed for key %s: %s", key, exc)
            return False
        logger.info("S3 delete success: %s", key)
        return True

    def presigned_upload(
        self,
        key: str,
        *,
        content_type: str,
        expires_in: int = 3600,
    ) -> PresignedUpload:
        from botocore.exceptions import BotoCoreError, ClientError

        self._require_config()
        try:
            url = self.client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.exception("Failed to generate presigned URL: %s", exc)
            raise StorageError(
                "Failed to generate upload URL", provider=self.name, key=key
            ) from exc

        return PresignedUpload(
            url=url,
            key=key,
            content_type=content_type,
            expires_in=expires_in,
            headers={"Content-Type": content_type},
            provider=self.name,
        )
