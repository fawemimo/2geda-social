"""Runtime configuration: resolution order, admin management, startup safety."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import override_settings

from config import runtime
from config.models import Setting
from config.registry import REGISTRY, manageable_specs, spec_for
from config.runtime import all_effective, get_bool, get_config, get_int, get_str


@pytest.fixture(autouse=True)
def _clear_config_cache():
    runtime.invalidate_cache()
    yield
    runtime.invalidate_cache()


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestResolutionOrder:

    def test_database_beats_django_settings_and_environment(self, monkeypatch):
        monkeypatch.setenv("OTP_TTL_SECONDS", "111")
        Setting.objects.create(key="OTP_TTL_SECONDS", value="222")
        runtime.invalidate_cache()
        with override_settings(OTP_TTL_SECONDS=333):
            assert get_config("OTP_TTL_SECONDS") == 222

    def test_django_settings_beat_environment(self, monkeypatch):
        """prod_settings already reads .env, so the settings layer sits above it."""
        monkeypatch.setenv("OTP_TTL_SECONDS", "111")
        with override_settings(OTP_TTL_SECONDS=333):
            assert get_config("OTP_TTL_SECONDS") == 333

    def test_environment_used_when_nothing_else_declares_the_key(self, monkeypatch):
        # ADS_MAX_CREATIVES is not declared in Django settings, so the
        # environment is the next layer down.
        monkeypatch.setenv("ADS_MAX_CREATIVES", "9")
        assert get_config("ADS_MAX_CREATIVES") == 9

    def test_registry_default_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("ADS_SERVE_LIMIT_MAX", raising=False)
        assert get_config("ADS_SERVE_LIMIT_MAX") == spec_for("ADS_SERVE_LIMIT_MAX").default

    def test_declared_django_setting_wins_over_environment(self, monkeypatch):
        monkeypatch.setenv("MESSAGING_PROVIDERS_SMS", "twilio")
        with override_settings(MESSAGING_PROVIDERS_SMS=""):
            # A deliberately blanked setting means "no override" and must not be
            # re-filled from the environment.
            assert get_config("MESSAGING_PROVIDERS_SMS", "") == ""

    def test_inactive_row_falls_back(self, monkeypatch):
        monkeypatch.setenv("ADS_MAX_CREATIVES", "111")
        Setting.objects.create(key="ADS_MAX_CREATIVES", value="222", is_active=False)
        runtime.invalidate_cache()
        assert get_config("ADS_MAX_CREATIVES") == 111

    def test_blank_row_falls_back(self, monkeypatch):
        monkeypatch.setenv("ADS_MAX_CREATIVES", "111")
        Setting.objects.create(key="ADS_MAX_CREATIVES", value="")
        runtime.invalidate_cache()
        assert get_config("ADS_MAX_CREATIVES") == 111

    def test_deleting_the_row_restores_the_env_value(self, monkeypatch):
        monkeypatch.setenv("ADS_MAX_CREATIVES", "111")
        row = Setting.objects.create(key="ADS_MAX_CREATIVES", value="222")
        runtime.invalidate_cache()
        assert get_config("ADS_MAX_CREATIVES") == 222
        row.delete()
        assert get_config("ADS_MAX_CREATIVES") == 111


# ---------------------------------------------------------------------------
# Start-up safety — the property that matters most
# ---------------------------------------------------------------------------

class TestStartupSafety:
    """These run WITHOUT the django_db marker: the DB is off limits."""

    def test_get_config_never_raises_without_a_database(self, monkeypatch):
        monkeypatch.setenv("ADS_MAX_CREATIVES", "321")
        assert get_config("ADS_MAX_CREATIVES") == 321

    def test_falls_back_when_the_table_does_not_exist(self, monkeypatch):
        from django.db.utils import ProgrammingError

        monkeypatch.setenv("ADS_MAX_CREATIVES", "7")
        with patch.object(
            runtime, "_db_values", side_effect=ProgrammingError("no such table")
        ):
            # Even a raising _db_values must not escape get_config.
            try:
                value = get_config("ADS_MAX_CREATIVES")
            except Exception as exc:  # pragma: no cover - guards a regression
                pytest.fail(f"get_config raised {exc!r}")
        assert value == 7

    def test_unknown_key_returns_the_supplied_default(self):
        assert get_config("TOTALLY_UNKNOWN", "fallback") == "fallback"

    def test_unavailability_backoff_expires(self, monkeypatch):
        runtime._mark_unavailable()
        assert runtime._db_values() == {}
        runtime.invalidate_cache()          # clears the back-off
        assert runtime._unavailable_until == 0.0

    def test_helpers_are_typed_and_safe(self, monkeypatch):
        monkeypatch.setenv("ADS_DEFAULT_PRIORITY", "8")
        assert get_int("ADS_DEFAULT_PRIORITY") == 8
        assert isinstance(get_str("MESSAGING_PROVIDERS"), str)
        assert get_bool("NOT_A_REAL_FLAG", False) is False

    def test_bad_value_falls_back_instead_of_crashing(self, monkeypatch):
        monkeypatch.setenv("ADS_MAX_CREATIVES", "not-a-number")
        assert get_config("ADS_MAX_CREATIVES", 10) == 10


# ---------------------------------------------------------------------------
# Secrets stay in the environment
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSecretsAreEnvOnly:

    @pytest.mark.parametrize(
        "key",
        ["PAYSTACK_SECRET_KEY", "RESEND_API_KEY", "TWILIO_AUTH_TOKEN",
         "AWS_SECRET_ACCESS_KEY", "FLUTTERWAVE_SECRET_HASH"],
    )
    def test_secret_cannot_be_stored(self, key):
        with pytest.raises(ValidationError) as exc:
            Setting.objects.create(key=key, value="leaked")
        assert "secret" in str(exc.value).lower() or "api key" in str(exc.value).lower()

    def test_secret_is_read_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("EBULKSMS_APIKEY", "secret_value")
        assert get_str("EBULKSMS_APIKEY") == "secret_value"

    def test_a_stray_secret_row_is_still_ignored(self, monkeypatch):
        """Even if a row is forced in past validation, reads skip the DB."""
        Setting.objects.bulk_create(
            [Setting(key="EBULKSMS_APIKEY", value="from_db", value_type="string")]
        )
        runtime.invalidate_cache()
        monkeypatch.setenv("EBULKSMS_APIKEY", "from_env")
        assert get_str("EBULKSMS_APIKEY") == "from_env"

    def test_all_effective_masks_secrets(self, monkeypatch):
        monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_live_supersecret")
        report = all_effective()
        assert report["PAYSTACK_SECRET_KEY"]["value"] == "********"
        assert report["PAYSTACK_SECRET_KEY"]["env_only"] is True


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSettingModel:

    def test_unknown_key_is_rejected(self):
        with pytest.raises(ValidationError, match="Unknown setting"):
            Setting.objects.create(key="MADE_UP_KEY", value="1")

    def test_key_is_upper_cased(self):
        row = Setting.objects.create(key="otp_ttl_seconds", value="120")
        assert row.key == "OTP_TTL_SECONDS"

    def test_type_and_category_come_from_the_registry(self):
        row = Setting.objects.create(key="OTP_TTL_SECONDS", value="120")
        spec = spec_for("OTP_TTL_SECONDS")
        assert row.value_type == spec.value_type
        assert row.category == spec.category

    def test_invalid_value_for_the_type_is_rejected(self):
        with pytest.raises(ValidationError, match="valid integer"):
            Setting.objects.create(key="OTP_TTL_SECONDS", value="soon")

    def test_duplicate_keys_are_rejected(self):
        Setting.objects.create(key="OTP_TTL_SECONDS", value="120")
        with pytest.raises(ValidationError):
            Setting.objects.create(key="OTP_TTL_SECONDS", value="130")

    @pytest.mark.parametrize(
        "raw,value_type,expected",
        [
            ("42", "integer", 42),
            ("true", "boolean", True),
            ("off", "boolean", False),
            ('{"a": 1}', "json", {"a": 1}),
            ("a, b ,c", "csv", ["a", "b", "c"]),
            ("plain", "string", "plain"),
            (42, "integer", 42),          # already typed (a Django setting)
            (["x", "y"], "csv", ["x", "y"]),
        ],
    )
    def test_casting(self, raw, value_type, expected):
        assert Setting.cast(raw, value_type) == expected


# ---------------------------------------------------------------------------
# Cache + management command
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCacheAndSync:

    def test_saving_a_setting_invalidates_the_cache(self, monkeypatch):
        monkeypatch.setenv("ADS_MAX_CREATIVES", "111")
        assert get_config("ADS_MAX_CREATIVES") == 111
        Setting.objects.create(key="ADS_MAX_CREATIVES", value="222")
        # No manual invalidation: the post_save signal must have done it.
        assert get_config("ADS_MAX_CREATIVES") == 222

    def test_sync_config_seeds_missing_rows(self):
        call_command("sync_config", verbosity=0)
        created = set(Setting.objects.values_list("key", flat=True))
        assert created == {spec.key for spec in manageable_specs()}

    def test_sync_config_never_overwrites(self):
        Setting.objects.create(key="OTP_TTL_SECONDS", value="999")
        call_command("sync_config", verbosity=0)
        assert Setting.objects.get(key="OTP_TTL_SECONDS").value == "999"

    def test_sync_config_creates_no_secret_rows(self):
        call_command("sync_config", verbosity=0)
        keys = set(Setting.objects.values_list("key", flat=True))
        secrets = {k for k, s in REGISTRY.items() if s.env_only}
        assert keys & secrets == set()

    def test_all_effective_reports_the_source(self, monkeypatch):
        monkeypatch.setenv("ADS_SERVE_LIMIT_MAX", "4")
        Setting.objects.create(key="OTP_TTL_SECONDS", value="222")
        runtime.invalidate_cache()
        report = all_effective()
        assert report["OTP_TTL_SECONDS"]["source"] == "database"
        assert report["ADS_SERVE_LIMIT_MAX"]["source"] == "environment"


# ---------------------------------------------------------------------------
# No public surface
# ---------------------------------------------------------------------------

class TestNoEndpoints:

    def test_the_app_exposes_no_urls(self):
        import importlib
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("config.urls")

    def test_config_is_not_mounted_in_the_url_conf(self):
        from django.urls import get_resolver

        def walk(patterns, prefix=""):
            out = []
            for p in patterns:
                if hasattr(p, "url_patterns"):
                    out += walk(p.url_patterns, prefix + str(p.pattern))
                else:
                    out.append(prefix + str(p.pattern))
            return out

        routes = walk(get_resolver().url_patterns)
        api_routes = [r for r in routes if r.startswith("api/") and "config" in r]
        assert api_routes == []


@pytest.mark.django_db
class TestAdminIsTheManagementSurface:

    def test_setting_is_registered_in_the_admin(self):
        from django.contrib import admin

        assert Setting in admin.site._registry

    def test_key_is_read_only_once_created(self):
        from django.contrib import admin

        model_admin = admin.site._registry[Setting]
        row = Setting.objects.create(key="OTP_TTL_SECONDS", value="120")
        assert "key" in model_admin.get_readonly_fields(request=None, obj=row)
        assert "key" not in model_admin.get_readonly_fields(request=None, obj=None)


# ---------------------------------------------------------------------------
# Admin pages must actually render
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdminRenders:
    """Exercises the real admin views.

    The previous version of this admin called `format_html()` with constant
    markup and no interpolation arguments, which raises TypeError on modern
    Django. Unit-testing the display methods in isolation would not have caught
    it — only requesting the page does.
    """

    @pytest.fixture
    def staff_client(self, django_user_model):
        from rest_framework.test import APIClient

        # is_active defaults to False on this project's User (set after OTP),
        # and the admin redirects inactive users to the login page.
        admin_user = django_user_model.objects.create(
            username="cfgadmin", email="cfgadmin@example.com",
            is_staff=True, is_superuser=True, is_active=True,
        )
        client = APIClient()
        client.force_login(admin_user)
        return client

    def test_changelist_renders_with_no_rows(self, staff_client):
        resp = staff_client.get("/admin/config/setting/")
        assert resp.status_code == 200

    def test_changelist_renders_with_rows(self, staff_client):
        # One row with a value, one blank -> exercises both display branches.
        Setting.objects.create(key="OTP_TTL_SECONDS", value="1200")
        Setting.objects.create(key="ADS_MAX_CREATIVES", value="")
        resp = staff_client.get("/admin/config/setting/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "OTP_TTL_SECONDS" in body
        assert "(from .env)" in body      # blank-value branch
        assert "database" in body         # source_hint branch

    def test_changelist_renders_an_inactive_row(self, staff_client):
        Setting.objects.create(key="OTP_TTL_SECONDS", value="1200", is_active=False)
        assert staff_client.get("/admin/config/setting/").status_code == 200

    def test_change_form_renders(self, staff_client):
        row = Setting.objects.create(key="OTP_TTL_SECONDS", value="1200")
        resp = staff_client.get(f"/admin/config/setting/{row.pk}/change/")
        assert resp.status_code == 200
        assert "Default:" in resp.content.decode()   # the guidance panel

    def test_change_form_renders_for_a_restart_required_setting(self, staff_client):
        """Exercises the nested markup branch inside guidance()."""
        from config import registry

        spec = registry.spec_for("STORAGE_PROVIDER")
        patched = registry.SettingSpec(
            key=spec.key, category=spec.category, value_type=spec.value_type,
            default=spec.default, help_text=spec.help_text,
            env_only=spec.env_only, requires_restart=True,
        )
        row = Setting.objects.create(key="STORAGE_PROVIDER", value="azure")
        with patch.dict(registry.REGISTRY, {"STORAGE_PROVIDER": patched}):
            resp = staff_client.get(f"/admin/config/setting/{row.pk}/change/")
        assert resp.status_code == 200
        assert "Workers must be restarted" in resp.content.decode()

    def test_add_form_renders(self, staff_client):
        assert staff_client.get("/admin/config/setting/add/").status_code == 200

    def test_search_and_filter_render(self, staff_client):
        Setting.objects.create(key="OTP_TTL_SECONDS", value="1200")
        assert staff_client.get(
            "/admin/config/setting/?q=OTP"
        ).status_code == 200
        assert staff_client.get(
            "/admin/config/setting/?category=OTP+%26+Authentication"
        ).status_code == 200

    def test_admin_actions_run(self, staff_client):
        row = Setting.objects.create(key="OTP_TTL_SECONDS", value="1200")
        for action in ("deactivate", "activate", "reset_to_env"):
            resp = staff_client.post(
                "/admin/config/setting/",
                {"action": action, "_selected_action": [str(row.pk)]},
                follow=True,
            )
            assert resp.status_code == 200, action
        row.refresh_from_db()
        assert row.value == ""       # reset_to_env cleared it
