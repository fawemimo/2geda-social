from __future__ import annotations

import asyncio
import logging

from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

POLL_GROUP_TPL = "poll_{poll_id}"


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


def broadcast_poll_event(poll_id: str, event: dict) -> None:
    sync_broadcast_to_group(
        POLL_GROUP_TPL.format(poll_id=poll_id),
        {"type": "poll_event", **event},
    )


async def async_broadcast_poll_event(poll_id: str, event: dict) -> None:
    await async_broadcast_to_group(
        POLL_GROUP_TPL.format(poll_id=poll_id),
        {"type": "poll_event", **event},
    )
