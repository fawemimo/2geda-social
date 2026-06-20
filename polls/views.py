from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.viewsets import ModelViewSet

from accounts.services.exceptions import ServiceError
from polls.models import Poll
from polls.serializers import (
    PollCreateSerializer,
    PollDetailSerializer,
    PollListSerializer,
    PollResultSerializer,
    PollUpdateSerializer,
    VoteCreateSerializer,
)
from polls.services import PollService
from polls.services.broadcaster import broadcast_poll_event
from utils.pagination import StandardPagination
from utils.responses import APIResponse


class PollViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    pagination_message = "Polls fetched successfully."
    lookup_field = "pk"

    def get_queryset(self):
        qs = Poll.objects.filter(is_deleted=False).select_related("author", "media")
        user = self.request.user
        if user.is_authenticated:
            return qs
        return qs.filter(status="active")

    def get_serializer_class(self):
        if self.action == "create":
            return PollCreateSerializer
        if self.action in ("update", "partial_update"):
            return PollUpdateSerializer
        if self.action == "retrieve":
            return PollDetailSerializer
        if self.action == "results":
            return PollResultSerializer
        return PollListSerializer

    def perform_create(self, serializer):
        return PollService.create(author=self.request.user, validated_data=serializer.validated_data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        poll = self.perform_create(serializer)
        return APIResponse.success(
            message="Poll created successfully.",
            data=PollDetailSerializer(poll, context={"request": request}).data,
            status_code=status.HTTP_201_CREATED,
        )

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
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else request.META.get("REMOTE_ADDR")
        PollService.record_view(
            poll=instance,
            viewer=request.user if request.user.is_authenticated else None,
            ip_address=ip,
        )
        serializer = self.get_serializer(instance, context={"request": request})
        return APIResponse.success(data=serializer.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        if instance.author != request.user:
            return APIResponse.error(message="You can only update your own polls.", status_code=403)
        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        poll = PollService.update(instance=instance, validated_data=serializer.validated_data)
        return APIResponse.success(
            message="Poll updated successfully.",
            data=PollDetailSerializer(poll, context={"request": request}).data,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.author != request.user:
            return APIResponse.error(message="You can only delete your own polls.", status_code=403)
        PollService.delete(instance=instance)
        return APIResponse.success(message="Poll deleted successfully.", status_code=200)

    @action(detail=True, methods=["post"])
    def vote(self, request, pk=None):
        poll = self.get_object()
        if poll.author == request.user:
            return APIResponse.error(message="You cannot vote on your own poll.", status_code=403)
        if poll.is_expired:
            return APIResponse.error(message="This poll has expired.", status_code=400)

        serializer = VoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            vote = PollService.cast_vote(
                poll=poll,
                option_id=str(serializer.validated_data["option_id"]),
                voter=request.user,
            )
            options_data = PollService.get_options_data(poll)
            broadcast_poll_event(str(poll.id), {
                "event": "vote.update",
                "poll_id": str(poll.id),
                "option_id": str(vote.option_id),
                "voter_id": str(request.user.id),
                "options": options_data,
                "total_votes": poll.total_votes,
            })
            return APIResponse.success(
                message="Vote cast successfully.",
                data={"option_id": str(vote.option_id), "created_at": vote.created_at},
                status_code=status.HTTP_201_CREATED,
            )
        except ServiceError as e:
            return APIResponse.error(message=e.message, status_code=e.status_code)

    @action(detail=True, methods=["post"])
    def unvote(self, request, pk=None):
        poll = self.get_object()
        try:
            option_id = request.data.get("option_id")
            if option_id and poll.poll_type == "multiple_choice":
                PollService.remove_option_vote(
                    poll=poll, option_id=str(option_id), voter=request.user,
                )
            else:
                PollService.remove_vote(poll=poll, voter=request.user)
            poll.refresh_from_db()
            options_data = PollService.get_options_data(poll)
            broadcast_poll_event(str(poll.id), {
                "event": "vote.removed",
                "poll_id": str(poll.id),
                "option_id": option_id,
                "voter_id": str(request.user.id),
                "options": options_data,
                "total_votes": poll.total_votes,
            })
            return APIResponse.success(message="Vote removed successfully.")
        except ServiceError as e:
            return APIResponse.error(message=e.message, status_code=e.status_code)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        instance = self.get_object()
        if instance.author != request.user:
            return APIResponse.error(message="Only the author can close this poll.", status_code=403)
        if instance.is_expired:
            return APIResponse.error(message="Poll is already closed or expired.", status_code=400)
        poll = PollService.close(instance=instance)
        broadcast_poll_event(str(poll.id), {
            "event": "poll.closed",
            "poll_id": str(poll.id),
        })
        return APIResponse.success(
            message="Poll closed successfully.",
            data=PollDetailSerializer(poll, context={"request": request}).data,
        )

    @action(detail=True, methods=["get"])
    def results(self, request, pk=None):
        instance = self.get_object()
        if not instance.show_results and instance.author != request.user:
            return APIResponse.error(
                message="Results are not publicly available for this poll.", status_code=403,
            )
        serializer = self.get_serializer(instance, context={"request": request})
        return APIResponse.success(data=serializer.data)
