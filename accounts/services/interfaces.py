from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    to: str
    subject: str
    body: str
    template: str | None = None
    context: dict[str, Any] | None = None

# A transport that delivers a message to a single recipient.

class INotificationSender(ABC):

    @abstractmethod
    def send(self, payload: NotificationPayload) -> None: ...

# Generates an OTP code as a string of digits.

class IOTPGenerator(Protocol):

    def generate(self, length: int) -> str: ...

# Hashes/verifies an OTP code so plaintext never lives in the DB.

class IOTPHasher(Protocol):

    def hash(self, code: str) -> str: ...

    def verify(self, code: str, hashed: str) -> bool: ...

# Counts events against a key and reports when the limit is exceeded.

class IRateLimiter(ABC):

# Increment counter for `key`. Returns (allowed, current_count).
    @abstractmethod
    def hit(self, key: str, *, limit: int, window: timedelta) -> tuple[bool, int]:
        pass
    @abstractmethod
    def reset(self, key: str) -> None: ...

# Returns True if `key` is currently cooling down.
    @abstractmethod
    def cooldown(self, key: str, *, ttl: timedelta) -> bool:
        pass
    @abstractmethod
    def start_cooldown(self, key: str, *, ttl: timedelta) -> None: ...

# A short-lived cross-process lock — used to prevent OTP races.

class IDistributedLock(ABC):

    @abstractmethod
    def acquire(self, key: str, *, ttl: timedelta) -> bool: ...

    @abstractmethod
    def release(self, key: str) -> None: ...

# Issues, refreshes, and invalidates auth tokens for a user.

class ITokenManager(ABC):

    @abstractmethod
    def issue(self, user, *, device_id: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def refresh(self, refresh_token: str) -> dict[str, Any]: ...

    @abstractmethod
    def revoke(self, refresh_token: str) -> None: ...

    @abstractmethod
    def revoke_all_for_user(self, user) -> int: ...

