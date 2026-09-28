from __future__ import annotations

from enum import Enum


class SearchType(Enum):

    USERS = "users"
    POSTS = "posts"
    COMMENTS = "comments"
    MEDIA = "media"
    COLLECTIONS = "collections"

    @classmethod
    def values(cls) -> list[str]:
        return [member.value for member in cls]

    @classmethod
    def from_value(cls, value: str) -> SearchType:
        return cls(value)

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(status.value, status.value.replace("_", " ").title()) for status in cls]
