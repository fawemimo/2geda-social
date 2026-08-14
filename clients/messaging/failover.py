from __future__ import annotations
import logging
from typing import Iterable, Sequence

from clients.messaging.base import (
    AllProvidersFailed,
    Channel,
    ChannelNotSupported,
    Message,
    MessagingError,
    MessagingProvider,
    SendResult,
)

logger = logging.getLogger(__name__)

COOLDOWN_KEY = "messaging:cooldown:{provider}"


class FailoverProvider(MessagingProvider):

    name = "failover"

    def __init__(
        self,
        providers: Sequence[MessagingProvider],
        *,
        cooldown_seconds: int = 0,
    ) -> None:
        if not providers:
            raise ValueError("FailoverProvider requires at least one provider.")
        self.providers = tuple(providers)
        self.cooldown_seconds = cooldown_seconds

    @property
    def channels(self) -> frozenset[Channel]:  # type: ignore[override]
        """Union of the chain — the chain can serve whatever any member can."""
        return frozenset().union(*(p.channels for p in self.providers))

    def is_configured(self) -> bool:
        return any(p.is_configured() for p in self.providers)

    def _in_cooldown(self, provider: MessagingProvider) -> bool:
        if not self.cooldown_seconds:
            return False
        from django.core.cache import cache

        return bool(cache.get(COOLDOWN_KEY.format(provider=provider.name)))

    def _start_cooldown(self, provider: MessagingProvider) -> None:
        if not self.cooldown_seconds:
            return
        from django.core.cache import cache

        cache.set(
            COOLDOWN_KEY.format(provider=provider.name), 1, self.cooldown_seconds
        )

    def candidates(self, channel: Channel) -> list[MessagingProvider]:
        eligible = [
            p for p in self.providers if p.supports(channel) and p.is_configured()
        ]
        # A provider in cooldown is deprioritised, not dropped — if every
        # provider is cooling down we still try rather than fail outright.
        hot = [p for p in eligible if not self._in_cooldown(p)]
        cold = [p for p in eligible if self._in_cooldown(p)]
        return hot + cold

    def send(self, message: Message) -> SendResult:
        chain = self.candidates(message.channel)
        if not chain:
            raise ChannelNotSupported(self.name, message.channel)

        failures: dict[str, str] = {}
        attempted: list[str] = []

        for provider in chain:
            try:
                result = provider.send(message)
            except MessagingError as exc:
                failures[provider.name] = str(exc)
                attempted.append(provider.name)
                self._start_cooldown(provider)

                if not exc.retryable:
                    # Permanent fault — another vendor will fail the same way.
                    logger.warning(
                        "Messaging %s failed permanently on %s; not failing over",
                        message.channel, provider.name,
                    )
                    raise

                logger.warning(
                    "Messaging %s failed on %s, failing over: %s",
                    message.channel, provider.name, exc,
                )
                continue
            except Exception as exc:  # defensive: contract says this cannot happen
                failures[provider.name] = f"unexpected: {exc}"
                attempted.append(provider.name)
                logger.exception(
                    "Provider %s raised a non-MessagingError; treating as retryable",
                    provider.name,
                )
                continue

            if attempted:
                logger.info(
                    "Messaging %s delivered by %s after %s failed",
                    message.channel, provider.name, ", ".join(attempted),
                )
            # Record who was tried first so callers can see the failover happened.
            return SendResult(
                message_id=result.message_id,
                provider=result.provider,
                channel=result.channel,
                raw=result.raw,
                attempts=tuple(attempted),
            )

        raise AllProvidersFailed(message.channel, failures)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        names = " -> ".join(p.name for p in self.providers)
        return f"<FailoverProvider [{names}]>"


def build_chain(
    providers: Iterable[MessagingProvider], *, cooldown_seconds: int = 0
) -> MessagingProvider:
    chain = list(providers)
    if len(chain) == 1:
        return chain[0]
    return FailoverProvider(chain, cooldown_seconds=cooldown_seconds)
