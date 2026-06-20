from __future__ import annotations

from rest_framework import serializers

from accounts.models import User
from polls.enums import PollType
from polls.models import Poll, PollOption, Vote


class PollOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PollOption
        fields = ["id", "text", "position", "vote_count"]


class PollOptionCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500)


class VoterSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source="profile.display_name", read_only=True, default="")
    avatar = serializers.CharField(source="profile.avatar.cdn_url", read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "avatar"]


class VoteSerializer(serializers.ModelSerializer):
    voter = VoterSerializer(read_only=True)
    option_id = serializers.UUIDField(source="option.id", read_only=True)
    option_text = serializers.CharField(source="option.text", read_only=True)

    class Meta:
        model = Vote
        fields = ["id", "voter", "option_id", "option_text", "created_at"]


class PollListSerializer(serializers.ModelSerializer):
    author = serializers.UUIDField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)
    options_count = serializers.IntegerField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    media_url = serializers.CharField(source="media.cdn_url", read_only=True, allow_null=True)
    media_type = serializers.CharField(source="media.media_type", read_only=True, allow_null=True)
    has_voted = serializers.SerializerMethodField()

    class Meta:
        model = Poll
        fields = [
            "id", "author", "author_username", "question", "poll_type", "status",
            "starts_at", "ends_at", "media_url", "media_type",
            "show_results", "show_voters", "show_vote_counts", "show_view_counts",
            "total_votes", "total_views", "options_count",
            "is_active", "is_expired", "has_voted",
            "created_at", "updated_at",
        ]

    def get_has_voted(self, obj) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.votes.filter(voter=request.user).exists()
        return False


class PollDetailSerializer(PollListSerializer):
    options = PollOptionSerializer(many=True, read_only=True)
    recent_voters = serializers.SerializerMethodField()

    class Meta(PollListSerializer.Meta):
        fields = PollListSerializer.Meta.fields + ["options", "recent_voters"]

    def get_recent_voters(self, obj):
        request = self.context.get("request")
        show = obj.show_voters or (request and request.user == obj.author)
        if not show:
            return []
        voters = (
            Vote.objects.filter(poll=obj)
            .select_related("voter")
            .order_by("-created_at")[:10]
        )
        return VoterSerializer([v.voter for v in voters], many=True).data


class PollCreateSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500)
    poll_type = serializers.ChoiceField(
        choices=PollType.choices(),
        default=PollType.SINGLE_CHOICE.value,
        required=False,
    )
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    media_id = serializers.UUIDField(required=False, allow_null=True)
    show_results = serializers.BooleanField(default=True, required=False)
    show_voters = serializers.BooleanField(default=False, required=False)
    show_vote_counts = serializers.BooleanField(default=True, required=False)
    show_view_counts = serializers.BooleanField(default=True, required=False)
    options = serializers.ListField(
        child=serializers.CharField(max_length=500),
        min_length=2,
    )


class PollUpdateSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500, required=False)
    poll_type = serializers.ChoiceField(
        choices=PollType.choices(),
        required=False,
    )
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    media_id = serializers.UUIDField(required=False, allow_null=True)
    show_results = serializers.BooleanField(required=False)
    show_voters = serializers.BooleanField(required=False)
    show_vote_counts = serializers.BooleanField(required=False)
    show_view_counts = serializers.BooleanField(required=False)
    options = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
    )


class VoteCreateSerializer(serializers.Serializer):
    option_id = serializers.UUIDField()


class PollResultSerializer(serializers.ModelSerializer):
    options = PollOptionSerializer(many=True, read_only=True)
    total_votes = serializers.IntegerField(read_only=True)
    total_views = serializers.IntegerField(read_only=True)
    voters = serializers.SerializerMethodField()

    class Meta:
        model = Poll
        fields = [
            "id", "question", "poll_type", "status",
            "options", "total_votes", "total_views",
            "voters", "created_at", "ends_at",
        ]

    def get_voters(self, obj):
        request = self.context.get("request")
        if obj.show_voters or (request and request.user == obj.author):
            votes = (
                Vote.objects.filter(poll=obj)
                .select_related("voter", "option")
                .order_by("-created_at")
            )
            return VoteSerializer(votes, many=True).data
        return []
