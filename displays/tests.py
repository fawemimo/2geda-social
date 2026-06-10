import pytest
from django.utils import timezone
from datetime import timedelta

from accounts.models import User
from displays.models import Display
from displays.tasks import hard_delete_expired_displays

pytestmark = pytest.mark.django_db


class TestHardDeleteExpiredDisplays:

    def test_hard_deletes_expired_only(self):
        user = User.objects.create_user(
            email="t@t.com", username="tester", password="pass", is_active=True,
        )
        expired = Display.objects.create(
            author=user, body="Expired",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        active = Display.objects.create(
            author=user, body="Active",
            expires_at=timezone.now() + timedelta(hours=23),
        )

        result = hard_delete_expired_displays()

        assert result["deleted_count"] == 1
        assert not Display.objects.filter(pk=expired.pk).exists()
        assert Display.objects.filter(pk=active.pk, is_deleted=False).exists()

    def test_skips_when_none_expired(self):
        user = User.objects.create_user(
            email="t@t.com", username="tester", password="pass", is_active=True,
        )
        Display.objects.create(
            author=user, body="Fresh",
            expires_at=timezone.now() + timedelta(hours=23),
        )

        result = hard_delete_expired_displays()

        assert result["deleted_count"] == 0

    def test_handles_multiple_expired(self):
        user = User.objects.create_user(
            email="t@t.com", username="tester", password="pass", is_active=True,
        )
        for i in range(5):
            Display.objects.create(
                author=user, body=f"Expired {i}",
                expires_at=timezone.now() - timedelta(hours=1),
            )

        result = hard_delete_expired_displays()

        assert result["deleted_count"] == 5
        assert Display.objects.count() == 0
