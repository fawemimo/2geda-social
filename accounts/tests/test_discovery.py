from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from django.test import TransactionTestCase

from accounts.services.connect import ConnectService
from accounts.services.discovery_cache import DiscoveryCache
from accounts.models import User, UserLocation


class DiscoveryCacheTest(TransactionTestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="smithEze@test.com",
            username="smithEze",
            password="pass",
            is_active=True,
        )

    @patch.object(DiscoveryCache, "_redis", return_value=None)
    def test_set_location_no_redis(self, mock_redis):
        DiscoveryCache.set_location("x", 1.0, 2.0)
        mock_redis.assert_called_once()

    @patch.object(DiscoveryCache, "_redis", return_value=None)
    def test_remove_location_no_redis(self, mock_redis):
        DiscoveryCache.remove_location("x")
        mock_redis.assert_called_once()

    @patch.object(DiscoveryCache, "_redis", return_value=None)
    def test_set_metadata_no_redis(self, mock_redis):
        DiscoveryCache.set_metadata("x", city="Paris")
        mock_redis.assert_called_once()

    @patch.object(DiscoveryCache, "_redis", return_value=None)
    def test_get_metadata_no_redis(self, mock_redis):
        result = DiscoveryCache.get_metadata("x")
        assert result is None
        mock_redis.assert_called_once()

    @patch.object(DiscoveryCache, "_redis", return_value=None)
    def test_nearby_user_ids_no_redis(self, mock_redis):
        result = DiscoveryCache.nearby_user_ids(0, 0, 10)
        assert result == []
        mock_redis.assert_called_once()

    @patch.object(DiscoveryCache, "_redis", return_value=None)
    def test_connected_user_ids_no_redis(self, mock_redis):
        result = DiscoveryCache.connected_user_ids("x")
        assert result == set()
        mock_redis.assert_called_once()

    @patch.object(DiscoveryCache, "_redis", return_value=None)
    def test_get_cached_no_redis(self, mock_redis):
        result = DiscoveryCache.get_cached("x", {})
        assert result is None

    @patch.object(DiscoveryCache, "_redis", return_value=None)
    def test_invalidate_user_no_redis(self, mock_redis):
        DiscoveryCache.invalidate_user("x")
        assert mock_redis.call_count >= 1

    @patch.object(DiscoveryCache, "_redis")
    def test_nearby_user_ids_with_mock_redis(self, mock_factory):
        mock_redis = MagicMock()
        mock_redis.georadius.return_value = [
            (b"uid1", 12.34),
            (b"uid2", 56.78),
        ]
        mock_factory.return_value = mock_redis

        result = DiscoveryCache.nearby_user_ids(48.85, 2.35, 100, exclude={"uid3"})
        mock_redis.georadius.assert_called_once_with(
            "discover:locations", 2.35, 48.85, 100,
            unit="km", withdist=True, sort="ASC",
        )
        assert result == [("uid1", 12.34), ("uid2", 56.78)]


