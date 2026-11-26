from django.core.cache import cache
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework import serializers, status

from accounts.tasks import send_incoming_call_push
from chats.models import CallLog
from chats.serializers import CallDeclineSerializer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from utils.responses import APIResponse


class DeclineCallView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CallDeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            call = CallLog.objects.get(
                pk=values["call_id"],
                caller_id=values["caller_id"],
                receiver_id=request.user.id,
                conversation_id=values["conversation_id"],
            )
        except CallLog.DoesNotExist:
            raise serializers.ValidationError({"call_id": "Call not found."})

        if call.status != "ringing":
            raise serializers.ValidationError({"call_id": "Call is no longer ringing."})
        call.status = "declined"
        call.ended_at = timezone.now()
        call.offer_sdp = ""
        call.save(update_fields=["status", "ended_at", "offer_sdp", "updated_at"])

        async_to_sync(get_channel_layer().group_send)(
            f"user_{call.caller_id}",
            {
                "type": "call_ended",
                "ended_by": str(request.user.id),
                "reason": "declined",
                "call_id": str(call.id),
            },
        )
        if not cache.get(f"online_user:{call.caller_id}"):
            send_incoming_call_push.delay(
                user_id=str(call.caller_id),
                data={
                    "type": "call_declined",
                    "call_id": str(call.id),
                    "caller_id": str(call.caller_id),
                    "conversation_id": str(call.conversation_id),
                },
            )
        return APIResponse.success(
            message="Call declined.", data={"call_id": str(call.id)},
            status_code=status.HTTP_200_OK,
        )
