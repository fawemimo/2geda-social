from __future__ import annotations

import asyncio
import logging

from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


async def async_broadcast_to_group(group_name: str, payload: dict) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        await channel_layer.group_send(group_name, payload)
    except Exception:
        logger.exception("Failed to broadcast to group %s", group_name)


def sync_broadcast_to_group(group_name: str, payload: dict) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        coro = channel_layer.group_send(group_name, payload)
        asyncio.run(coro)
    except Exception:
        logger.exception("Failed to broadcast to group %s", group_name)


async def async_broadcast_post_event(post_id: str, event: dict) -> None:
    await async_broadcast_to_group(
        f"post_{post_id}",
        {"type": "post_event", **event},
    )


def broadcast_post_event(post_id: str, event: dict) -> None:
    sync_broadcast_to_group(
        f"post_{post_id}",
        {"type": "post_event", **event},
    )


def broadcast_feed_event(user_id: str, event: dict) -> None:
    sync_broadcast_to_group(
        f"user_{user_id}",
        {"type": "feed_event", **event},
    )


def broadcast_trending_event(event: dict) -> None:
    sync_broadcast_to_group(
        "trending_feed",
        {"type": "trending_event", **event},
    )


def broadcast_presence_event(user_id: str, event: dict) -> None:
    sync_broadcast_to_group(
        f"user_{user_id}",
        {"type": "presence_event", **event},
    )
