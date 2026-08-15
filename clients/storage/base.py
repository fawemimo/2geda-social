from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

DEFAULT_CACHE_CONTROL = "public, max-age=31536000, immutable"


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    url: str
    content_type: str = ""
    size_bytes: int = 0
    media_type: str = ""
    width: int | None = None
    height: int | None = None
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "url": self.url,
            "content_type": self.content_type,
            "file_size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class PresignedUpload:

    url: str
    key: str
    content_type: str = ""
    media_type: str = ""
    expires_in: int = 3600
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "PUT"
    provider: str = ""


class StorageError(RuntimeError):

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        key: str | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.key = key
        self.retryable = retryable


class StorageNotConfigured(StorageError):
    def __init__(self, provider: str, detail: str = "") -> None:
        super().__init__(
            f"Storage provider {provider!r} is not configured. {detail}".strip(),
            provider=provider,
            retryable=False,
        )


class StorageProvider(ABC):
    name: ClassVar[str] = "base"

    def is_configured(self) -> bool:
        return True

    @abstractmethod
    def upload(
        self,
        fileobj,
        key: str,
        *,
        content_type: str,
        cache_control: str = DEFAULT_CACHE_CONTROL,
    ) -> StoredObject:
        """Upload `fileobj` to `key`. Returns StoredObject or raises StorageError."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove `key`. Idempotent — a missing object is a successful delete."""

    @abstractmethod
    def url_for(self, key: str) -> str:
        """Public URL for `key`. Pure; never performs I/O."""

    def presigned_upload(
        self,
        key: str,
        *,
        content_type: str,
        expires_in: int = 3600,
    ) -> PresignedUpload:
        raise StorageError(
            f"{self.name} does not support presigned uploads.",
            provider=self.name,
            key=key,
            retryable=False,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name!r}>"
