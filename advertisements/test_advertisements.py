"""Advertisement lifecycle, delivery and telemetry."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.services.exceptions import ConflictError, ValidationError
from advertisements.models import (
    AdCreative,
    AdDailyMetric,
    AdEvent,
    AdPlacement,
    Advertisement,
)
from advertisements.services import AdDeliveryService, AdEventService, AdvertisementService
from advertisements.tasks import (
    activate_due_advertisements,
    attach_ad_creatives,
    complete_expired_advertisements,
    pause_exhausted_advertisements,
)
from medias.models import Media
from utils.enum import AdEventType, AdMode, AdScreenPosition, AdStatus, ProcessingStatus

User = get_user_model()
ADS_URL = "/api/v2/advertisements/"


@pytest.fixture
def advertiser(db):
    return User.objects.create(username="brand", email="brand@example.com")


@pytest.fixture
def admin_user(db):
    return User.objects.create(
        username="moderator", email="mod@example.com", is_staff=True
    )


@pytest.fixture
def viewer(db):
    return User.objects.create(username="viewer", email="viewer@example.com")


def make_media(owner):
    return Media.objects.create(
        owner=owner,
        media_type="image",
        storage_key=f"images/{uuid.uuid4()}.jpg",
        cdn_url="https://cdn.test/ad.jpg",
        processing_status=ProcessingStatus.READY.value,
    )


def make_advert(advertiser, *, status=AdStatus.RUNNING.value, with_creative=True,
                mode=AdMode.ON_FEED_LIST.value, starts_delta=-1, ends_delta=7, **kwargs):
    now = timezone.now()
    advert = Advertisement.objects.create(
        advertiser=advertiser,
        title=kwargs.pop("title", "Big Sale"),
        status=status,
        starts_at=now + timedelta(days=starts_delta),
        ends_at=now + timedelta(days=ends_delta),
        **kwargs,
    )
    AdPlacement.objects.create(
        advertisement=advert, mode=mode,
        screen_position=AdScreenPosition.INLINE.value,
    )
    if with_creative:
        AdCreative.objects.create(advertisement=advert, media=make_media(advertiser))
    return advert


def auth(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Model / lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdvertisementLifecycle:

    def test_caption_is_optional(self, advertiser):
        advert = make_advert(advertiser)
        assert advert.caption == ""

    def test_submit_requires_a_creative(self, advertiser):
        advert = make_advert(advertiser, status=AdStatus.DRAFT.value, with_creative=False)
        with pytest.raises(ValidationError, match="at least one image"):
            AdvertisementService.submit_for_review(advert=advert)

    def test_submit_requires_a_placement(self, advertiser):
        advert = make_advert(advertiser, status=AdStatus.DRAFT.value)
        advert.placements.all().delete()
        with pytest.raises(ValidationError, match="advert mode"):
            AdvertisementService.submit_for_review(advert=advert)

    def test_happy_path_draft_to_running(self, advertiser, admin_user):
        advert = make_advert(advertiser, status=AdStatus.DRAFT.value)

        AdvertisementService.submit_for_review(advert=advert)
        assert advert.status == AdStatus.PENDING_REVIEW.value

        AdvertisementService.approve(advert=advert, reviewer=admin_user)
        advert.refresh_from_db()
        # Window is already open, so approval goes live immediately.
        assert advert.status == AdStatus.RUNNING.value
        assert advert.activated_at is not None

    def test_approval_of_a_future_advert_waits(self, advertiser, admin_user):
        advert = make_advert(
            advertiser, status=AdStatus.DRAFT.value, starts_delta=2, ends_delta=9
        )
        AdvertisementService.submit_for_review(advert=advert)
        AdvertisementService.approve(advert=advert, reviewer=admin_user)
        advert.refresh_from_db()
        assert advert.status == AdStatus.APPROVED.value
        assert advert.activated_at is None

    def test_illegal_transition_is_rejected(self, advertiser):
        advert = make_advert(advertiser, status=AdStatus.DRAFT.value)
        with pytest.raises(ConflictError, match="Cannot move an advert"):
            AdvertisementService.pause(advert=advert)

    def test_completed_is_terminal(self, advertiser):
        advert = make_advert(advertiser)
        AdvertisementService.complete(advert=advert)
        with pytest.raises(ConflictError):
            AdvertisementService.resume(advert=advert)

    def test_reject_requires_a_reason(self, advertiser, admin_user):
        advert = make_advert(advertiser, status=AdStatus.PENDING_REVIEW.value)
        with pytest.raises(ValidationError):
            AdvertisementService.reject(advert=advert, reviewer=admin_user, reason="  ")

    def test_resume_after_window_closed_is_refused(self, advertiser):
        advert = make_advert(
            advertiser, status=AdStatus.RUNNING.value, starts_delta=-9, ends_delta=9
        )
        AdvertisementService.pause(advert=advert)
        Advertisement.objects.filter(pk=advert.pk).update(
            ends_at=timezone.now() - timedelta(hours=1)
        )
        advert.refresh_from_db()
        with pytest.raises(ConflictError, match="window has ended"):
            AdvertisementService.resume(advert=advert)


# ---------------------------------------------------------------------------
# Celery: the schedule drives start / end
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestScheduleTasks:

    def test_activates_adverts_whose_start_has_arrived(self, advertiser):
        advert = make_advert(advertiser, status=AdStatus.APPROVED.value)

        result = activate_due_advertisements()

        advert.refresh_from_db()
        assert result["activated"] == 1
        assert advert.status == AdStatus.RUNNING.value
        assert advert.activated_at is not None

    def test_does_not_activate_a_future_advert(self, advertiser):
        advert = make_advert(
            advertiser, status=AdStatus.APPROVED.value, starts_delta=1, ends_delta=5
        )
        assert activate_due_advertisements()["activated"] == 0
        advert.refresh_from_db()
        assert advert.status == AdStatus.APPROVED.value

    def test_completes_adverts_past_their_end(self, advertiser):
        advert = make_advert(advertiser, status=AdStatus.RUNNING.value)
        Advertisement.objects.filter(pk=advert.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )

        result = complete_expired_advertisements()

        advert.refresh_from_db()
        assert result["completed"] == 1
        assert advert.status == AdStatus.COMPLETED.value
        assert advert.completed_at is not None

    def test_completion_also_closes_paused_adverts(self, advertiser):
        advert = make_advert(advertiser, status=AdStatus.PAUSED.value)
        Advertisement.objects.filter(pk=advert.pk).update(
            ends_at=timezone.now() - timedelta(minutes=1)
        )
        complete_expired_advertisements()
        advert.refresh_from_db()
        assert advert.status == AdStatus.COMPLETED.value

    def test_sweeps_are_idempotent(self, advertiser):
        make_advert(advertiser, status=AdStatus.APPROVED.value)
        assert activate_due_advertisements()["activated"] == 1
        assert activate_due_advertisements()["activated"] == 0

    def test_pauses_when_the_impression_cap_is_reached(self, advertiser):
        advert = make_advert(advertiser, total_impression_cap=100)
        Advertisement.objects.filter(pk=advert.pk).update(impressions_count=100)

        assert pause_exhausted_advertisements()["paused"] == 1
        advert.refresh_from_db()
        assert advert.status == AdStatus.PAUSED.value

    def test_pauses_when_the_budget_is_spent(self, advertiser):
        advert = make_advert(advertiser, budget_amount=50)
        Advertisement.objects.filter(pk=advert.pk).update(amount_spent=50)
        assert pause_exhausted_advertisements()["paused"] == 1


# ---------------------------------------------------------------------------
# Creatives: link, never re-upload
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCreativeAttachment:

    def test_links_media_in_order(self, advertiser):
        advert = make_advert(advertiser, with_creative=False)
        ids = [str(make_media(advertiser).id) for _ in range(3)]

        result = attach_ad_creatives(str(advert.id), ids)

        assert result["attached"] == 3
        rows = list(advert.creatives.order_by("position"))
        assert [str(r.media_id) for r in rows] == ids

    def test_does_not_touch_storage(self, advertiser, storage_objects):
        advert = make_advert(advertiser, with_creative=False)
        attach_ad_creatives(str(advert.id), [str(make_media(advertiser).id)])
        assert storage_objects.objects == {}

    def test_skips_media_owned_by_someone_else(self, advertiser, viewer):
        advert = make_advert(advertiser, with_creative=False)
        theirs = make_media(viewer)
        result = attach_ad_creatives(str(advert.id), [str(theirs.id)])
        assert result["attached"] == 0
        assert str(theirs.id) in result["skipped"]

    def test_is_idempotent(self, advertiser):
        advert = make_advert(advertiser, with_creative=False)
        ids = [str(make_media(advertiser).id)]
        attach_ad_creatives(str(advert.id), ids)
        attach_ad_creatives(str(advert.id), ids)
        assert advert.creatives.count() == 1


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDelivery:

    def test_serves_a_running_advert_for_its_mode(self, advertiser, viewer):
        make_advert(advertiser, mode=AdMode.ON_FEED_LIST.value)
        picked = AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer)
        assert len(picked) == 1

    def test_does_not_serve_another_mode(self, advertiser, viewer):
        make_advert(advertiser, mode=AdMode.ON_FEED_LIST.value)
        assert AdDeliveryService.select(mode=AdMode.ON_STARTUP.value, viewer=viewer) == []

    @pytest.mark.parametrize(
        "status",
        [AdStatus.DRAFT.value, AdStatus.PENDING_REVIEW.value, AdStatus.APPROVED.value,
         AdStatus.PAUSED.value, AdStatus.COMPLETED.value, AdStatus.REJECTED.value],
    )
    def test_only_running_adverts_are_served(self, advertiser, viewer, status):
        make_advert(advertiser, status=status)
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer) == []

    def test_does_not_serve_outside_the_flight_window(self, advertiser, viewer):
        advert = make_advert(advertiser)
        Advertisement.objects.filter(pk=advert.pk).update(
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=2),
        )
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer) == []

    def test_advert_without_a_creative_is_not_served(self, advertiser, viewer):
        make_advert(advertiser, with_creative=False)
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer) == []

    def test_soft_deleted_advert_is_not_served(self, advertiser, viewer):
        advert = make_advert(advertiser)
        advert.delete()
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer) == []

    def test_screen_position_filter(self, advertiser, viewer):
        make_advert(advertiser)  # INLINE
        assert AdDeliveryService.select(
            mode=AdMode.ON_FEED_LIST.value, viewer=viewer,
            screen_position=AdScreenPosition.FULL_SCREEN.value,
        ) == []
        assert AdDeliveryService.select(
            mode=AdMode.ON_FEED_LIST.value, viewer=viewer,
            screen_position=AdScreenPosition.INLINE.value,
        )

    def test_daily_cap_stops_delivery(self, advertiser, viewer):
        advert = make_advert(advertiser, daily_impression_cap=5)
        AdDailyMetric.objects.create(
            advertisement=advert, date=timezone.localdate(), impressions=5,
        )
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer) == []

    def test_total_cap_stops_delivery(self, advertiser, viewer):
        advert = make_advert(advertiser, total_impression_cap=10)
        Advertisement.objects.filter(pk=advert.pk).update(impressions_count=10)
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer) == []

    def test_per_user_frequency_cap(self, advertiser, viewer):
        advert = make_advert(advertiser, frequency_cap_per_user=1)
        AdEvent.objects.create(
            advertisement=advert, user=viewer,
            event_type=AdEventType.IMPRESSION.value,
        )
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer) == []
        # A different viewer is unaffected.
        other = User.objects.create(username="other", email="o@example.com")
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=other)

    def test_anonymous_viewers_only_get_untargeted_adverts(self, advertiser):
        make_advert(advertiser, target_cities=["Lagos"])
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=None) == []

        make_advert(advertiser, title="Open to all")
        assert AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=None)

    def test_limit_is_respected(self, advertiser, viewer):
        for i in range(4):
            make_advert(advertiser, title=f"Ad {i}")
        assert len(
            AdDeliveryService.select(
                mode=AdMode.ON_FEED_LIST.value, viewer=viewer, limit=3
            )
        ) == 3

    def test_higher_priority_wins_more_often(self, advertiser, viewer):
        make_advert(advertiser, title="loud", priority=10)
        make_advert(advertiser, title="quiet", priority=1)

        picks = [
            AdDeliveryService.select(mode=AdMode.ON_FEED_LIST.value, viewer=viewer)[0]
            .advertisement.title
            for _ in range(200)
        ]
        assert picks.count("loud") > picks.count("quiet")


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEventRecording:

    def test_impression_increments_counters_and_daily_metric(self, advertiser, viewer):
        advert = make_advert(advertiser)
        AdEventService.record(
            advertisement_id=str(advert.id),
            event_type=AdEventType.IMPRESSION.value,
            user=viewer,
        )
        advert.refresh_from_db()
        assert advert.impressions_count == 1
        metric = AdDailyMetric.objects.get(advertisement=advert, date=timezone.localdate())
        assert metric.impressions == 1

    def test_click_increments_clicks_and_ctr(self, advertiser, viewer):
        advert = make_advert(advertiser)
        for _ in range(4):
            AdEventService.record(
                advertisement_id=str(advert.id),
                event_type=AdEventType.IMPRESSION.value, user=viewer,
            )
        AdEventService.record(
            advertisement_id=str(advert.id),
            event_type=AdEventType.CLICK.value, user=viewer,
        )
        advert.refresh_from_db()
        assert advert.clicks_count == 1
        assert advert.click_through_rate == 25.0

    def test_replayed_beacon_is_ignored(self, advertiser, viewer):
        advert = make_advert(advertiser)
        for _ in range(3):
            AdEventService.record(
                advertisement_id=str(advert.id),
                event_type=AdEventType.IMPRESSION.value,
                user=viewer, dedupe_key="beacon-1",
            )
        advert.refresh_from_db()
        assert advert.impressions_count == 1
        assert AdEvent.objects.filter(advertisement=advert).count() == 1

    def test_cpm_billing_charges_per_thousand(self, advertiser, viewer):
        from decimal import Decimal
        advert = make_advert(advertiser, pricing_model="cpm", bid_amount=Decimal("1000"))
        AdEventService.record(
            advertisement_id=str(advert.id),
            event_type=AdEventType.IMPRESSION.value, user=viewer,
        )
        advert.refresh_from_db()
        assert advert.amount_spent == Decimal("1.00")

    def test_cpc_does_not_bill_impressions(self, advertiser, viewer):
        from decimal import Decimal
        advert = make_advert(advertiser, pricing_model="cpc", bid_amount=Decimal("20"))
        AdEventService.record(
            advertisement_id=str(advert.id),
            event_type=AdEventType.IMPRESSION.value, user=viewer,
        )
        advert.refresh_from_db()
        assert advert.amount_spent == Decimal("0.00")

        AdEventService.record(
            advertisement_id=str(advert.id),
            event_type=AdEventType.CLICK.value, user=viewer,
        )
        advert.refresh_from_db()
        assert advert.amount_spent == Decimal("20.00")

    def test_unknown_advertisement_is_ignored(self, viewer):
        assert AdEventService.record(
            advertisement_id=str(uuid.uuid4()),
            event_type=AdEventType.IMPRESSION.value, user=viewer,
        ) is None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdvertisementAPI:

    def _payload(self, advertiser, **overrides):
        now = timezone.now()
        payload = {
            "title": "Launch week",
            "media_ids": [str(make_media(advertiser).id)],
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(days=5)).isoformat(),
            "placements": [
                {"mode": AdMode.ON_FEED_LIST.value,
                 "screen_position": AdScreenPosition.INLINE.value},
            ],
        }
        payload.update(overrides)
        return payload

    def test_create_starts_as_draft_without_a_caption(self, advertiser):
        resp = auth(advertiser).post(ADS_URL, self._payload(advertiser), format="json")
        assert resp.status_code == 201, resp.data
        assert resp.data["data"]["status"] == AdStatus.DRAFT.value
        assert resp.data["data"]["caption"] == ""

    def test_create_rejects_an_end_before_start(self, advertiser):
        now = timezone.now()
        resp = auth(advertiser).post(
            ADS_URL,
            self._payload(
                advertiser,
                starts_at=(now + timedelta(days=2)).isoformat(),
                ends_at=(now + timedelta(days=1)).isoformat(),
            ),
            format="json",
        )
        assert resp.status_code == 400

    def test_create_requires_a_placement(self, advertiser):
        resp = auth(advertiser).post(
            ADS_URL, self._payload(advertiser, placements=[]), format="json"
        )
        assert resp.status_code == 400

    def test_create_rejects_someone_elses_media(self, advertiser, viewer):
        resp = auth(advertiser).post(
            ADS_URL,
            self._payload(advertiser, media_ids=[str(make_media(viewer).id)]),
            format="json",
        )
        assert resp.status_code == 400
        assert "not owned by you" in str(resp.data)

    def test_create_rejects_a_duplicate_mode(self, advertiser):
        resp = auth(advertiser).post(
            ADS_URL,
            self._payload(advertiser, placements=[
                {"mode": AdMode.ON_STARTUP.value},
                {"mode": AdMode.ON_STARTUP.value},
            ]),
            format="json",
        )
        assert resp.status_code == 400

    def test_advertisers_only_see_their_own(self, advertiser, viewer):
        make_advert(advertiser)
        make_advert(viewer)
        resp = auth(advertiser).get(ADS_URL)
        assert resp.status_code == 200
        assert resp.data["totalItem"] == 1

    def test_cannot_read_another_advertisers_advert(self, advertiser, viewer):
        advert = make_advert(viewer)
        resp = auth(advertiser).get(f"{ADS_URL}{advert.id}/")
        assert resp.status_code == 403

    def test_only_staff_may_review(self, advertiser):
        advert = make_advert(advertiser, status=AdStatus.PENDING_REVIEW.value)
        resp = auth(advertiser).post(
            f"{ADS_URL}{advert.id}/review/", {"action": "approve"}, format="json"
        )
        assert resp.status_code == 403

    def test_staff_can_approve(self, advertiser, admin_user):
        advert = make_advert(advertiser, status=AdStatus.PENDING_REVIEW.value)
        resp = auth(admin_user).post(
            f"{ADS_URL}{advert.id}/review/", {"action": "approve"}, format="json"
        )
        assert resp.status_code == 200, resp.data
        advert.refresh_from_db()
        assert advert.status == AdStatus.RUNNING.value

    def test_reject_without_a_reason_is_a_400(self, advertiser, admin_user):
        advert = make_advert(advertiser, status=AdStatus.PENDING_REVIEW.value)
        resp = auth(admin_user).post(
            f"{ADS_URL}{advert.id}/review/", {"action": "reject"}, format="json"
        )
        assert resp.status_code == 400

    def test_metrics_endpoint(self, advertiser):
        advert = make_advert(advertiser)
        resp = auth(advertiser).get(f"{ADS_URL}{advert.id}/metrics/")
        assert resp.status_code == 200
        assert "click_through_rate" in resp.data["data"]


@pytest.mark.django_db
class TestServeAndBeaconAPI:

    def test_serve_requires_a_valid_mode(self, advertiser):
        client = APIClient()
        assert client.get("/api/v2/advertisements/serve/").status_code == 400
        assert client.get(
            "/api/v2/advertisements/serve/?mode=nonsense"
        ).status_code == 400

    def test_serve_returns_a_render_ready_payload(self, advertiser, viewer):
        make_advert(advertiser)
        resp = auth(viewer).get(
            f"/api/v2/advertisements/serve/?mode={AdMode.ON_FEED_LIST.value}"
        )
        assert resp.status_code == 200
        item = resp.data["data"][0]
        assert item["mode"] == AdMode.ON_FEED_LIST.value
        assert item["screen_position"] == AdScreenPosition.INLINE.value
        assert item["creatives"][0]["image_url"]
        # Commercial detail must never reach the client.
        assert "bid_amount" not in item and "budget_amount" not in item

    def test_serve_works_for_anonymous_clients(self, advertiser):
        make_advert(advertiser)
        resp = APIClient().get(
            f"/api/v2/advertisements/serve/?mode={AdMode.ON_FEED_LIST.value}"
        )
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1

    def test_beacon_is_accepted_and_queued(self, advertiser, viewer):
        advert = make_advert(advertiser)
        resp = auth(viewer).post(
            "/api/v2/advertisements/events/",
            {"advertisement_id": str(advert.id),
             "event_type": AdEventType.IMPRESSION.value},
            format="json",
        )
        assert resp.status_code == 202
        advert.refresh_from_db()
        assert advert.impressions_count == 1  # eager celery

    def test_beacon_rejects_an_unknown_event_type(self, advertiser, viewer):
        advert = make_advert(advertiser)
        resp = auth(viewer).post(
            "/api/v2/advertisements/events/",
            {"advertisement_id": str(advert.id), "event_type": "teleport"},
            format="json",
        )
        assert resp.status_code == 400

    def test_options_endpoint_lists_the_vocabulary(self):
        resp = APIClient().get("/api/v2/advertisements/options/")
        assert resp.status_code == 200
        modes = {m["value"] for m in resp.data["data"]["modes"]}
        assert {"flash", "on_startup", "on_feed_list", "on_comment_show"} <= modes
        assert resp.data["data"]["screen_positions"]
