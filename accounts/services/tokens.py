from __future__ import annotations

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from accounts.models import User

from .exceptions import AuthenticationError
from .interfaces import ITokenManager
from typing import Any

# Concrete ITokenManager backed by SimpleJWT.

class JWTTokenService(ITokenManager):

    def issue(self, user: User, *, device_id: str | None = None) -> dict[str, Any]:
        if not user.is_active:
            raise AuthenticationError("Inactive users cannot receive tokens.")
        refresh = RefreshToken.for_user(user)
        if device_id:
            refresh["device_id"] = str(device_id)
        return {
            "access": str(refresh.access_token),
            "access_expires_at": refresh.access_token.payload.get("exp"),
            "refresh": str(refresh),
            "refresh_expires_at": refresh.payload.get("exp"),
            "token_type": "Bearer",
        }

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        try:
            token = RefreshToken(refresh_token)
            token.verify()
            token.blacklist()
            user_id = token["user_id"]
            user = User.objects.only("id", "is_active").get(pk=user_id)
        except TokenError as exc:
            raise AuthenticationError("Invalid or expired refresh token.") from exc
        except User.DoesNotExist as exc:
            raise AuthenticationError("User no longer exists.") from exc

        device_id = token.payload.get("device_id")
        return self.issue(user, device_id=device_id)

    def revoke(self, refresh_token: str) -> None:
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError as exc:
            raise AuthenticationError("Invalid refresh token.") from exc
# Blacklist every outstanding refresh token for this user.

    def revoke_all_for_user(self, user: User) -> int:
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        outstanding = OutstandingToken.objects.filter(user=user)
        count = 0
        for token in outstanding.iterator(chunk_size=500):
            _, created = BlacklistedToken.objects.get_or_create(token=token)
            if created:
                count += 1
        return count


# Alias kept for readability in service code.
TokenService = JWTTokenService

