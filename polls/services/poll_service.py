import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from accounts.models import User
from clients.payments import PaymentGateway, PaymentError
from medias.models import Media
from polls.enums import PollStatus, PollType
from polls.models import (
    SERVICE_CHARGE_PERCENT,
    Poll,
    PollOption,
    PollPayout,
    PollView,
    Vote,
    VotePayment,
)
from polls.services.exceptions import (
    DuplicateVoteError,
    PollExpiredError,
    ValidationError,
    VoteAlreadyCastError,
)
from utils.enum import PaymentStatus
from utils.generators import generate_poll_payout_reference, generate_vote_payment_reference

logger = logging.getLogger(__name__)


class PollService:

    @staticmethod
    @transaction.atomic
    def create(*, author: User, validated_data: dict) -> Poll:
        question = validated_data.get("question")
        poll_type = validated_data.get("poll_type", PollType.SINGLE_CHOICE.value)
        ends_at = validated_data.get("ends_at")
        media_id = validated_data.get("media_id")
        is_paid_voting = validated_data.get("is_paid_voting", False)
        vote_price = validated_data.get("vote_price", 0)
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
            is_paid_voting=is_paid_voting,
            vote_price=vote_price if is_paid_voting else 0,
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

        if instance.total_votes > 0 and "is_paid_voting" in validated_data:
            raise ValidationError("Cannot change voting type after votes have been cast.")

        updatable_fields = [
            "question", "poll_type", "ends_at", "is_paid_voting", "vote_price",
            "show_results", "show_voters", "show_vote_counts", "show_view_counts",
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

    # ── Paid voting ─────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def initialize_vote_payment(
        *, poll: Poll, option_id: str, voter: User, quantity: int = 1
    ) -> VotePayment:
        if not poll.is_paid_voting:
            raise ValidationError("This poll does not require payment to vote.")
        if poll.is_expired:
            raise PollExpiredError()
        if not poll.is_active:
            raise PollExpiredError("This poll is not active.")

        try:
            option = PollOption.objects.get(pk=option_id, poll=poll)
        except PollOption.DoesNotExist:
            raise ValidationError("Option not found in this poll.")

        amount = poll.vote_price * quantity
        charge = amount * SERVICE_CHARGE_PERCENT
        net = amount - charge
        reference = generate_vote_payment_reference()

        gateway = PaymentGateway()
        try:
            result = gateway.initialize(
                email=voter.email,
                amount=amount,
                reference=reference,
                metadata={
                    "poll_id": str(poll.id),
                    "option_id": str(option.id),
                    "voter_id": str(voter.id),
                    "quantity": quantity,
                    "type": "poll_vote",
                },
            )
        except PaymentError as exc:
            logger.exception("Vote payment init failed: %s", exc)
            raise ValidationError("Payment initialization failed. Please try again.")

        return VotePayment.objects.create(
            poll=poll,
            voter=voter,
            option=option,
            quantity=quantity,
            amount=amount,
            service_charge=charge,
            net_amount=net,
            reference=result.reference,
            authorization_url=result.authorization_url,
            provider_data=result.raw,
        )

    @staticmethod
    @transaction.atomic
    def verify_vote_payment(*, reference: str, voter: User) -> list[Vote]:
        try:
            payment = VotePayment.objects.select_for_update().get(
                reference=reference, voter=voter,
            )
        except VotePayment.DoesNotExist:
            raise ValidationError("Payment reference not found.")

        if payment.status == PaymentStatus.SUCCESSFUL.value:
            existing = list(payment.votes.all())
            if existing:
                return existing
            raise ValidationError("Payment already verified but votes not recorded.")

        poll = Poll.objects.select_for_update().get(pk=payment.poll_id)
        if poll.is_expired:
            raise PollExpiredError()

        gateway = PaymentGateway()
        try:
            verification = gateway.verify(reference)
        except PaymentError as exc:
            logger.exception("Vote payment verification failed: %s", exc)
            raise ValidationError("Payment verification failed.")

        if not verification.is_successful:
            payment.status = PaymentStatus.FAILED.value
            payment.provider_data = verification.raw
            payment.save(update_fields=["status", "provider_data"])
            raise ValidationError("Payment was not successful.")

        payment.status = PaymentStatus.SUCCESSFUL.value
        payment.provider_data = verification.raw
        payment.save(update_fields=["status", "provider_data"])

        option = PollOption.objects.select_for_update().get(pk=payment.option_id)
        votes = Vote.objects.bulk_create([
            Vote(poll=poll, option=option, voter=voter, is_paid=True, payment=payment)
            for _ in range(payment.quantity)
        ])

        PollOption.objects.filter(pk=option.pk).update(
            vote_count=F("vote_count") + payment.quantity,
        )
        Poll.objects.filter(pk=poll.pk).update(
            total_votes=F("total_votes") + payment.quantity,
        )

        return votes

    @staticmethod
    def get_poll_analytics(*, poll: Poll) -> dict:
        total_paid = Vote.objects.filter(poll=poll, is_paid=True).count()
        total_free = poll.total_votes - total_paid
        gross = Decimal(str(poll.vote_price)) * total_paid
        charge = gross * SERVICE_CHARGE_PERCENT
        net = gross - charge

        payout = PollPayout.objects.filter(poll=poll).order_by("-created_at").first()

        return {
            "poll_id": poll.id,
            "question": poll.question,
            "total_votes": poll.total_votes,
            "total_free_votes": total_free,
            "total_paid_votes": total_paid,
            "vote_price": poll.vote_price,
            "gross_revenue": gross,
            "service_charge_percent": SERVICE_CHARGE_PERCENT * 100,
            "total_service_charge": charge,
            "net_remittance": net,
            "payout": payout,
        }

    @staticmethod
    @transaction.atomic
    def process_poll_payout(poll: Poll) -> PollPayout | None:
        if not poll.is_paid_voting:
            return None

        if PollPayout.objects.filter(poll=poll).exclude(
            status=PaymentStatus.FAILED.value
        ).exists():
            return None

        paid_payments = VotePayment.objects.filter(
            poll=poll, status=PaymentStatus.SUCCESSFUL.value,
        )
        if not paid_payments.exists():
            return None

        total_votes = sum(p.quantity for p in paid_payments)
        gross = sum(p.amount for p in paid_payments)
        charge = sum(p.service_charge for p in paid_payments)
        net = gross - charge

        return PollPayout.objects.create(
            poll=poll,
            author=poll.author,
            total_paid_votes=total_votes,
            gross_amount=gross,
            service_charge_total=charge,
            net_amount=net,
            payout_ref=generate_poll_payout_reference(),
        )
