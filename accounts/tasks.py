from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from accounts.services.interfaces import NotificationPayload
from accounts.services.notifications import (
    SMSNotificationSender,
)


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
    logger.info(f"Email sent to {to} (subject={subject}): {body}")
    # EmailNotificationSender().send(
    #     NotificationPayload(
    #         to=to,
    #         subject=subject,
    #         body=body,
    #         template="accounts/emails/otp.html",
    #         context={"code": code, "username": username, "purpose": purpose},
    #     )
    # )


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
    SMSNotificationSender().send(
        NotificationPayload(
            to=to,
            subject=OTP_SUBJECTS.get(purpose, "Verification code"),
            body=f"Your verification code is: {code}",
        )
    )


@shared_task(
    name="accounts.tasks.send_otp_whatsapp",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def send_otp_whatsapp(*, to: str, code: str, purpose: str) -> None:
    from accounts.services.notifications import WhatsAppNotificationSender
    logger.info(f"WhatsApp OTP to {to} (purpose={purpose}): {code}")
    # WhatsAppNotificationSender().send(
    #     NotificationPayload(
    #         to=to,
    #         subject=OTP_SUBJECTS.get(purpose, "Verification code"),
    #         body=f"Your verification code is: {code}",
    #         context={"code": code},
    #     )
    # )


@shared_task(
    name="accounts.tasks.send_welcome_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_welcome_email(*, to: str, username: str) -> None:
    logger.info(f"Welcome email sent to {to} (username={username})")
    # EmailNotificationSender().send(
    #     NotificationPayload(
    #         to=to,
    #         subject="Welcome aboard",
    #         body=f"Hi {username}, welcome to the platform!",
    #         template="accounts/emails/welcome.html",
    #         context={"username": username},
    #     )
    # )


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
# Reverse geocodes the coordinates via Google Maps API and creates a UserLocation record.
)
def process_user_location(user_id: str, latitude: str, longitude: str, ip_address: str | None = None) -> None:
    from accounts.models import User, UserLocation
    from accounts.services.discovery_cache import DiscoveryCache
    from clients.google.location_address import GoogleLocation

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for location processing.")
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
        location_data=location_data
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

    logger.info(f"UserLocation created for {user_id} at {latitude},{longitude}")


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
        ConnectService().send_connection_request(requester=requester, recipient=recipient)
    except Exception as e:
        logger.error(f"Failed to send connection request from {requester_id} to {recipient_id}: {str(e)}")


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
        ConnectService().respond_to_connection(user=user, connection_id=connection_id, action=action)
    except Exception as e:
        logger.error(f"Failed to respond to connection {connection_id} by {user_id}: {str(e)}")


@shared_task(
    name="accounts.tasks.send_user_push_notification",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
)
def send_user_push_notification(*, user_id: str, title: str, body: str, data: dict | None = None) -> None:
    from accounts.models import User
    from accounts.services.device import DeviceService
    from clients.google.firebase import FireBasePushAPI

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("User %s not found for push notification", user_id)
        return

    tokens = DeviceService.get_trusted_push_tokens(user)
    if not tokens:
        logger.info("No trusted push tokens for user %s", user_id)
        return

    firebase = FireBasePushAPI()
    for token in tokens:
        try:
            firebase.send_notification(token, title, body, data=data)
        except Exception:
            logger.exception("Failed to send push to token for user %s", user_id)


@shared_task(
    name="accounts.tasks.cleanup_old_profile_image",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
# Delete old profile image from S3 + DB and notify the user.
)
def cleanup_old_profile_image(
    *,
    media_id: str,
    user_id: str,
    field: str,
) -> None:
    from clients.aws.storage import delete_file
    from medias.models import Media

    try:
        old_media = Media.objects.get(pk=media_id)
    except Media.DoesNotExist:
        logger.warning("Old media %s already gone, skipping cleanup", media_id)
        return

    delete_file(old_media.cdn_url)
    old_media.delete()

    send_user_push_notification.delay(
        user_id=user_id,
        title="Profile Updated",
        body=f"Your profile {field.replace('_', ' ')} has been updated.",
        data={"type": "profile_image_updated", "field": field},
    )


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
        logger.warning("Pending registration %s expired before hash completed", identifier)
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
        logger.info("Password hashed for pending registration %s", identifier)
    else:
        logger.warning("Pending registration %s expired, skipping hash update", identifier)


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
        logger.error("Referrer or referred user not found for code=%s user=%s", referral_code, referred_user_id)
        return

    Referral.objects.get_or_create(referrer=referrer, referred_user=referred_user)

    reward_user(
        user=referrer,
        points=PointRewardingMaps.REFFERAL.value,
        action="referral",
        source=referred_user,
        auto_claim=True,
    )
    logger.info("Referral reward processed: referrer=%s referred=%s", referrer.pk, referred_user_id)

