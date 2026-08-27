from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    category: str
    value_type: str = "string"          # string | integer | boolean | json | csv
    default: Any = ""
    help_text: str = ""
    #: Secrets stay in the environment. Never stored, never editable.
    env_only: bool = False
    #: Restarting workers is required for the change to take effect.
    requires_restart: bool = False


CATEGORY_OTP = "OTP & Authentication"
CATEGORY_EMAIL = "Email"
CATEGORY_MESSAGING = "SMS & WhatsApp"
CATEGORY_STORAGE = "Media Storage"
CATEGORY_PAYMENTS = "Payments"
CATEGORY_MEDIA = "Media Processing"
CATEGORY_ADS = "Advertisements"
CATEGORY_INTEGRATIONS = "Third-party Integrations"


SPECS: tuple[SettingSpec, ...] = (
    # - OTP / auth 
    SettingSpec("OTP_CODE_LENGTH", CATEGORY_OTP, "integer", 6,
                "Number of digits in a one-time code."),
    SettingSpec("OTP_TTL_SECONDS", CATEGORY_OTP, "integer", 600,
                "How long a one-time code stays valid."),
    SettingSpec("OTP_MAX_ATTEMPTS", CATEGORY_OTP, "integer", 5,
                "Wrong guesses allowed before a code is burned."),
    SettingSpec("OTP_RESEND_COOLDOWN_SECONDS", CATEGORY_OTP, "integer", 60,
                "Minimum wait between resend requests."),
    SettingSpec("OTP_DAILY_QUOTA", CATEGORY_OTP, "integer", 20,
                "Maximum codes per identifier per day."),
    SettingSpec("PASSWORD_RESET_TTL_SECONDS", CATEGORY_OTP, "integer", 900,
                "Lifetime of a password-reset token."),
    SettingSpec("LOGIN_MAX_FAILED_ATTEMPTS", CATEGORY_OTP, "integer", 10,
                "Failed logins before an account is locked out."),
    SettingSpec("LOGIN_LOCKOUT_SECONDS", CATEGORY_OTP, "integer", 900,
                "How long a lockout lasts."),

    # - Email --
    SettingSpec("EMAIL_PROVIDER", CATEGORY_EMAIL, "string", "resend",
                "Transport for outbound mail: resend | ses | console | memory."),
    SettingSpec("EMAIL_SENDER", CATEGORY_EMAIL, "string", "",
                "From address used by every email provider."),
    SettingSpec("EMAIL_FROM_NAME", CATEGORY_EMAIL, "string", "2geda Social App",
                "Display name shown beside the sender address."),
    SettingSpec("RESEND_EMAIL_URL", CATEGORY_EMAIL, "string",
                "https://api.resend.com/emails", "Resend API endpoint."),
    SettingSpec("RESEND_TIMEOUT", CATEGORY_EMAIL, "integer", 15,
                "Seconds to wait on the Resend API."),
    SettingSpec("RESEND_API_KEY", CATEGORY_EMAIL, "string", "",
                "Resend API key.", env_only=True),
    SettingSpec("AWS_ACCESS_KEY_ID_SES", CATEGORY_EMAIL, "string", "",
                "SES access key.", env_only=True),
    SettingSpec("AWS_SECRET_ACCESS_KEY_SES", CATEGORY_EMAIL, "string", "",
                "SES secret key.", env_only=True),

    # - SMS / WhatsApp --
    SettingSpec("MESSAGING_PROVIDERS", CATEGORY_MESSAGING, "string",
                "twilio,termii,ebulksms",
                "Ordered failover chain. First entry is tried first."),
    SettingSpec("MESSAGING_PROVIDERS_SMS", CATEGORY_MESSAGING, "string", "",
                "Optional SMS-only chain. Blank inherits the default chain."),
    SettingSpec("MESSAGING_PROVIDERS_WHATSAPP", CATEGORY_MESSAGING, "string", "",
                "Optional WhatsApp-only chain. Blank inherits the default chain."),
    SettingSpec("MESSAGING_FAILOVER_COOLDOWN_SECONDS", CATEGORY_MESSAGING,
                "integer", 0,
                "Skip a provider for N seconds after it fails. 0 disables."),
    SettingSpec("DEFAULT_PHONE_COUNTRY_CODE", CATEGORY_MESSAGING, "string", "234",
                "Country code assumed for national-format numbers."),
    SettingSpec("TWILIO_FROM_NUMBER", CATEGORY_MESSAGING, "string", "",
                "Twilio SMS sender number in E.164."),
    SettingSpec("TWILIO_WHATSAPP_FROM", CATEGORY_MESSAGING, "string", "",
                "Twilio WhatsApp sender, e.g. whatsapp:+14155238886."),
    SettingSpec("TWILIO_TIMEOUT", CATEGORY_MESSAGING, "integer", 20),
    SettingSpec("TWILIO_ACCOUNT_SID", CATEGORY_MESSAGING, "string", "",
                "Twilio account SID.", env_only=True),
    SettingSpec("TWILIO_AUTH_TOKEN", CATEGORY_MESSAGING, "string", "",
                "Twilio auth token.", env_only=True),
    SettingSpec("TERMII_SENDER_ID", CATEGORY_MESSAGING, "string", "2geda"),
    SettingSpec("TERMII_BASE_URL", CATEGORY_MESSAGING, "string",
                "https://api.ng.termii.com"),
    SettingSpec("TERMII_TIMEOUT", CATEGORY_MESSAGING, "integer", 20),
    SettingSpec("TERMII_API_KEY", CATEGORY_MESSAGING, "string", "",
                "Termii API key.", env_only=True),
    SettingSpec("EBULKSMS_SENDER_ID", CATEGORY_MESSAGING, "string", "2Geda"),
    SettingSpec("EBULKSMS_BASEURL", CATEGORY_MESSAGING, "string",
                "https://api.ebulksms.com"),
    SettingSpec("EBULKSMS_WHATSAPP_URL", CATEGORY_MESSAGING, "string", "",
                "Set to enable EBulkSMS WhatsApp delivery."),
    SettingSpec("EBULKSMS_TIMEOUT", CATEGORY_MESSAGING, "integer", 20),
    SettingSpec("EBULKSMS_USERNAME", CATEGORY_MESSAGING, "string", "",
                "EBulkSMS username.", env_only=True),
    SettingSpec("EBULKSMS_APIKEY", CATEGORY_MESSAGING, "string", "",
                "EBulkSMS API key.", env_only=True),

    # - Storage 
    SettingSpec("STORAGE_PROVIDER", CATEGORY_STORAGE, "string", "s3",
                "Backend that owns uploaded files: s3 | azure | memory.",
                requires_restart=False),
    SettingSpec("AWS_S3_REGION_NAME", CATEGORY_STORAGE, "string", "us-east-1"),
    SettingSpec("AWS_STORAGE_BUCKET_NAME", CATEGORY_STORAGE, "string", ""),
    SettingSpec("AWS_S3_CUSTOM_DOMAIN", CATEGORY_STORAGE, "string", "",
                "CDN in front of the bucket. Blank derives it from bucket+region."),
    SettingSpec("AZURE_STORAGE_CONTAINER", CATEGORY_STORAGE, "string", "media"),
    SettingSpec("AZURE_STORAGE_CUSTOM_DOMAIN", CATEGORY_STORAGE, "string", ""),
    SettingSpec("AZURE_STORAGE_ACCOUNT_NAME", CATEGORY_STORAGE, "string", ""),
    SettingSpec("AWS_ACCESS_KEY_ID", CATEGORY_STORAGE, "string", "",
                "S3 access key.", env_only=True),
    SettingSpec("AWS_SECRET_ACCESS_KEY", CATEGORY_STORAGE, "string", "",
                "S3 secret key.", env_only=True),
    SettingSpec("AZURE_STORAGE_ACCOUNT_KEY", CATEGORY_STORAGE, "string", "",
                "Azure account key.", env_only=True),
    SettingSpec("AZURE_STORAGE_CONNECTION_STRING", CATEGORY_STORAGE, "string", "",
                "Azure connection string.", env_only=True),

    # - Payments --
    SettingSpec("PAYMENT_PROVIDER", CATEGORY_PAYMENTS, "string", "paystack",
                "Live gateway: paystack | flutterwave | memory. Only one at a time."),
    SettingSpec("PAYSTACK_CALLBACK_URL", CATEGORY_PAYMENTS, "string", ""),
    SettingSpec("PAYSTACK_PUBLIC_KEY", CATEGORY_PAYMENTS, "string", "",
                "Publishable key — safe to expose to clients."),
    SettingSpec("FLUTTERWAVE_CALLBACK_URL", CATEGORY_PAYMENTS, "string", ""),
    SettingSpec("FLUTTERWAVE_PUBLIC_KEY", CATEGORY_PAYMENTS, "string", "",
                "Publishable key — safe to expose to clients."),
    SettingSpec("PAYSTACK_SECRET_KEY", CATEGORY_PAYMENTS, "string", "",
                "Paystack secret key.", env_only=True),
    SettingSpec("FLUTTERWAVE_SECRET_KEY", CATEGORY_PAYMENTS, "string", "",
                "Flutterwave secret key.", env_only=True),
    SettingSpec("FLUTTERWAVE_SECRET_HASH", CATEGORY_PAYMENTS, "string", "",
                "Flutterwave webhook secret hash.", env_only=True),

    #  Media processing 
    SettingSpec("MEDIA_MAX_UPLOAD_BYTES", CATEGORY_MEDIA, "integer", 8 * 1024 * 1024,
                "Largest profile image accepted, in bytes."),
    SettingSpec("MEDIA_AVATAR_MAX_EDGE", CATEGORY_MEDIA, "integer", 512,
                "Longest edge for avatars and display photos."),
    SettingSpec("MEDIA_COVER_MAX_EDGE", CATEGORY_MEDIA, "integer", 1600,
                "Longest edge for cover photos."),
    SettingSpec("MEDIA_STAGING_TTL_SECONDS", CATEGORY_MEDIA, "integer", 1800,
                "How long staged upload bytes survive in Redis."),

    # - Advertisements 
    SettingSpec("ADS_MAX_CREATIVES", CATEGORY_ADS, "integer", 10,
                "Images allowed on one advert."),
    SettingSpec("ADS_DEFAULT_PRIORITY", CATEGORY_ADS, "integer", 5,
                "Priority applied to a new advert."),
    SettingSpec("ADS_SERVE_LIMIT_MAX", CATEGORY_ADS, "integer", 5,
                "Most adverts one serve request may return."),

    # - Integrations 
    SettingSpec("GOOGLE_MAPS_GEOCODE_URL", CATEGORY_INTEGRATIONS, "string",
                "https://maps.googleapis.com/maps/api/geocode/json"),
    SettingSpec("GOOGLE_MAPS_API_KEY", CATEGORY_INTEGRATIONS, "string", "",
                "Google Maps API key.", env_only=True),
    SettingSpec("FIREBASE_PROJECT_ID", CATEGORY_INTEGRATIONS, "string", ""),
)

REGISTRY: dict[str, SettingSpec] = {spec.key: spec for spec in SPECS}

CATEGORIES: tuple[str, ...] = (
    CATEGORY_OTP, CATEGORY_EMAIL, CATEGORY_MESSAGING, CATEGORY_STORAGE,
    CATEGORY_PAYMENTS, CATEGORY_MEDIA, CATEGORY_ADS, CATEGORY_INTEGRATIONS,
)

VALUE_TYPES: tuple[tuple[str, str], ...] = (
    ("string", "String"),
    ("integer", "Integer"),
    ("boolean", "Boolean"),
    ("json", "JSON"),
    ("csv", "Comma-separated list"),
)


def spec_for(key: str) -> SettingSpec | None:
    return REGISTRY.get(key)


def manageable_specs() -> list[SettingSpec]:
    """Specs an operator may actually store in the database."""
    return [spec for spec in SPECS if not spec.env_only]
