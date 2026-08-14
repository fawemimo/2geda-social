import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from celery.schedules import crontab
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

load_dotenv()

DEBUG = os.getenv("DEBUG")

SECRET_KEY = os.getenv("SECRET_KEY")

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS").split(",")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", default="localhost"),
        "PORT": os.getenv("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

PORT = 8000

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

REST_FRAMEWORK = {
    # for exceptions handling
    "EXCEPTION_HANDLER": "utils.exceptions.custom_exception_handler",
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.parsers.MultiPartParser",
        "utils.renderers.LocalTimezoneJSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        # "rest_framework_xml.parsers.XMLParser",
    ),
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "COERCE_DECIMAL_TO_STRING": False,
    "DEFAULT_PAGINATION_CLASS": "utils.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    # "DEFAULT_SCHEMA_CLASS": "rest_framework.schemas.coreapi.AutoSchema",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": (
        "accounts.throttles.BurstAnonThrottle",
        "accounts.throttles.SustainedAnonThrottle",
        "accounts.throttles.BurstUserThrottle",
        "accounts.throttles.SustainedUserThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon_burst": "60/minute",
        "anon_sustained": "1000/day",
        "user_burst": "240/minute",
        "user_sustained": "20000/day",
        "otp_request": "5/minute",
        "otp_verify": "10/minute",
        "login": "10/minute",
        "registration": "5/minute",
        "post_create": "3/minute",
    },
}

CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL"
)

CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_HEARTBEAT = 30
CELERY_BROKER_POOL_LIMIT = 20
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "confirm_publish": True,
    "max_retries": 5,
    "interval_start": 0.1,
    "interval_step": 0.5,
    "interval_max": 5.0,
}
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Africa/Lagos"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 5
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 4
CELERY_BEAT_SCHEDULE = {
    "purge-expired-otps-every-hour": {
        "task": "accounts.tasks.purge_expired_otps",
        "schedule": crontab(minute=0),
    },
    "hard-delete-expired-displays-every-15-minutes": {
        "task": "displays.tasks.hard_delete_expired_displays",
        "schedule": crontab(minute="*/15"),
    },
    "close-expired-polls-every-5-minutes": {
        "task": "polls.tasks.close_expired_polls",
        "schedule": crontab(minute="*/5"),
    },
    "release-expired-ticket-reservations-every-5-minutes": {
        "task": "tickets.tasks.release_expired_reservations",
        "schedule": crontab(minute="*/5"),
    },
}

# Account / OTP tuning knobs — overridable via env without touching code.
OTP_CODE_LENGTH = int(os.getenv("OTP_CODE_LENGTH", "6"))
OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "600"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60"))
OTP_DAILY_QUOTA = int(os.getenv("OTP_DAILY_QUOTA", "20"))
PASSWORD_RESET_TTL_SECONDS = int(os.getenv("PASSWORD_RESET_TTL_SECONDS", "900"))
LOGIN_MAX_FAILED_ATTEMPTS = int(os.getenv("LOGIN_MAX_FAILED_ATTEMPTS", "10"))
LOGIN_LOCKOUT_SECONDS = int(os.getenv("LOGIN_LOCKOUT_SECONDS", "900"))

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_CALLBACK_URL = os.getenv("PAYSTACK_CALLBACK_URL", "")

AUTH_USER_MODEL = "accounts.User"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": os.getenv("SECRET_KEY"),
    "VERIFYING_KEY": None,
    "AUTH_HEADERS_TYPES": ("JWT",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "accounts.serializers.UserTokenObtainPairSerializer",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "2geda Social API",
    "DESCRIPTION": "2geda Social API Documentation",
    "VERSION": "v2",
    "SERVE_INCLUDE_SCHEMA": False,
    # OTHER SETTINGS
}


# CORS_ALLOWED_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS").split(",")
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS").split(",")

CORS_ALLOW_HEADERS = (
    "accept",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
)


EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = 465  # Use 587 for TLS, or 465 for SSL
EMAIL_USE_SSL = True
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL")
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL')
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "resend")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")

# SMS / WhatsApp transport chain for clients.messaging.
# Ordered — a retryable failure fails over to the next provider immediately.
MESSAGING_PROVIDERS = os.getenv("MESSAGING_PROVIDERS", "twilio,termii,ebulksms")
MESSAGING_PROVIDERS_SMS = os.getenv("MESSAGING_PROVIDERS_SMS", "")
MESSAGING_PROVIDERS_WHATSAPP = os.getenv("MESSAGING_PROVIDERS_WHATSAPP", "")
MESSAGING_FAILOVER_COOLDOWN_SECONDS = int(
    os.getenv("MESSAGING_FAILOVER_COOLDOWN_SECONDS", "0")
)


STORAGE_TYPE = os.getenv("STORAGE_TYPE", "AWS")

# AWS CONFIG
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME")
AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
AWS_S3_SIGNATURE_NAME = "s3v4"
AWS_S3_CUSTOM_DOMAIN = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com"
AWS_S3_FILE_OVERWRITE = False

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {"location": "media", "default_acl": None},
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = f"{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/media/"

DAPHNE_PORT = os.getenv("DAPHNE_PORT", default=8001)

ASGI_APPLICATION = "core.asgi.application"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {module}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class":     "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "apps.accounts": {
            "handlers": ["console"],
            "level":    "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level":    "WARNING",
            "propagate": False,
        },
    },
}


