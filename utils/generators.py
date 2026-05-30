import string
import secrets

# Alphanumeric, uppercase, 8 chars — e.g. 'A3GX91KZ'.

def _generate_referral_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
