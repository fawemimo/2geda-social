from __future__ import annotations

import logging

from clients.storage.base import (
    DEFAULT_CACHE_CONTROL,
    PresignedUpload,
    StorageError,
    StorageProvider,
    StoredObject,
)

logger = logging.getLogger(__name__)


class MemoryProvider(StorageProvider):
    name = "memory"

    def __init__(self, *, base_url: str = "https://memory.test") -> None:
        self.objects: dict[str, dict] = {}
        self.base_url = base_url.rstrip("/")

    def url_for(self, key: str) -> str:
        return f"{self.base_url}/{key}"

    def upload(
        self,
        fileobj,
        key: str,
        *,
        content_type: str,
        cache_control: str = DEFAULT_CACHE_CONTROL,
    ) -> StoredObject:
        data = fileobj.read() if hasattr(fileobj, "read") else bytes(fileobj)
        self.objects[key] = {
            "data": data,
            "content_type": content_type,
            "cache_control": cache_control,
        }
        return StoredObject(
            key=key,
            url=self.url_for(key),
            content_type=content_type,
            size_bytes=len(data),
            provider=self.name,
        )

    def delete(self, key: str) -> bool:
        if not key:
            return False
        self.objects.pop(key, None)  # absent == already deleted
        return True

    def presigned_upload(
        self, key: str, *, content_type: str, expires_in: int = 3600
    ) -> PresignedUpload:
        return PresignedUpload(
            url=f"{self.url_for(key)}?signature=test",
            key=key,
            content_type=content_type,
            expires_in=expires_in,
            headers={"Content-Type": content_type},
            provider=self.name,
        )

    def clear(self) -> None:
        self.objects.clear()


class FailingProvider(StorageProvider):
    """Always raises. Lets tests exercise the failure contract."""

    name = "failing"

    def __init__(self, *, detail: str = "forced failure") -> None:
        self.detail = detail

    def url_for(self, key: str) -> str:
        return f"https://failing.test/{key}"

    def upload(self, fileobj, key: str, *, content_type: str, **kwargs) -> StoredObject:
        raise StorageError(self.detail, provider=self.name, key=key)

    def delete(self, key: str) -> bool:
        return False
