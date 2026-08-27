from __future__ import annotations

import os
import re

#: Country calling code assumed for national-format numbers (Nigeria).
def _default_country_code() -> str:
    """Read per call so an admin change takes effect without a restart."""
    from config import get_str

    return str(get_str("DEFAULT_PHONE_COUNTRY_CODE", "234")).lstrip("+") or "234"

# E.164 allows at most 15 digits.
_MAX_DIGITS = 15
_MIN_DIGITS = 7


class InvalidPhoneNumber(ValueError):
    pass


def normalize(phone: str, *, country_code: str | None = None) -> str:
    """Return `phone` in E.164 (`+<digits>`), or raise InvalidPhoneNumber."""
    if not phone or not str(phone).strip():
        raise InvalidPhoneNumber("Phone number is empty.")

    raw = str(phone).strip()
    # Remember whether the caller gave an explicit international marker before
    # stripping punctuation.
    explicit_intl = raw.startswith("+") or raw.startswith("00")

    digits = re.sub(r"\D", "", raw)
    if not digits:
        raise InvalidPhoneNumber(f"No digits in phone number: {phone!r}")

    cc = (country_code or _default_country_code()).lstrip("+")

    if explicit_intl:
        # "00234..." is the international prefix form of "+234...".
        if raw.startswith("00"):
            digits = digits[2:]
    elif digits.startswith("0"):
        # National format: drop the trunk 0, prepend the country code.
        digits = cc + digits[1:]
    elif not digits.startswith(cc):
        # Bare subscriber number with no trunk prefix.
        digits = cc + digits

    if not (_MIN_DIGITS <= len(digits) <= _MAX_DIGITS):
        raise InvalidPhoneNumber(
            f"{phone!r} normalises to {len(digits)} digits, outside E.164 range."
        )

    return f"+{digits}"


def to_national_digits(e164: str) -> str:
    return e164.lstrip("+")


def to_whatsapp(e164: str) -> str:
    return e164 if e164.startswith("whatsapp:") else f"whatsapp:{e164}"
