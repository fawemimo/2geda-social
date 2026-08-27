from __future__ import annotations

import os

from django.core.management.base import BaseCommand

from config.models import Setting
from config.registry import manageable_specs
from config.runtime import invalidate_cache


class Command(BaseCommand):
    help = "Create missing config.Setting rows from the registry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would be created without writing.",
        )
        parser.add_argument(
            "--prune", action="store_true",
            help="Delete rows whose key is no longer in the registry.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        specs = manageable_specs()
        existing = set(Setting.objects.values_list("key", flat=True))

        created = 0
        for spec in specs:
            if spec.key in existing:
                continue
            env_value = os.getenv(spec.key)
            value = env_value if env_value not in (None, "") else ""
            if dry_run:
                self.stdout.write(f"  would create {spec.key} = {value!r}")
            else:
                Setting.objects.create(
                    key=spec.key,
                    value=str(value),
                    value_type=spec.value_type,
                    category=spec.category,
                    description=spec.help_text,
                )
            created += 1

        pruned = 0
        if options["prune"]:
            known = {spec.key for spec in specs}
            stale = Setting.objects.exclude(key__in=known)
            pruned = stale.count()
            if not dry_run:
                stale.delete()

        if not dry_run:
            invalidate_cache()

        verb = "Would create" if dry_run else "Created"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {created} setting(s); {len(specs) - created} already present."
            + (f" Pruned {pruned}." if options["prune"] else "")
        ))
