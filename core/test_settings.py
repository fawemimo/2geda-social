import os
from datetime import timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-xxxxxxxxxxxxxxxxx")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("ALLOWED_HOSTS", "testserver,localhost")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://testserver")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "http://testserver")
os.environ.setdefault("DB_NAME", ":memory:")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
os.environ.setdefault("EMAIL_HOST", "localhost")
os.environ.setdefault("EMAIL_HOST_USER", "test")
os.environ.setdefault("EMAIL_HOST_PASSWORD", "test")
os.environ.setdefault("DEFAULT_FROM_EMAIL", "noreply@test.local")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
os.environ.setdefault("AWS_STORAGE_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_S3_REGION_NAME", "us-east-1")

# Pull in everything from the production-style overrides, then patch what
# tests must override (DB, cache, broker, email backend, JWT key).
from core.settings import *  # noqa: F401,F403,E402

SECRET_KEY = "test-secret-key-not-for-production-xxxxxxxxxxxxxxxxx"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Stop the test boot from failing on app-cross FKs to optional apps.
SILENCED_SYSTEM_CHECKS = ["fields.E300", "fields.E307"]

# Keep JWT signing deterministic against our test SECRET_KEY.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":  timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS":  True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUTH_HEADERS_TYPES": ("JWT", "Bearer"),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "accounts.serializers.UserTokenObtainPairSerializer",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}

# Tests don't want production throttle pressure.
REST_FRAMEWORK = {
    **globals().get("REST_FRAMEWORK", {}),
    "DEFAULT_THROTTLE_CLASSES": (),
    "DEFAULT_THROTTLE_RATES": {
        "anon_burst": "60/minute",
        "anon_sustained": "1000/day",
        "user_burst": "240/minute",
        "user_sustained": "20000/day",
        "otp_request": "10/minute",
        "otp_verify": "10/minute",
        "login": "20/minute",
        "registration": "10/minute",
        "post_create": "3/minute",
    },
}

