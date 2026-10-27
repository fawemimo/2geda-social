import hashlib
import hmac
import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone as dt_timezone
from django.conf import settings

_context: ContextVar[dict] = ContextVar("log_context", default={})


def bind(**fields):
    current = dict(_context.get())
    current.update({k: v for k, v in fields.items() if v is not None})
    return _context.set(current)


def unbind(token):
    try:
        _context.reset(token)
    except (ValueError, LookupError):
        _context.set({})


def get_context():
    return dict(_context.get())


def new_request_id():
    return uuid.uuid4().hex


def get_request_id():
    return _context.get().get("request_id")


def ref(value, prefix="ref"):
    if value in (None, ""):
        return None
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        str(value).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{prefix}_{digest[:12]}"


def account_ref(account_number):
    return ref(account_number, prefix="acct")


def user_ref(user):
    if user is None:
        return None
    user_id = getattr(user, "id", user)
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "pin",
    "otp",
    "token",
    "secret",
    "authorization",
    "auth",
    "credential",
    "signature",
    "apikey",
    "api_key",
    "private",
    "bvn",
    "nin",
    "email",
    "phone",
    "msisdn",
    "mobile",
    "account_number",
    "accountnumber",
    "accountno",
    "acctno",
    "nuban",
    "card",
    "pan",
    "cvv",
    "cvc",
    "expiry",
    "dob",
    "date_of_birth",
    "first_name",
    "last_name",
    "middle_name",
    "fullname",
    "full_name",
    "customer_name",
    "customername",
    "account_name",
    "accountname",
    "receiver_name",
    "receivername",
    "sender_name",
    "sendername",
    "firstname",
    "lastname",
    "middlename",
    "surname",
    "othername",
    "address",
    "street",
    "postal",
    "selfie",
    "image",
    "base64",
    "document",
    "signature_url",
    "login_pin",
    "otp_code",
    "password",
    "transaction_pin",
    "login_pin",
    "pin",
    "re_password",
    "old_pin",
    "new_pin",
    "old_password",
    "new_password",
    "new_login_pin",
    "access_token",
    "refresh_token",
    "csrfmiddlewaretoken",
    "accessToken",
    "expiresIn",
    "profile_image",
    "front_id_url",
    "back_id_url",
    "bill_proof_url",
    "user_signature_url",
    "address_base64",
    "id_image",
    "selfie_image",
    "liveness_image1",
    "liveness_image2",
    "liveness_image3",
    "liveness_image4",
    "liveness_image5",
    "liveness_image6",
    "liveness_image7",
    "cac_doc_image",
    "bill_image",
)


SAFE_KEY_EXACT = {
    "bank_name",
    "biller_name",
    "institution_name",
    "event_name",
    "task_name",
    "template_name",
    "field_name",
    "file_name",
    "filename",
    "account_type",
    "card_type",
    "phone_verified",
    "email_verified",
    "has_pin",
    "pin_set",
    "auth_type",
    "token_type",
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_DIGITS = re.compile(r"\b\d{10,19}\b")
_NG_PHONE = re.compile(r"\b(?:\+?234|0)[789]\d{9}\b")

REDACTED = "[redacted]"
MAX_STRING = 512
MAX_ITEMS = 50


def _is_sensitive_key(key):
    lowered = str(key).lower()
    if lowered in SAFE_KEY_EXACT:
        return False
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def scrub_text(text):
    if not isinstance(text, str):
        return text
    text = _EMAIL.sub(REDACTED, text)
    text = _NG_PHONE.sub(REDACTED, text)
    text = _LONG_DIGITS.sub(REDACTED, text)
    return text


def redact(value, _depth=0):
    if _depth > 6:
        return "[truncated: too deep]"

    if isinstance(value, dict):
        cleaned = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                cleaned["..."] = f"[{len(value) - MAX_ITEMS} more keys]"
                break
            cleaned[key] = (
                REDACTED if _is_sensitive_key(key) else redact(item, _depth + 1)
            )
        return cleaned

    if isinstance(value, (list, tuple)):
        items = [redact(v, _depth + 1) for v in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"[{len(value) - MAX_ITEMS} more items]")
        return items

    if isinstance(value, str):
        scrubbed = scrub_text(value)
        if len(scrubbed) > MAX_STRING:
            return scrubbed[:MAX_STRING] + f"...[{len(scrubbed)} chars]"
        return scrubbed

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return scrub_text(str(value))[:MAX_STRING]


_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class ContextFilter(logging.Filter):

    def filter(self, record):
        for key, value in _context.get().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, service=None, environment=None):
        super().__init__()
        self.service = service or getattr(settings, "SERVICE_NAME", "eldorado-api")
        self.environment = environment or getattr(settings, "ENV", "DEV")

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=dt_timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service,
            "env": self.environment,
            "message": scrub_text(record.getMessage())[:MAX_STRING],
            "source": f"{record.module}.{record.funcName}:{record.lineno}",
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = REDACTED if _is_sensitive_key(key) else redact(value)

        if record.exc_info:
            exc_type, exc_value, _tb = record.exc_info
            payload["error"] = {
                "type": getattr(exc_type, "__name__", str(exc_type)),
                "message": scrub_text(str(exc_value))[:MAX_STRING],
                "stack": scrub_text(self.formatException(record.exc_info))[-4000:],
            }

        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)[-2000:]

        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):

    def format(self, record):
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} "
            f"{record.levelname:<8} {record.name} "
            f"{scrub_text(record.getMessage())}"
        )
        context = {
            key: redact(value)
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        }
        request_id = context.pop("request_id", None)
        if request_id:
            base = f"[{str(request_id)[:8]}] {base}"
        if context:
            base += " | " + " ".join(f"{k}={v}" for k, v in context.items())
        if record.exc_info:
            base += "\n" + scrub_text(self.formatException(record.exc_info))
        return base