class RedisEmptyFallbackTest(TransactionTestCase):

    def setUp(self):
        self.smithEze = User.objects.create_user(
            email="smithEze@test.com", username="smithEze", password="pass", is_active=True,
        )
        self.bob = User.objects.create_user(
            email="bob@test.com", username="bob", password="pass", is_active=True,
        )
        UserLocation.objects.create(
            user=self.smithEze, latitude="48.8566", longitude="2.3522",
        )
        UserLocation.objects.create(
            user=self.bob, latitude="48.8584", longitude="2.2945",
        )

    @patch.object(DiscoveryCache, "nearby_user_ids", return_value=[])
    @patch.object(DiscoveryCache, "geo_has_data", return_value=False)
    @patch.object(DiscoveryCache, "get_metadata", return_value=None)
    @patch.object(DiscoveryCache, "connected_user_ids", return_value=set())
    @patch.object(DiscoveryCache, "_redis", return_value=MagicMock())
    def test_falls_back_when_redis_geoset_empty(
        self, *mocks,
    ):
        service = ConnectService()
        filters = {"distance_km": 50, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        users = list(qs)
        self.assertIn(self.bob, [u for u in users],
                       "Should fall back to PG when Redis geoset is empty")

    @patch.object(DiscoveryCache, "nearby_user_ids", return_value=[])
    @patch.object(DiscoveryCache, "geo_has_data", return_value=True)
    @patch.object(DiscoveryCache, "get_metadata", return_value=None)
    @patch.object(DiscoveryCache, "connected_user_ids", return_value=set())
    @patch.object(DiscoveryCache, "_redis", return_value=MagicMock())
    def test_trusts_redis_when_geoset_has_data_but_none_nearby(
        self, *mocks,
    ):
        service = ConnectService()
        filters = {"distance_km": 50, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        users = list(qs)
        self.assertEqual(len(users), 0,
                         "Should return empty when Redis geoset has users but none nearby")


class DiscoveryIntegrationTest(TransactionTestCase):

    def setUp(self):
        self.smithEze = User.objects.create_user(
            email="smithEze@test.com",
            username="smithEze",
            password="pass",
            is_active=True,
        )
        self.bob = User.objects.create_user(
            email="bob@test.com",
            username="bob",
            password="pass",
            is_active=True,
        )

        UserLocation.objects.create(
            user=self.smithEze,
            latitude="48.8566",
            longitude="2.3522",
            location_data={"city": "Paris", "state": "Île-de-France", "country": "France"},
        )
        UserLocation.objects.create(
            user=self.bob,
            latitude="48.8584",
            longitude="2.2945",
            location_data={"city": "Paris", "state": "Île-de-France", "country": "France"},
        )

    def test_postgres_fallback_returns_users(self):
        service = ConnectService()
        filters = {"distance_km": 50, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        users = list(qs)
        self.assertIn(self.bob, [u for u in users])

    def test_postgres_fallback_respects_city_filter(self):
        service = ConnectService()
        filters = {"distance_km": 50, "city": "Paris", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        users = list(qs)
        self.assertIn(self.bob, [u for u in users])

    def test_postgres_fallback_excludes_connected(self):
        from accounts.models import Connection
        from utils.enum import ConnectionStatus

        Connection.objects.create(
            requester=self.smithEze, recipient=self.bob,
            status=ConnectionStatus.ACCEPTED.value,
        )
        service = ConnectService()
        filters = {"distance_km": 50, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        users = list(qs)
        self.assertNotIn(self.bob, [u for u in users])

    def test_annotated_distance_km(self):
        service = ConnectService()
        filters = {"distance_km": 50, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        for u in qs:
            self.assertIsNotNone(getattr(u, "distance_km", None))
            self.assertGreaterEqual(u.distance_km, 0)

    def test_distance_filter_excludes_out_of_range(self):
        charlie = User.objects.create_user(
            email="charlie@far.com",
            username="charlie",
            password="pass",
            is_active=True,
        )
        UserLocation.objects.create(
            user=charlie,
            latitude="6.5244",
            longitude="3.3792",
            location_data={"city": "Lagos", "state": "Lagos", "country": "Nigeria"},
        )

        service = ConnectService()
        filters = {"distance_km": 10, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        users = list(qs)

        self.assertNotIn(charlie, [u for u in users],
                          "Charlie (~4,200 km away) should be excluded by 10 km limit")
        self.assertIn(self.bob, [u for u in users],
                       "Bob (~5 km away) should be within 10 km limit")

    def test_distance_filter_excludes_all_outside_range(self):
        service = ConnectService()
        filters = {"distance_km": 0.1, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        users = list(qs)
        self.assertEqual(len(users), 0,
                         "No users should be within 0.1 km of smithEze")

    def test_distance_filter_no_value_uses_default(self):
        service = ConnectService()
        filters = {"city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.smithEze, filters)
        users = list(qs)
        self.assertIn(self.bob, [u for u in users],
                       "Bob should be found with default distance")
