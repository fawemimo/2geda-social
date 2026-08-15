from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from accounts.services.interfaces import NotificationPayload
from accounts.services.notifications import EmailNotificationSender

logger = logging.getLogger(__name__)


OTP_SUBJECTS = {
    "registration": "Verify your email",
    "login": "Your login code",
    "password_reset": "Reset your password",
    "phone_verify": "Verify your phone number",
    "email_verify": "Verify your email",
    "device_trust": "Confirm your device",
}


@shared_task(
    name="accounts.tasks.send_otp_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def send_otp_email(*, to: str, code: str, purpose: str, username: str = "") -> None:
    subject = OTP_SUBJECTS.get(purpose, "Your verification code")
    body = (
        f"Hi {username or 'there'},\n\n"
        f"Your verification code is: {code}\n\n"
        f"This code expires shortly. If you did not request it, please ignore this email."
    )

    EmailNotificationSender().send(
        NotificationPayload(
            to=to,
            subject=subject,
            body=body,
            template="otp",
            context={
                "code": code,
                "username": username,
                "purpose": purpose,
                "expires_in_minutes": max(
                    1, getattr(settings, "OTP_TTL_SECONDS", 600) // 60
                ),
            },
        )
    )


@shared_task(
    name="accounts.tasks.send_otp_message",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def send_otp_message(
    *,
    to: str,
    code: str,
    purpose: str,
    channel: str | None = None,
) -> None:
    from clients.messaging import MessagingService

    result = MessagingService().send_otp(to=to, code=code, channel=channel)
    logger.info(
        "OTP dispatched (purpose=%s channel=%s provider=%s)",
        purpose,
        result.channel,
        result.provider,
    )


@shared_task(
    name="accounts.tasks.send_otp_sms",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def send_otp_sms(*, to: str, code: str, purpose: str) -> None:
    from clients.messaging import Channel, MessagingService

    result = MessagingService().send_otp(to=to, code=code, channel=Channel.SMS)
    logger.info(
        "OTP dispatched (purpose=%s channel=%s provider=%s)",
        purpose,
        result.channel,
        result.provider,
    )


@shared_task(
    name="accounts.tasks.send_welcome_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_welcome_email(*, to: str, username: str) -> None:
    EmailNotificationSender().send(
        NotificationPayload(
            to=to,
            subject="Welcome to 2geda",
            body=f"Hi {username}, welcome to the platform!",
            template="welcome",
            context={"username": username},
        )
    )


# Periodic cleanup. Deletes OTP rows that have been used OR expired
@shared_task(name="accounts.tasks.purge_expired_otps")
def purge_expired_otps(*, older_than_days: int = 1) -> int:
    from accounts.models import OTP

    cutoff = timezone.now() - timedelta(days=older_than_days)
    deleted, _ = OTP.objects.filter(expires_at__lt=cutoff).delete()
    logger.info("Purged %s expired OTP rows older than %s", deleted, cutoff)
    return deleted


@shared_task(
    name="accounts.tasks.process_user_location",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def process_user_location(
    user_id: str, latitude: str, longitude: str, ip_address: str | None = None
) -> None:
    from accounts.models import User, UserLocation
    from accounts.services.discovery_cache import DiscoveryCache
    from clients.google.location_address import GoogleLocation

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.exception(f"User {user_id} not found for location processing.")
        return

    # Convert to float for Google API
    lat_f, lon_f = float(latitude), float(longitude)

    # Reverse geocode
    location_data = GoogleLocation().get_address(latitude=lat_f, longitude=lon_f)

    # Store in database
    UserLocation.objects.create(
        user=user,
        latitude=latitude,
        longitude=longitude,
        ip_address=ip_address,
        location_data=location_data,
    )

    # Warm Redis cache
    try:
        DiscoveryCache.set_location(user_id, lat_f, lon_f)
        meta = {"lat": str(lat_f), "lon": str(lon_f)}
        if location_data:
            meta["city"] = location_data.get("city", "") or ""
            meta["state"] = location_data.get("state", "") or ""
            meta["country"] = location_data.get("country", "") or ""
        DiscoveryCache.set_metadata(user_id, **meta)
    except Exception as exc:
        logger.warning("Failed to warm Redis cache: %s", exc)


@shared_task(
    name="accounts.tasks.async_send_connection_request",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def async_send_connection_request(requester_id: str, recipient_id: str) -> None:
    from accounts.models import User
    from accounts.services.connect import ConnectService

    try:
        requester = User.objects.get(pk=requester_id)
        recipient = User.objects.get(pk=recipient_id)
        ConnectService().send_connection_request(
            requester=requester, recipient=recipient
        )
    except Exception as e:
        logger.exception(
            f"Failed to send connection request from {requester_id} to {recipient_id}: {str(e)}"
        )


@shared_task(
    name="accounts.tasks.async_respond_to_connection",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def async_respond_to_connection(user_id: str, connection_id: str, action: str) -> None:
    from accounts.models import User
    from accounts.services.connect import ConnectService

    try:
        user = User.objects.get(pk=user_id)
        ConnectService().respond_to_connection(
            user=user, connection_id=connection_id, action=action
        )
    except Exception as e:
        logger.exception(
            f"Failed to respond to connection {connection_id} by {user_id}: {str(e)}"
        )


@shared_task(
    name="accounts.tasks.send_user_push_notification",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def send_user_push_notification(
    *, user_id: str, title: str, body: str, data: dict | None = None
) -> None:
    from accounts.models import User
    from accounts.services.device import DeviceService
    from clients.google.firebase import FireBasePushAPI

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.exception("User %s not found for push notification", user_id)
        return

    tokens = DeviceService.get_trusted_push_tokens(user)
    if not tokens:
        return

    firebase = FireBasePushAPI()
    for token in tokens:
        try:
            firebase.send_notification(token, title, body, data=data)
        except Exception:
            logger.exception("Failed to send push to token for user %s", user_id)


# Delete an old/replaced profile image from S3 + DB and notify the user.
@shared_task(
    name="accounts.tasks.cleanup_old_profile_image",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def cleanup_old_profile_image(
    *,
    media_id: str,
    user_id: str,
    field: str,
    notify: bool = True,
) -> None:
    from clients.storage import StorageService
    from medias.models import Media

    old_media = Media.objects.filter(pk=media_id).first()
    if old_media is None:
        logger.warning("Old media %s already gone, skipping cleanup", media_id)
        return

    # storage_key is authoritative; cdn_url is only a rendering of it.
    if old_media.storage_key:
        StorageService().delete(old_media.storage_key)
    old_media.delete()

    if notify:
        send_user_push_notification.delay(
            user_id=user_id,
            title="Profile Updated",
            body=f"Your profile {field.replace('_', ' ')} has been updated.",
            data={"type": "profile_image_updated", "field": field},
        )


# Decode, downscale and upload a staged profile image, then swap it in.
@shared_task(
    name="accounts.tasks.process_profile_image",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
)
def process_profile_image(
    *,
    media_id: str,
    user_id: str,
    field: str,
    staging_key: str,
) -> dict:
    from django.db import transaction as db_transaction

    from accounts.models import UserProfile
    from clients.storage import StorageService
    from medias.models import Media
    from utils import images
    from utils.enum import ProcessingStatus
    from utils.staging import drop_blob, peek_blob

    media = Media.objects.filter(pk=media_id).first()
    if media is None:
        logger.warning("Media %s vanished before processing", media_id)
        return {"success": False, "error": "media_missing"}

    # Peek rather than claim: a retry after a transient S3 error must still
    # find the bytes. The blob is dropped explicitly once we are done.
    raw = peek_blob(staging_key)
    if raw is None:
        logger.exception("Staged bytes expired for media %s", media_id)
        _mark_media_failed(media, "Upload expired before processing.")
        return {"success": False, "error": "staging_expired"}

    try:
        processed = images.normalize(raw, max_edge=images.max_edge_for(field))
    except images.ImageValidationError as exc:
        logger.exception("Profile image rejected for media %s: %s", media_id, exc)
        drop_blob(staging_key)
        _mark_media_failed(media, str(exc))
        return {"success": False, "error": "invalid_image"}

    # Raises on failure so autoretry_for kicks in; the blob survives for it.
    StorageService().upload_to_key(
        processed["buffer"],
        media.storage_key,
        content_type=processed["content_type"],
    )
    drop_blob(staging_key)

    old_media_id = None
    with db_transaction.atomic():
        profile = (
            UserProfile.objects.select_for_update().filter(user_id=user_id).first()
        )
        if profile is None:
            logger.exception("Profile missing for user %s", user_id)
            return {"success": False, "error": "profile_missing"}

        media.refresh_from_db()
        media.cdn_url = _public_media_url(media.storage_key)
        media.mime_type = processed["content_type"]
        media.file_size_bytes = processed["file_size_bytes"]
        media.width_px = processed["width"]
        media.height_px = processed["height"]
        media.processing_status = ProcessingStatus.READY.value
        media.processing_error = ""
        media.save(
            update_fields=[
                "cdn_url",
                "mime_type",
                "file_size_bytes",
                "width_px",
                "height_px",
                "processing_status",
                "processing_error",
            ]
        )

        previous = getattr(profile, field, None)
        if previous is not None and str(previous.pk) != str(media.pk):
            old_media_id = str(previous.pk)

        setattr(profile, field, media)
        profile.save(update_fields=[field])

    if old_media_id:
        cleanup_old_profile_image.delay(
            media_id=old_media_id,
            user_id=user_id,
            field=field,
        )
    else:
        send_user_push_notification.delay(
            user_id=user_id,
            title="Profile Updated",
            body=f"Your profile {field.replace('_', ' ')} has been updated.",
            data={"type": "profile_image_updated", "field": field},
        )

    logger.info("Profile image ready | media=%s field=%s", media_id, field)
    return {"success": True, "media_id": media_id, "url": media.cdn_url}


def _mark_media_failed(media, reason: str) -> None:
    from utils.enum import ProcessingStatus

    media.processing_status = ProcessingStatus.FAILED.value
    media.processing_error = reason[:500]
    media.save(update_fields=["processing_status", "processing_error"])


def _public_media_url(key: str) -> str:
    from clients.storage import StorageService

    return StorageService().url_for(key)


@shared_task(
    name="accounts.tasks.hash_pending_password",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def hash_pending_password(*, identifier: str, raw_password: str) -> None:
    from accounts.services.pending_registration import (
        PendingRegistration,
        PendingRegistrationStore,
    )

    store = PendingRegistrationStore()
    pending = store.get(identifier)
    if pending is None:
        logger.warning("Pending registration expired before hash completed")
        return

    hashed = make_password(raw_password)
    updated = PendingRegistration(
        email=pending.email,
        username=pending.username,
        phone_number=pending.phone_number,
        password_hash=hashed,
        raw_password=None,
        referral_code=pending.referral_code,
        code_hash=pending.code_hash,
        attempts=pending.attempts,
        issued_at=pending.issued_at,
        ip_address=pending.ip_address,
    )
    remaining_ttl = (
        pending.issued_at
        + timedelta(seconds=getattr(settings, "OTP_TTL_SECONDS", 600))
        - timezone.now()
    )
    if remaining_ttl > timedelta(0):
        store.replace(identifier, updated, ttl=remaining_ttl)
    else:
        logger.warning("Pending registration expired, skipping hash update")


@shared_task(
    name="accounts.tasks.process_referral_reward",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def process_referral_reward(*, referral_code: str, referred_user_id: str) -> None:
    from accounts.models import Referral, User
    from accounts.services.rewards import reward_user
    from utils.enum import PointRewardingMaps

    try:
        referrer = User.objects.only("id").get(referral_code=referral_code.upper())
        referred_user = User.objects.get(pk=referred_user_id)
    except User.DoesNotExist:
        logger.exception(
            "Referrer or referred user not found for user=%s", referred_user_id
        )
        return

    Referral.objects.get_or_create(referrer=referrer, referred_user=referred_user)

    reward_user(
        user=referrer,
        points=PointRewardingMaps.REFFERAL.value,
        action="referral",
        source=referred_user,
        auto_claim=True,
    )
