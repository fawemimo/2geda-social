import logging

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from accounts.models import User
from medias.models import Media
from polls.enums import PollStatus, PollType
from polls.models import Poll, PollOption, PollView, Vote
from polls.services.exceptions import (
    DuplicateVoteError,
    PollExpiredError,
    ValidationError,
    VoteAlreadyCastError,
)

logger = logging.getLogger(__name__)


class PollService:

    @staticmethod
    @transaction.atomic
    def create(*, author: User, validated_data: dict) -> Poll:
        question = validated_data.get("question")
        poll_type = validated_data.get("poll_type", PollType.SINGLE_CHOICE.value)
        ends_at = validated_data.get("ends_at")
        media_id = validated_data.get("media_id")
        show_results = validated_data.get("show_results", True)
        show_voters = validated_data.get("show_voters", False)
        show_vote_counts = validated_data.get("show_vote_counts", True)
        show_view_counts = validated_data.get("show_view_counts", True)
        options_data = validated_data.get("options", [])

        if len(options_data) < 2:
            raise ValidationError("A poll must have at least 2 options.")

        if ends_at and ends_at <= timezone.now():
            raise ValidationError("ends_at must be in the future.")

        poll = Poll.objects.create(
            author=author,
            question=question,
            poll_type=poll_type,
            ends_at=ends_at,
            show_results=show_results,
            show_voters=show_voters,
            show_vote_counts=show_vote_counts,
            show_view_counts=show_view_counts,
        )

        if media_id:
            try:
                media = Media.objects.get(pk=media_id, owner=author)
                poll.media = media
                poll.save(update_fields=["media"])
            except Media.DoesNotExist:
                raise ValidationError(f"Media {media_id} not found or not owned by you.")

        PollService._create_options(poll, options_data)
        poll.refresh_from_db()
        return poll

    @staticmethod
    @transaction.atomic
    def update(*, instance: Poll, validated_data: dict) -> Poll:
        if instance.status == PollStatus.CLOSED.value:
            raise ValidationError("Cannot update a closed poll.")

        updatable_fields = [
            "question", "poll_type", "ends_at", "show_results",
            "show_voters", "show_vote_counts", "show_view_counts",
        ]
        for field in updatable_fields:
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        media_id = validated_data.get("media_id")
        if media_id is not None:
            try:
                media = Media.objects.get(pk=media_id, owner=instance.author)
                instance.media = media
            except Media.DoesNotExist:
                raise ValidationError(f"Media {media_id} not found or not owned by you.")
        elif "media_id" in validated_data:
            instance.media = None

        options_data = validated_data.get("options")
        if options_data is not None:
            instance.options.all().delete()
            PollService._create_options(instance, options_data)

        if validated_data.get("ends_at") and instance.ends_at and instance.ends_at <= timezone.now():
            raise ValidationError("ends_at must be in the future.")

        instance.save()
        return instance

    @staticmethod
    @transaction.atomic
    def delete(*, instance: Poll) -> None:
        instance.delete()

    @staticmethod
    @transaction.atomic
    def close(*, instance: Poll) -> Poll:
        instance.status = PollStatus.CLOSED.value
        instance.ends_at = timezone.now()
        instance.save(update_fields=["status", "ends_at", "updated_at"])
        return instance

    @staticmethod
    @transaction.atomic
    def cast_vote(*, poll: Poll, option_id: str, voter: User) -> Vote:
        poll = Poll.objects.select_for_update().get(pk=poll.pk)

        if poll.is_expired:
            raise PollExpiredError()
        if not poll.is_active:
            raise PollExpiredError("This poll is not active.")

        try:
            option = PollOption.objects.select_for_update().get(pk=option_id, poll=poll)
        except PollOption.DoesNotExist:
            raise ValidationError("Option not found in this poll.")

        if poll.poll_type == PollType.SINGLE_CHOICE.value:
            if Vote.objects.filter(poll=poll, voter=voter).exists():
                raise VoteAlreadyCastError()
        else:
            if Vote.objects.filter(option=option, voter=voter).exists():
                raise DuplicateVoteError()

        Vote.objects.create(poll=poll, option=option, voter=voter)

        PollOption.objects.filter(pk=option.pk).update(vote_count=F("vote_count") + 1)
        Poll.objects.filter(pk=poll.pk).update(total_votes=F("total_votes") + 1)

        option.refresh_from_db()
        poll.refresh_from_db()

        return Vote.objects.get(poll=poll, option=option, voter=voter)

    @staticmethod
    @transaction.atomic
    def remove_vote(*, poll: Poll, voter: User) -> None:
        poll = Poll.objects.select_for_update().get(pk=poll.pk)

        if poll.poll_type == PollType.SINGLE_CHOICE.value:
            deleted, _ = Vote.objects.filter(poll=poll, voter=voter).delete()
        else:
            raise ValidationError(
                "Specify the option_id to remove a vote from a multiple-choice poll."
            )

        if deleted:
            Poll.objects.filter(pk=poll.pk).update(
                total_votes=Greatest(F("total_votes") - deleted, 0),
            )

    @staticmethod
    @transaction.atomic
    def remove_option_vote(*, poll: Poll, option_id: str, voter: User) -> None:
        poll = Poll.objects.select_for_update().get(pk=poll.pk)
        try:
            option = PollOption.objects.select_for_update().get(pk=option_id, poll=poll)
        except PollOption.DoesNotExist:
            raise ValidationError("Option not found in this poll.")

        deleted, _ = Vote.objects.filter(option=option, voter=voter).delete()
        if deleted:
            PollOption.objects.filter(pk=option.pk).update(
                vote_count=Greatest(F("vote_count") - 1, 0),
            )
            Poll.objects.filter(pk=poll.pk).update(
                total_votes=Greatest(F("total_votes") - 1, 0),
            )

    @staticmethod
    def record_view(*, poll: Poll, viewer: User | None, ip_address: str | None = None) -> None:
        if viewer:
            if PollView.objects.filter(poll=poll, viewer=viewer).exists():
                return
        PollView.objects.create(poll=poll, viewer=viewer, ip_address=ip_address)
        Poll.objects.filter(pk=poll.pk).update(total_views=F("total_views") + 1)

    @staticmethod
    def _create_options(poll: Poll, options_data: list[dict | str]) -> list[PollOption]:
        options = []
        for idx, opt in enumerate(options_data):
            if isinstance(opt, dict):
                text = opt.get("text", "")
            else:
                text = str(opt)
            if not text or not text.strip():
                continue
            options.append(PollOption(poll=poll, text=text.strip(), position=idx))

        created = PollOption.objects.bulk_create(options)
        Poll.objects.filter(pk=poll.pk).update(options_count=len(created))
        return created

    @staticmethod
    def get_options_data(poll: Poll) -> list[dict]:
        return list(
            poll.options.values("id", "text", "vote_count", "position").order_by("position")
        )
