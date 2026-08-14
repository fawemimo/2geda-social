from __future__ import annotations

import logging
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema 
from accounts.models import User
from accounts.cache import (
    CACHE_DETAIL_TTL,
    CACHE_LIST_TTL,
    make_user_detail_cache_key,
    make_user_list_cache_key,
    make_user_me_cache_key,
)
from accounts.serializers import (
    ConnectFilterSerializer,
    ConnectRespondSerializer,
    ConnectUserSerializer,
    DevicePayloadSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileImageUploadSerializer,
    ProfileUpdateSerializer,
    PushTokenUpdateSerializer,
    RegisterSerializer,
    ResendOTPSerializer,
    TokenRefreshSerializer,
    UserDeviceSerializer,
    UserDetailSerializer,
    UserListSerializer,
    UserLocationIngestSerializer,
    UserMeSerializer,
    UserProfileSerializer,
    VerifyOTPSerializer,
)
from accounts.services import (
    AuthenticationService,
    DeviceService,
    OTPService,
    PasswordService,
    ProfileService,
    RegistrationService,
    TokenService,
)
from accounts.services.connect import ConnectService
from accounts.services.device import DevicePayload
from accounts.tasks import async_respond_to_connection, async_send_connection_request, process_user_location
from accounts.services.exceptions import NotFoundError
from accounts.throttles import (
    LoginThrottle,
    OTPRequestThrottle,
    OTPVerifyThrottle,
    RegistrationThrottle,
)
from utils.enum import OTPChannel, OTPPurpose
from utils.pagination import StandardPagination
from utils.responses import APIResponse


logger = logging.getLogger(__name__)


def _client_ip(request) -> str | None:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


#  registration & OTP 


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [RegistrationThrottle]
    throttle_scope = "registration"

    @swagger_auto_schema(request_body=RegisterSerializer)
    def post(self, request):
        data = RegisterSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data.get("email") or None
        phone_number = data.validated_data.get("phone_number") or None
        result = RegistrationService().start_registration(
            email=email,
            username=data.validated_data["username"],
            password=data.validated_data["password"],
            phone_number=phone_number,
            referral_code=data.validated_data.get("referral_code") or None,
            ip_address=_client_ip(request),
            channel=data.validated_data.get("channel") or None,
        )
        resp_data = {
            "otp_expires_at": result.otp_expires_at,
            "cooldown_until": result.cooldown_until,
            "next": "verify_otp",
        }
        if result.email:
            resp_data["email"] = result.email
        if result.phone_number:
            resp_data["phone_number"] = result.phone_number
        channel = (
            "email" if result.email
            else (data.validated_data.get("channel") or "WhatsApp")
        )
        return APIResponse.success(
            message=f"OTP has been sent to your {channel}. Verify to finish creating your account.",
            data=resp_data,
            status_code=status.HTTP_202_ACCEPTED,
        )


class VerifyRegistrationOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyThrottle]
    throttle_scope = "otp_verify"

    @swagger_auto_schema(request_body=VerifyOTPSerializer)
    def post(self, request):
        data = VerifyOTPSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        email = data.validated_data.get("email") or None
        phone_number = data.validated_data.get("phone_number") or None

        result = RegistrationService().complete_registration(
            email=email,
            phone_number=phone_number,
            code=data.validated_data["code"],
        )

        device_payload = data.validated_data.get("device")
        if device_payload:
            user = User.objects.get(pk=result.user_id)
            DeviceService().register(
                user=user,
                payload=DevicePayload(
                    name=device_payload.get("name", ""),
                    platform=device_payload["platform"],
                    device_fingerprint=device_payload["device_fingerprint"],
                    os_version=device_payload.get("os_version", ""),
                    app_version=device_payload.get("app_version", ""),
                    push_token=device_payload.get("push_token", ""),
                ),
                ip_address=_client_ip(request),
            )

        resp_data = {
            "user_id": result.user_id,
            "access": result.access,
            "refresh": result.refresh,
            "token_type": "Bearer",
        }
        if result.email:
            resp_data["email"] = result.email
        if result.phone_number:
            resp_data["phone_number"] = result.phone_number

        return APIResponse.success(
            message="Account verified and created successfully.",
            data=resp_data,
            status_code=status.HTTP_201_CREATED,
        )


