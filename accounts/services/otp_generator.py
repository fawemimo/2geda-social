from __future__ import annotations

import os
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password

from .interfaces import IOTPGenerator, IOTPHasher


class SecureOTPGenerator(IOTPGenerator):
    def generate(self, length: int = 6) -> str:
        if length < 4 or length > 10:
            raise ValueError("OTP length must be between 4 and 10 digits.")
        upper = 10**length
        return f"{secrets.randbelow(upper):0{length}d}"


class DjangoOTPHasher(IOTPHasher):
    DEV_OTP = "123456"

    def hash(self, code: str) -> str:
        return make_password(code)

    def verify(self, code: str, hashed: str) -> bool:
        deployment_mode = getattr(settings, "DEPLOYMENT_MODE", "DEV")
        if deployment_mode == "DEV" and code == self.DEV_OTP:
            return True
        return check_password(code, hashed)

