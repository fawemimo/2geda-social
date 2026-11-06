import os

from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = "Create a default superuser from environment variables if one does not exist."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "dev.kolawole@2geda.com")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "dev.kolawole@2geda.com@1234")
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "dev.kolawole")

        if not all([email, password, username]):
            self.stdout.write(self.style.WARNING(
                "Skipping superuser creation: set DJANGO_SUPERUSER_EMAIL, "
                "DJANGO_SUPERUSER_PASSWORD, and DJANGO_SUPERUSER_USERNAME."
            ))
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.SUCCESS(
                f"Superuser with email {email} already exists. Skipping."
            ))
            return

        User.objects.create_superuser(
            email=email,
            password=password,
            username=username,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Superuser '{username}' created successfully."
        ))