class ResendOTPView(APIView):
    """
    Resend OTP. For purpose=registration the OTP lives in Redis; for
    every other purpose the DB-backed OTPService is used.
    """
    permission_classes = [AllowAny]
    throttle_classes = [OTPRequestThrottle]
    throttle_scope = "otp_request"

    @swagger_auto_schema(request_body=ResendOTPSerializer)
    def post(self, request):
        data = ResendOTPSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        purpose = data.validated_data.get("purpose") or OTPPurpose.REGISTRATION.value

        email = data.validated_data.get("email") or None
        phone_number = data.validated_data.get("phone_number") or None

        if purpose == OTPPurpose.REGISTRATION.value:
            result = RegistrationService().resend_registration_otp(
                email=email,
                phone_number=phone_number,
                channel=data.validated_data.get("channel") or None,
            )
            resp_data = {
                "otp_expires_at": result.otp_expires_at,
                "cooldown_until": result.cooldown_until,
                "purpose": purpose,
            }
            if result.email:
                resp_data["email"] = result.email
            if result.phone_number:
                resp_data["phone_number"] = result.phone_number
            channel = (
                "email" if result.email
                else (data.validated_data.get("channel") or "WhatsApp")
            )
            return APIResponse.success(
                message=f"A new OTP has been sent to your {channel}.",
                data=resp_data,
            )
        
        email = email.lower() if email else email
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist as exc:
            raise NotFoundError("No account found for this email.", code="user_not_found") from exc

        issued = OTPService().issue(
            user=user,
            purpose=purpose,
            delivery_address=email,
            channel=OTPChannel.EMAIL.value,
            ip_address=_client_ip(request),
        )
        from accounts import tasks
        tasks.send_otp_email.delay(
            to=email, code=issued.code, purpose=purpose, username=user.username
        )
        return APIResponse.success(
            message="A new OTP has been sent to your email.",
            data={"otp_expires_at": issued.expires_at, "purpose": purpose},
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    throttle_scope = "login"

    @swagger_auto_schema(request_body=LoginSerializer)
    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = AuthenticationService().login(
            email=data.validated_data.get("email"),
            username=data.validated_data.get("username"),
            phone_number=data.validated_data.get("phone_number"),
            password=data.validated_data["password"],
            device_payload=data.validated_data.get("device"),
            ip_address=_client_ip(request),
        )
        return APIResponse.success(
            message="Logged in successfully.",
            data={
                "user_id": result.user_id,
                "access": result.access,
                "access_expires_at": result.access_expires_at,
                "refresh": result.refresh,
                "refresh_expires_at": result.refresh_expires_at,
                "token_type": "Bearer",
                "device_id": result.device_id,
            },
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=LogoutSerializer)
    def post(self, request):
        data = LogoutSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        AuthenticationService().logout(refresh_token=data.validated_data["refresh"])
        return APIResponse.success(message="Logged out successfully.", data={})


class LogoutEverywhereView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        count = AuthenticationService().logout_everywhere(user=request.user)
        return APIResponse.success(
            message="All active sessions have been signed out.",
            data={"sessions_revoked": count},
        )


#  token management 
class TokenRefreshView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(request_body=TokenRefreshSerializer)
    def post(self, request):
        data = TokenRefreshSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        tokens = TokenService().refresh(data.validated_data["refresh"])
        return APIResponse.success(message="Token refreshed successfully.", data=tokens)


#  password reset / change 

class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPRequestThrottle]
    throttle_scope = "otp_request"

    @swagger_auto_schema(request_body=PasswordResetRequestSerializer)
    def post(self, request):
        data = PasswordResetRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        PasswordService().request_reset(
            email=data.validated_data.get("email"),
            phone_number=data.validated_data.get("phone_number"),
            ip_address=_client_ip(request),
        )
        # Deliberately uniform response: don't leak whether the identifier is registered.
        return APIResponse.success(
            message="If that email or phone number is registered, an OTP has been sent.",
            data={},
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyThrottle]
    throttle_scope = "otp_verify"

    @swagger_auto_schema(request_body=PasswordResetConfirmSerializer)
    def post(self, request):
        data = PasswordResetConfirmSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        PasswordService().confirm_reset(
            email=data.validated_data.get("email"),
            phone_number=data.validated_data.get("phone_number"),
            code=data.validated_data["code"],
            new_password=data.validated_data["new_password"],
        )
        return APIResponse.success(
            message="Password has been reset. Please log in with your new password.",
            data={},
        )


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=PasswordChangeSerializer)
    def post(self, request):
        from accounts.tasks import send_user_push_notification

        user = request.user
        data = PasswordChangeSerializer(data=request.data)
        try:
            data.is_valid(raise_exception=True)
            PasswordService().change_password(user=user, **data.validated_data)
        except Exception:
            send_user_push_notification.delay(
                user_id=str(user.id),
                title="Security Alert",
                body="Someone attempted to change your password. If this wasn't you, secure your account immediately.",
                data={"type": "password_change_failed"},
            )
            raise

        send_user_push_notification.delay(
            user_id=str(user.id),
            title="Password Changed",
            body="Your password was changed successfully.",
            data={"type": "password_change_success"},
        )
        return APIResponse.success(
            message="Password updated. All other sessions have been signed out.",
            data={},
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(responses={200: UserMeSerializer()})
    def get(self, request):
        cache_key = make_user_me_cache_key(str(request.user.pk))
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(data=cached)

        response = APIResponse.success(
            message="Current user fetched successfully.",
            data=UserMeSerializer(request.user).data,
        )
        cache.set(cache_key, response.data, timeout=None)
        return response


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(responses={200: UserProfileSerializer()})
    def get(self, request):
        profile = ProfileService().get(user=request.user)
        return APIResponse.success(
            message="Profile fetched successfully.",
            data=UserProfileSerializer(profile).data,
        )

    @swagger_auto_schema(request_body=ProfileUpdateSerializer, responses={200: UserProfileSerializer()})
    def patch(self, request):
        data = ProfileUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        profile = ProfileService().update_partial(user=request.user, data=data.validated_data)
        return APIResponse.success(
            message="Profile updated successfully.",
            data=UserProfileSerializer(profile).data,
        )



def _dispatch_profile_image_upload(request, field: str) -> Response:
    """Accept a profile image and hand the heavy work to Celery.

    The request thread only validates, parks the bytes in Redis and reserves the
    final S3 key — so it returns in single-digit milliseconds regardless of how
    slow S3 is. Decoding, downscaling and uploading happen on a worker.
    """
    from django.db import transaction

    from accounts.tasks import process_profile_image
    from clients.aws.storage import build_key, public_url
    from medias.models import Media
    from utils.enum import MediaType, ProcessingStatus
    from utils.staging import stage_blob

    data = ProfileImageUploadSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    file = data.validated_data["file"]

    file.seek(0)
    staging_key = stage_blob(file.read())

    # Reserve the object key now so the client learns its final URL up front and
    # can prefetch or optimistically render it.
    storage_key = build_key(MediaType.IMAGE.value, ".jpg")
    final_url = public_url(storage_key)

    with transaction.atomic():
        media = Media.objects.create(
            owner=request.user,
            media_type=MediaType.IMAGE.value,
            storage_key=storage_key,
            cdn_url="",
            original_filename=(getattr(file, "name", "") or "")[:255],
            processing_status=ProcessingStatus.PENDING.value,
        )
        # on_commit, or the worker can start before this row is visible to it.
        transaction.on_commit(
            lambda: process_profile_image.delay(
                media_id=str(media.id),
                user_id=str(request.user.id),
                field=field,
                staging_key=staging_key,
            )
        )

    return APIResponse.success(
        message=f"Your profile {field.replace('_', ' ')} is being processed.",
        data={
            "media_id": str(media.id),
            "processing_status": ProcessingStatus.PENDING.value,
            field: final_url,
        },
        status_code=status.HTTP_202_ACCEPTED,
    )


def _delete_profile_image(request, field: str) -> Response:
    """Detach a profile image immediately; reclaim the S3 object in the background."""
    from django.db import transaction

    from accounts.tasks import cleanup_old_profile_image

    profile = request.user.profile
    old_media = getattr(profile, field, None)
    if not old_media:
        return APIResponse.success(
            message=f"No {field.replace('_', ' ')} to remove.",
            data={field: None},
        )

    old_media_id = str(old_media.pk)

    # Detach synchronously so the very next read of the profile is correct;
    # only the slow S3 round-trip is deferred.
    with transaction.atomic():
        setattr(profile, field, None)
        profile.save(update_fields=[field])
        transaction.on_commit(
            lambda: cleanup_old_profile_image.delay(
                media_id=old_media_id,
                user_id=str(request.user.id),
                field=field,
                notify=False,
            )
        )

    return APIResponse.success(
        message=f"{field.replace('_', ' ').title()} removed successfully.",
        data={field: None},
    )


class ProfileAvatarUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @swagger_auto_schema(
        request_body=ProfileImageUploadSerializer,
        responses={202: "Accepted — image queued for processing"},
    )
    def put(self, request):
        return _dispatch_profile_image_upload(request, "avatar")

    @swagger_auto_schema(responses={200: "Avatar removed"})
    def delete(self, request):
        return _delete_profile_image(request, "avatar")


class ProfileCoverUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    @swagger_auto_schema(
        request_body=ProfileImageUploadSerializer,
        responses={202: "Accepted — image queued for processing"},
    )
    def put(self, request):
        return _dispatch_profile_image_upload(request, "cover_photo")

    @swagger_auto_schema(responses={200: "Cover photo removed"})
    def delete(self, request):
        return _delete_profile_image(request, "cover_photo")


class ProfileDisplayPhotoUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    @swagger_auto_schema(
        request_body=ProfileImageUploadSerializer,
        responses={202: "Accepted — image queued for processing"},
    )
    def put(self, request):
        return _dispatch_profile_image_upload(request, "display_photo")

    @swagger_auto_schema(responses={200: "Display photo removed"})
    def delete(self, request):
        return _delete_profile_image(request, "display_photo")


class DeviceListCreateView(APIView):
    """
    GET paginated list of the caller's devices.
    POST register a new device for the caller.
    """
    permission_classes = [IsAuthenticated]
    pagination_message = "Devices fetched successfully."

    @swagger_auto_schema(responses={200: UserDeviceSerializer(many=True)})
    def get(self, request):

        queryset = DeviceService().list_for_user(request.user)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(list(queryset), request, view=self)
        if page is None:
            return APIResponse.success(
                message="Devices fetched successfully.",
                data=UserDeviceSerializer(queryset, many=True).data,
            )
        serializer = UserDeviceSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @swagger_auto_schema(request_body=DevicePayloadSerializer)
    def post(self, request):
        data = DevicePayloadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payload = DevicePayload(
            name=data.validated_data.get("name", ""),
            platform=data.validated_data["platform"],
            device_fingerprint=data.validated_data["device_fingerprint"],
            os_version=data.validated_data.get("os_version", ""),
            app_version=data.validated_data.get("app_version", ""),
            push_token=data.validated_data.get("push_token", ""),
        )
        device = DeviceService().register(
            user=request.user, payload=payload, ip_address=_client_ip(request)
        )
        return APIResponse.success(
            message="Device registered successfully.",
            data=UserDeviceSerializer(device).data,
            status_code=status.HTTP_201_CREATED,
        )


class DeviceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter("device_id", openapi.IN_PATH, description="Device ID", type=openapi.TYPE_STRING),
        ],
    )
    def delete(self, request, device_id):
        DeviceService().revoke(user=request.user, device_id=device_id)
        return APIResponse.success(message="Device revoked successfully.", data={})


