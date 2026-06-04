from __future__ import annotations

import logging

from django.core.cache import cache
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from chats.serializers import (
    ConversationCreateSerializer,
    ConversationSerializer,
    MessageSerializer,
)
from chats.services import ChatService
from utils.responses import APIResponse

PRESENCE_CACHE_PREFIX = "online_user:"

logger = logging.getLogger(__name__)


class ConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(responses={200: ConversationSerializer(many=True)})
    def get(self, request):
        convs = ChatService().get_user_conversations(str(request.user.id))
        serializer = ConversationSerializer(
            convs, many=True, context={"request": request},
        )
        return APIResponse.success(
            message="Conversations fetched successfully.",
            data=serializer.data,
        )


class ConversationCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=ConversationCreateSerializer)
    def post(self, request):
        data = ConversationCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        conv, created = ChatService.get_or_create_direct_conversation(
            user_a_id=str(request.user.id),
            user_b_id=str(data.validated_data["recipient_id"]),
        )
        serializer = ConversationSerializer(conv, context={"request": request})
        msg = "Conversation created." if created else "Conversation already exists."
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return APIResponse.success(message=msg, data=serializer.data, status_code=code)


class ConversationMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id: str):
        conv = ChatService.get_conversation_for_user(
            str(conversation_id), str(request.user.id),
        )
        if not conv:
            return APIResponse.error(
                message="Conversation not found or access denied.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        before = request.query_params.get("before")
        msgs = ChatService.get_messages(
            str(conversation_id), before=before,
        )
        serializer = MessageSerializer(msgs, many=True)
        return APIResponse.success(
            message="Messages fetched successfully.",
            data=serializer.data,
        )


class UserPresenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_ids = request.query_params.getlist("user_ids") or request.query_params.get("user_ids", "")
        if isinstance(user_ids, str):
            user_ids = [uid.strip() for uid in user_ids.split(",") if uid.strip()]

        if not user_ids:
            return APIResponse.success(
                message="Presence fetched successfully.",
                data={"online_users": []},
            )

        online = []
        for uid in user_ids:
            if cache.get(f"{PRESENCE_CACHE_PREFIX}{uid}"):
                online.append({"user_id": uid})

        return APIResponse.success(
            message="Presence fetched successfully.",
            data={"online_users": online},
        )

