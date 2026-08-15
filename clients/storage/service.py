from __future__ import annotations

import logging
import os
from typing import Any

from clients.storage.base import (
    DEFAULT_CACHE_CONTROL,
    PresignedUpload,
    StorageProvider,
    StoredObject,
)
from clients.storage.classification import (
    build_key,
    classify,
    normalize_image,
    validate_file_size,
)
from clients.storage.registry import get_provider
from utils.enum import MediaType

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, provider: StorageProvider | None = None) -> None:
        self._provider = provider

    @property
    def provider(self) -> StorageProvider:
        if self._provider is None:
            self._provider = get_provider()
        return self._provider
    
    def build_key(self, media_type: str, ext: str) -> str:
        return build_key(media_type, ext)

    def url_for(self, key: str) -> str:
        return self.provider.url_for(key)

    def upload(self, file, *, ext: str | None = None) -> StoredObject:
        source_name = getattr(file, "name", "") or ""
        info = classify(ext if ext else source_name)
        media_type = info["media_type"]
        mime = info["mime"]

        validate_file_size(file, media_type)

        ext = os.path.splitext(source_name)[1].lower() or ext or ""
        upload_data = file
        content_type = mime
        key = build_key(media_type, ext)
        width = height = None

        if media_type == MediaType.IMAGE.value:
            normalized, fmt, norm_ext = normalize_image(file, ext)
            upload_data = normalized
            key = build_key(media_type, norm_ext)
            content_type = f"image/{fmt}"
            from PIL import Image

            with Image.open(file) as img:
                width, height = img.size
        else:
            file.seek(0)

        stored = self.provider.upload(upload_data, key, content_type=content_type)

        
        return StoredObject(
            key=stored.key,
            url=stored.url,
            content_type=stored.content_type or content_type,
            size_bytes=getattr(file, "size", 0) or 0,
            media_type=media_type,
            width=width,
            height=height,
            provider=stored.provider,
            raw=stored.raw,
        )

    def upload_to_key(
        self,
        fileobj,
        key: str,
        *,
        content_type: str,
        cache_control: str = DEFAULT_CACHE_CONTROL,
    ) -> StoredObject:
        return self.provider.upload(
            fileobj, key, content_type=content_type, cache_control=cache_control
        )

    def delete(self, key: str) -> bool:
        return self.provider.delete(key)

    def delete_url(self, file_url: str) -> bool:
        key = self.key_from_url(file_url)
        if not key:
            logger.warning("Could not derive a storage key from the given URL.")
            return False
        return self.delete(key)

    def key_from_url(self, file_url: str) -> str | None:
        if not file_url:
            return None
        for candidate in (file_url,):
            base = self.provider.url_for("")
            if candidate.startswith(base):
                return candidate[len(base):].lstrip("/")
        return None

    def presigned_upload(
        self, file_name: str, *, expires_in: int = 3600
    ) -> PresignedUpload:
        info = classify(file_name)
        ext = os.path.splitext(file_name)[1].lower()
        key = build_key(info["media_type"], ext)
        signed = self.provider.presigned_upload(
            key, content_type=info["mime"], expires_in=expires_in
        )
        return PresignedUpload(
            url=signed.url,
            key=signed.key,
            content_type=signed.content_type or info["mime"],
            media_type=info["media_type"],
            expires_in=signed.expires_in,
            headers=signed.headers,
            method=signed.method,
            provider=signed.provider,
        )