class DevicePushTokenView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        request_body=PushTokenUpdateSerializer,
        manual_parameters=[
            openapi.Parameter("device_id", openapi.IN_PATH, description="Device ID", type=openapi.TYPE_STRING),
        ],
    )
    def post(self, request, device_id):
        data = PushTokenUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        device = DeviceService().update_push_token(
            user=request.user,
            device_id=device_id,
            push_token=data.validated_data["push_token"],
        )
        return APIResponse.success(
            message="Push token updated successfully.",
            data=UserDeviceSerializer(device).data,
        )


class DeviceTrustView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter("device_id", openapi.IN_PATH, description="Device ID", type=openapi.TYPE_STRING),
        ],
    )
    def post(self, request, device_id):
        device = DeviceService().trust(user=request.user, device_id=device_id)
        return APIResponse.success(
            message="Device marked as trusted.",
            data=UserDeviceSerializer(device).data,
        )


#  user listing & detail 

class UserListView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_message = "Users fetched successfully."

    def get(self, request):
        cache_key = make_user_list_cache_key(dict(request.query_params.items()))
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(data=cached)

        qs = User.objects.filter(is_active=True, is_deleted=False).select_related(
            "profile__avatar",
        ).order_by("-created_at")

        FILTER_MAP = {
            "username": "username__icontains",
            "email": "email__icontains",
            "display_name": "profile__display_name__icontains",
            "first_name": "profile__first_name__icontains",
            "last_name": "profile__last_name__icontains",
            "city": "profile__current_city__icontains",
        }

        filters = {}
        for param, lookup in FILTER_MAP.items():
            val = request.query_params.get(param, "").strip()
            if val:
                filters[lookup] = val

        if filters:
            qs = qs.filter(**filters)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is None:
            response = APIResponse.success(
                message="Users fetched successfully.",
                data=UserListSerializer(qs, many=True).data,
            )
        else:
            serializer = UserListSerializer(page, many=True)
            response = paginator.get_paginated_response(serializer.data)

        cache.set(cache_key, response.data, timeout=CACHE_LIST_TTL)
        return response


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        cache_key = make_user_detail_cache_key(str(user_id))
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(data=cached)

        try:
            user = User.objects.select_related(
                "profile__avatar", "profile__cover_photo",
            ).get(pk=user_id, is_active=True, is_deleted=False)
        except User.DoesNotExist:
            return APIResponse.error(
                message="User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        serializer = UserDetailSerializer(user)
        response = APIResponse.success(
            message="User fetched successfully.",
            data=serializer.data,
        )
        cache.set(cache_key, response.data, timeout=CACHE_DETAIL_TTL)
        return response
        serializer = UserDetailSerializer(user)
        return APIResponse.success(
            message="User fetched successfully.",
            data=serializer.data,
        )


#  connect & discovery 

class ConnectDiscoveryView(APIView):
    """
    GET Fetch discoverable users based on distance, city, state, or country.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter("distance_km", openapi.IN_QUERY, type=openapi.TYPE_NUMBER, required=False),
            openapi.Parameter("city", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("state", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter("country", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
        ],
        responses={200: ConnectUserSerializer(many=True)},
    )
    def get(self, request):

        filters = ConnectFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)

        queryset = ConnectService().get_discoverable_users(request.user, filters.validated_data)
        
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is None:
            return APIResponse.success(
                message="Discoverable users fetched successfully.",
                data=ConnectUserSerializer(queryset, many=True).data,
            )
        serializer = ConnectUserSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ConnectRequestView(APIView):
    """
    POST  Send a connection request to a specific user asynchronously.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter("user_id", openapi.IN_PATH, description="Recipient user ID", type=openapi.TYPE_STRING),
        ],
    )
    def post(self, request, user_id):
        
        async_send_connection_request.delay(
            requester_id=str(request.user.id),
            recipient_id=str(user_id)
        )
        return APIResponse.success(
            message="Connection request dispatched successfully.",
            data={},
            status_code=status.HTTP_202_ACCEPTED
        )

