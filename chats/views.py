from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.db import models
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.models import User
from chats.models import Conversation, ConversationMember, JoinRequest, Message
from chats.serializers import (
    ConversationCreateSerializer,
    ConversationSerializer,
    GroupCreateSerializer,
    GroupMemberActionSerializer,
    GroupTargetMemberSerializer,
    JoinRequestSerializer,
    MediaSearchSerializer,
    MessageSerializer,
    PromoteToAdminSerializer,
    UserSearchSerializer,
)
from chats.services import ChatService
from utils.responses import APIResponse

PRESENCE_CACHE_PREFIX = "online_user:"

logger = logging.getLogger(__name__)


def _broadcast_group_event(conversation_id: str, event: dict) -> None:
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"chat_{conversation_id}",
            event,
        )
    except Exception:
        logger.exception("Failed to broadcast group event")


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


class GroupCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=GroupCreateSerializer)
    def post(self, request):
        data = GroupCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        try:
            conv = ChatService.create_group_conversation(
                creator_id=str(request.user.id),
                name=data.validated_data["name"],
                description=data.validated_data.get("description", ""),
                member_ids=[str(uid) for uid in data.validated_data["member_ids"]],
            )
        except ValueError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ConversationSerializer(conv, context={"request": request})
        return APIResponse.success(
            message="Group conversation created.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class GroupManageMembersView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: str):
        """Add members to a group (admin/owner only)."""
        data = GroupMemberActionSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        try:
            conv = ChatService.add_group_members(
                conversation_id=str(conversation_id),
                actor_id=str(request.user.id),
                member_ids=[str(uid) for uid in data.validated_data["member_ids"]],
            )
        except Conversation.DoesNotExist:
            return APIResponse.error(
                message="Conversation not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ConversationSerializer(conv, context={"request": request})
        _broadcast_group_event(
            str(conversation_id),
            {
                "type": "group_members_updated",
                "conversation_id": str(conversation_id),
                "action": "added",
                "member_ids": [str(uid) for uid in data.validated_data["member_ids"]],
            },
        )
        return APIResponse.success(
            message="Members added successfully.",
            data=serializer.data,
        )

    def delete(self, request, conversation_id: str):
        """Remove a member from a group (admin/owner only)."""
        data = GroupTargetMemberSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        target_user_id = str(data.validated_data["user_id"])

        try:
            conv = ChatService.remove_group_member(
                conversation_id=str(conversation_id),
                actor_id=str(request.user.id),
                target_user_id=target_user_id,
            )
        except ConversationMember.DoesNotExist:
            return APIResponse.error(
                message="Target user is not a member.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )

        serializer = ConversationSerializer(conv, context={"request": request})
        _broadcast_group_event(
            str(conversation_id),
            {
                "type": "member_removed",
                "conversation_id": str(conversation_id),
                "user_id": target_user_id,
                "removed_by_id": str(request.user.id),
            },
        )
        return APIResponse.success(
            message="Member removed successfully.",
            data=serializer.data,
        )


class GroupLockToggleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: str):
        """Toggle lock/unlock for a group (admin/owner only)."""
        try:
            conv = ChatService.toggle_group_lock(
                conversation_id=str(conversation_id),
                actor_id=str(request.user.id),
            )
        except Conversation.DoesNotExist:
            return APIResponse.error(
                message="Conversation not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )

        serializer = ConversationSerializer(conv, context={"request": request})
        event_type = "group_locked" if conv.is_locked else "group_unlocked"
        _broadcast_group_event(
            str(conversation_id),
            {
                "type": event_type,
                "conversation_id": str(conversation_id),
                "is_locked": conv.is_locked,
                "locked_by_id": str(request.user.id),
            },
        )
        msg = "Group locked." if conv.is_locked else "Group unlocked."
        return APIResponse.success(message=msg, data=serializer.data)


class MessageDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, message_id: str):
        """Delete a message. Admin can delete any message in a group."""
        try:
            msg = ChatService.delete_message(
                message_id=str(message_id),
                actor_id=str(request.user.id),
            )
        except Message.DoesNotExist:
            return APIResponse.error(
                message="Message not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )

        _broadcast_group_event(
            str(msg.conversation_id),
            {
                "type": "message_deleted",
                "message_id": str(msg.id),
                "conversation_id": str(msg.conversation_id),
                "deleted_by_id": str(request.user.id),
            },
        )
        return APIResponse.success(message="Message deleted.")


class GroupJoinRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: str):
        """Request to join a group (non-members only)."""
        try:
            join_req = ChatService.request_to_join_group(
                conversation_id=str(conversation_id),
                user_id=str(request.user.id),
            )
        except Conversation.DoesNotExist:
            return APIResponse.error(
                message="Conversation not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )

        serializer = JoinRequestSerializer(join_req)
        _broadcast_group_event(
            str(conversation_id),
            {
                "type": "join_request_created",
                "conversation_id": str(conversation_id),
                "join_request_id": str(join_req.id),
                "user_id": str(request.user.id),
                "username": request.user.username,
            },
        )
        return APIResponse.success(
            message="Join request submitted. Waiting for admin approval.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class GroupJoinRequestListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id: str):
        """List pending join requests (admin/owner only)."""
        try:
            requests = ChatService.get_pending_join_requests(
                conversation_id=str(conversation_id),
                user_id=str(request.user.id),
            )
        except PermissionError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )

        serializer = JoinRequestSerializer(requests, many=True)
        return APIResponse.success(
            message="Pending join requests fetched.",
            data=serializer.data,
        )


class GroupJoinRequestProcessView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: str, request_id: str):
        """Approve a join request (admin/owner only)."""
        action = request.query_params.get("action", "approve")

        try:
            if action == "approve":
                join_req = ChatService.approve_join_request(
                    request_id=str(request_id),
                    actor_id=str(request.user.id),
                )
                msg = "Join request approved."
            else:
                join_req = ChatService.reject_join_request(
                    request_id=str(request_id),
                    actor_id=str(request.user.id),
                )
                msg = "Join request rejected."
        except JoinRequest.DoesNotExist:
            return APIResponse.error(
                message="Join request not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )

        serializer = JoinRequestSerializer(join_req)

        event_type = "join_request_approved" if action == "approve" else "join_request_rejected"
        _broadcast_group_event(
            str(conversation_id),
            {
                "type": event_type,
                "conversation_id": str(conversation_id),
                "join_request_id": str(request_id),
                "user_id": str(join_req.user_id),
                "processed_by_id": str(request.user.id),
            },
        )
        return APIResponse.success(message=msg, data=serializer.data)


class GroupPromoteAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id: str):
        """Promote a member to admin (admin/owner only)."""
        data = PromoteToAdminSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        try:
            member = ChatService.promote_to_admin(
                conversation_id=str(conversation_id),
                actor_id=str(request.user.id),
                target_user_id=str(data.validated_data["user_id"]),
            )
        except ConversationMember.DoesNotExist:
            return APIResponse.error(
                message="Member not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as e:
            return APIResponse.error(
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        _broadcast_group_event(
            str(conversation_id),
            {
                "type": "member_promoted",
                "conversation_id": str(conversation_id),
                "user_id": str(member.user_id),
                "new_role": member.role,
                "promoted_by_id": str(request.user.id),
            },
        )
        return APIResponse.success(
            message="Member promoted to admin.",
            data={"user_id": str(member.user_id), "role": member.role},
        )


class ChatSearchMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return APIResponse.success(
                message="Search messages fetched.",
                data=[],
            )

        conversation_id = request.query_params.get("conversation_id")
        msgs = ChatService.search_messages(
            user_id=str(request.user.id),
            query=query,
            conversation_id=str(conversation_id) if conversation_id else None,
        )
        serializer = MessageSerializer(msgs, many=True)
        return APIResponse.success(
            message="Messages search completed.",
            data=serializer.data,
        )


class ChatSearchConversationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return APIResponse.success(
                message="Search conversations fetched.",
                data=[],
            )

        convs = ChatService.search_conversations(
            user_id=str(request.user.id),
            query=query,
        )
        serializer = ConversationSerializer(convs, many=True, context={"request": request})
        return APIResponse.success(
            message="Conversations search completed.",
            data=serializer.data,
        )


class ChatSearchUsersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return APIResponse.success(
                message="Search users fetched.",
                data=[],
            )

        users = User.objects.filter(
            models.Q(username__icontains=query)
            | models.Q(email__icontains=query)
            | models.Q(profile__display_name__icontains=query),
            is_active=True,
        ).select_related("profile__avatar").distinct()[:20]

        serializer = UserSearchSerializer(users, many=True)
        return APIResponse.success(
            message="Users search completed.",
            data=serializer.data,
        )


class ChatSearchMediaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return APIResponse.success(
                message="Search media fetched.",
                data=[],
            )

        media_type = request.query_params.get("media_type", "").strip() or None
        msgs = ChatService.search_media(
            user_id=str(request.user.id),
            query=query,
            media_type=media_type,
        )
        serializer = MediaSearchSerializer(msgs, many=True)
        return APIResponse.success(
            message="Media search completed.",
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
