from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from rest_framework import parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.views import APIView

from clients.storage import classify
from medias.models import Media
from medias.serializers import (
    MediaPresignedUrlSerializer,
    MediaResponseSerializer,
    MediaUploadSerializer,
)
from utils.enum import ProcessingStatus
from utils.pagination import StandardPagination
from utils.responses import APIResponse

logger = logging.getLogger(__name__)


class MediaUploadView(APIView):
    """Server-side upload — file is queued to Celery for S3 upload.

    The request returns immediately with processing_status=PENDING;
    the Celery task uploads to S3 and updates the record to READY.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        serializer = MediaUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data["file"]
        filename = getattr(file, "name", "") or "upload"

        try:
            info = classify(filename)
        except ValueError as exc:
            return APIResponse.error(message=str(exc), status_code=400)

        import uuid
        temp_key = f"pending/{uuid.uuid4()}"

        media = Media.objects.create(
            owner=request.user,
            media_type=info["media_type"],
            storage_key=temp_key,
            original_filename=filename,
            processing_status=ProcessingStatus.PENDING.value,
        )

        file_bytes = file.read()
        import base64
        encoded = base64.b64encode(file_bytes).decode("ascii")

        transaction.on_commit(lambda: _queue_media_upload(
            str(media.id), encoded, filename,
        ))

        logger.info(
            "Media upload queued | id=%s type=%s user=%s",
            media.id, media.media_type, request.user.id,
        )

        return APIResponse.success(
            message="Media upload queued for processing.",
            data=MediaResponseSerializer(media).data,
            status_code=status.HTTP_201_CREATED,
        )


def _queue_media_upload(media_id: str, encoded: str, filename: str) -> None:
    from medias.tasks import process_media_upload
    process_media_upload.delay(media_id, encoded, filename)


class MediaViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    serializer_class = MediaResponseSerializer
    pagination_message = "Media fetched successfully."

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return Media.objects.filter(
                owner=user, is_deleted=False,
            ).order_by("-created_at")
        return Media.objects.none()

    def create(self, request, *args, **kwargs):
        return APIResponse.error(
            message="Use POST /medias/upload/ for server-side upload "
                    "or POST /medias/presigned-url/ for client-side upload.",
            status_code=405,
        )

    def update(self, request, *args, **kwargs):
        return APIResponse.error(message="Media cannot be updated.", status_code=405)

    def partial_update(self, request, *args, **kwargs):
        return APIResponse.error(message="Media cannot be updated.", status_code=405)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.success(data=serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return APIResponse.success(data=serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.owner != request.user:
            return APIResponse.error(
                message="You can only delete your own media.", status_code=403,
            )

        storage_key = instance.storage_key
        instance.delete()

        if storage_key and not storage_key.startswith("pending/"):
            from medias.tasks import delete_media_file
            transaction.on_commit(lambda: delete_media_file.delay(storage_key))

        logger.info("Media deleted | id=%s user=%s", instance.id, request.user.id)
        return APIResponse.success(message="Media deleted successfully.")

    @action(detail=False, methods=["post"], url_path="presigned-url")
    def presigned_url(self, request):
        """Generate a presigned S3 URL for direct client-side upload.

        Creates a Media record (PENDING), returns the presigned URL + media_id.
        The client uploads directly to S3, then calls confirm-upload.
        """
        serializer = MediaPresignedUrlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_name = serializer.validated_data["file_name"]

        try:
            info = classify(file_name)
        except ValueError as exc:
            return APIResponse.error(message=str(exc), status_code=400)

        from clients.storage import StorageService

        try:
            signed = StorageService().presigned_upload(file_name)
        except Exception as exc:
            return APIResponse.error(message=str(exc), status_code=500)

        media = Media.objects.create(
            owner=request.user,
            media_type=info["media_type"],
            storage_key=signed.key,
            original_filename=file_name,
            processing_status=ProcessingStatus.PENDING.value,
        )

        logger.info(
            "Presigned URL issued | id=%s key=%s user=%s",
            media.id, signed.key, request.user.id,
        )

        return APIResponse.success(
            message="Presigned URL generated. Upload the file directly to storage, "
                    "then POST to confirm-upload.",
            data={
                "url": signed.url,
                "key": signed.key,
                "media_id": str(media.id),
                "media_type": signed.media_type,
                "content_type": signed.content_type,
                "headers": signed.headers,
            },
        )

    @action(detail=True, methods=["post"], url_path="confirm-upload")
    def confirm_upload(self, request, pk=None):
        """Confirm that a presigned-URL upload completed.

        Verifies the file exists in S3 and marks the Media as READY.
        """
        instance = self.get_object()
        if instance.owner != request.user:
            return APIResponse.error(message="Not your media.", status_code=403)

        if instance.processing_status == ProcessingStatus.READY.value:
            return APIResponse.success(
                message="Media already confirmed.",
                data=MediaResponseSerializer(instance).data,
            )

        import boto3
        from botocore.exceptions import ClientError

        s3 = boto3.client("s3")
        try:
            s3.head_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=instance.storage_key,
            )
        except ClientError:
            return APIResponse.error(
                message="File not found in S3. Upload using the presigned URL first.",
                status_code=404,
            )

        instance.processing_status = ProcessingStatus.READY.value
        instance.save(update_fields=["processing_status"])

        logger.info("Upload confirmed | id=%s", instance.id)

        return APIResponse.success(
            message="Upload confirmed successfully.",
            data=MediaResponseSerializer(instance).data,
        )
