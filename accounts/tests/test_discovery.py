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
            email="alice@test.com",
            username="alice",
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


class DiscoveryIntegrationTest(TransactionTestCase):

    def setUp(self):
        self.alice = User.objects.create_user(
            email="alice@test.com",
            username="alice",
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
            user=self.alice,
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
        qs = service.get_discoverable_users(self.alice, filters)
        users = list(qs)
        self.assertIn(self.bob, [u for u in users])

    def test_postgres_fallback_respects_city_filter(self):
        service = ConnectService()
        filters = {"distance_km": 50, "city": "Paris", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.alice, filters)
        users = list(qs)
        self.assertIn(self.bob, [u for u in users])

    def test_postgres_fallback_excludes_connected(self):
        from accounts.models import Connection
        from utils.enum import ConnectionStatus

        Connection.objects.create(
            requester=self.alice, recipient=self.bob,
            status=ConnectionStatus.ACCEPTED.value,
        )
        service = ConnectService()
        filters = {"distance_km": 50, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.alice, filters)
        users = list(qs)
        self.assertNotIn(self.bob, [u for u in users])

    def test_annotated_distance_km(self):
        service = ConnectService()
        filters = {"distance_km": 50, "city": "", "state": "", "country": ""}
        qs = service.get_discoverable_users(self.alice, filters)
        for u in qs:
            self.assertIsNotNone(getattr(u, "distance_km", None))
            self.assertGreaterEqual(u.distance_km, 0)