class ConnectRespondView(APIView):
    """
    POST Accept or reject a connection request asynchronously.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        request_body=ConnectRespondSerializer,
        manual_parameters=[
            openapi.Parameter("connection_id", openapi.IN_PATH, description="Connection ID", type=openapi.TYPE_STRING),
        ],
    )
    def post(self, request, connection_id):
        
        data = ConnectRespondSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        async_respond_to_connection.delay(
            user_id=str(request.user.id),
            connection_id=str(connection_id),
            action=data.validated_data["action"]
        )
        
        return APIResponse.success(
            message=f"Connection response ({data.validated_data['action']}) dispatched successfully.",
            data={},
            status_code=status.HTTP_202_ACCEPTED
        )


class UserLocationUpdateView(APIView):
    """
    POST  Ingest user location coordinates asynchronously to handle high throughput.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=UserLocationIngestSerializer)
    def post(self, request):
        data = UserLocationIngestSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        lat = float(data.validated_data["latitude"])
        lon = float(data.validated_data["longitude"])

        # Eagerly update Redis geoset for immediate discovery accuracy,
        # while the async task handles the DB write + reverse geocoding.
        from accounts.services.discovery_cache import DiscoveryCache
        uid = str(request.user.id)
        DiscoveryCache.set_location(uid, lat, lon)
        DiscoveryCache.set_metadata(uid, lat=str(lat), lon=str(lon))
        DiscoveryCache.invalidate_user(uid)

        process_user_location.delay(
            user_id=uid,
            latitude=str(lat),
            longitude=str(lon),
            ip_address=_client_ip(request)
        )

        return APIResponse.success(
            message="Location update accepted.",
            data={},
            status_code=status.HTTP_202_ACCEPTED
        )
