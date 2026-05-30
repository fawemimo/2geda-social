from __future__ import annotations

import secrets

from django.contrib.auth.hashers import check_password, make_password

from .interfaces import IOTPGenerator, IOTPHasher


class SecureOTPGenerator(IOTPGenerator):
    def generate(self, length: int = 6) -> str:
        if length < 4 or length > 10:
            raise ValueError("OTP length must be between 4 and 10 digits.")
        upper = 10**length
        return f"{secrets.randbelow(upper):0{length}d}"


class DjangoOTPHasher(IOTPHasher):
    def hash(self, code: str) -> str:
        return make_password(code)

    def verify(self, code: str, hashed: str) -> bool:
        return check_password(code, hashed)

