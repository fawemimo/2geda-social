from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import httpx
import jwt

logger = logging.getLogger(__name__)


class AppleVoIPPushAPI:
    """Send VoIP notifications directly to APNs using token based auth."""

    @staticmethod
    def send(token: str, data: dict) -> bool:
        key_id = os.getenv("APNS_KEY_ID", "49FBCQ6KA4")
        team_id = os.getenv("APNS_TEAM_ID", "RA93FW7557")
        key_path = os.getenv(
            "APNS_AUTH_KEY_PATH","/AuthKey_49FBCQ6KA4.p8",
        )
        topic = os.getenv("APNS_VOIP_TOPIC", "com.techcity.togeda.voip")
        if not (key_id and team_id and key_path and Path(key_path).is_file()):
            logger.error("APNs VoIP is not configured (APNS_KEY_ID, APNS_TEAM_ID, APNS_AUTH_KEY_PATH)")
            return False

        try:            
            private_key = Path(key_path).read_text()
            bearer = jwt.encode(
                {"iss": team_id, "iat": int(time.time())}, private_key,
                algorithm="ES256", headers={"kid": key_id},
            )
            host = "https://api.push.apple.com"
            with httpx.Client(http2=True, timeout=10) as client:
                response = client.post(
                    f"{host}/3/device/{token}",
                    headers={
                        "authorization": f"bearer {bearer}",
                        "apns-topic": topic,
                        "apns-push-type": "voip",
                        "apns-priority": "10",
                        "apns-expiration": str(int(time.time()) + 40),
                    },
                    json={"aps": {"content-available": 1}, **data},
                )
            if response.status_code != 200:
                logger.warning("APNs VoIP push rejected: status=%s response=%s", response.status_code, response.text)
                return False
            return True
        except Exception:
            logger.exception("Failed to send APNs VoIP push")
            return False
