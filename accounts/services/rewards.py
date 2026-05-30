from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone
from accounts.models import PointsRewarding
logger = logging.getLogger(__name__)

# Reward a user for a given action. Returns reward info or None if action is not mapped.

def reward_user(
    *,
    user,
    points: int,
    action: str,
    source,
    auto_claim: bool = True,
) -> dict[str, Any] | None:

    reward = PointsRewarding(
        user=user,
        points=points,
        reason=action,
        source=source,
        is_claimed=auto_claim,
        claimed_at=timezone.now() if auto_claim else None,
    )
    reward.save()

    from accounts.tasks import send_user_push_notification

    push_body = (
        f"You earned {points} points for {action}!"
    )
    send_user_push_notification.delay(
        user_id=str(user.pk),
        title="Points Earned \u2728",
        body=push_body,
        data={
            "type": "points_reward"
        },
    )

    return {
        "reward_id": str(reward.pk),
        "points": points,
        "action": action,
    }

