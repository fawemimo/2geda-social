import string
import secrets
import uuid

# Alphanumeric, uppercase, 8 chars — e.g. 'A3GX91KZ'.

def _generate_referral_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_ticket_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "TKT-" + "".join(secrets.choice(alphabet) for _ in range(length))


def generate_event_link() -> str:
    return secrets.token_urlsafe(16)


def generate_transaction_reference() -> str:
    return "REF-" + str(uuid.uuid4()).replace("-", "").upper()[:20]


def generate_payout_reference() -> str:
    return "PO-" + secrets.token_hex(8).upper()
