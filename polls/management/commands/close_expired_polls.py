from __future__ import annotations

from django.core.management.base import BaseCommand

from polls.tasks import close_expired_polls as close_polls_task


class Command(BaseCommand):
    help = "Close polls whose ends_at has passed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print matching polls without closing them.",
        )

    def handle(self, *args, **options):
        from django.utils import timezone

        from polls.enums import PollStatus
        from polls.models import Poll

        now = timezone.now()
        expired_qs = Poll.objects.filter(
            ends_at__lte=now,
            status=PollStatus.ACTIVE.value,
            is_deleted=False,
        )
        count = expired_qs.count()

        if options["dry_run"]:
            self.stdout.write(f"Would close {count} expired poll(s).")
            return

        result = close_polls_task()
        self.stdout.write(f"Closed {result['closed_count']} expired poll(s).")
