import logging

from django.db.models import F, OuterRef, Subquery, FloatField, ExpressionWrapper
from django.db.models.functions import Cos, Sin, ASin, Sqrt, Radians, Power
from django.utils import timezone

from accounts.models import User, UserLocation, Connection
from accounts.services.discovery_cache import DiscoveryCache
from utils.enum import ConnectionStatus

logger = logging.getLogger(__name__)


class ConnectService:

    def get_discoverable_users(self, current_user: User, filters: dict):
        try:
            return self._get_discoverable_users_redis(current_user, filters)
        except Exception as exc:
            logger.warning("Redis discovery failed, falling back to Postgres: %s", exc)
            return self._get_discoverable_users_pg(current_user, filters)

    # ── Redis-backed path (fast) ──────────────────────────────────

    def _get_discoverable_users_redis(self, current_user: User, filters: dict):
        uid = str(current_user.id)

        if DiscoveryCache._redis() is None:
            raise ConnectionError("Redis not available")

        cached = DiscoveryCache.get_cached(uid, filters)
        if cached is not None:
            return self._build_user_qs(current_user, cached, filters)

        lat = None
        lon = None
        meta = DiscoveryCache.get_metadata(uid)

        if meta:
            lat = float(meta.get("lat", 0))
            lon = float(meta.get("lon", 0))

        if lat is None or lon is None:
            current_loc = UserLocation.objects.filter(
                user=current_user
            ).order_by("-created_at").first()
            if current_loc and current_loc.latitude and current_loc.longitude:
                lat = float(current_loc.latitude)
                lon = float(current_loc.longitude)

        if lat is None or lon is None:
            if filters.get("distance_km"):
                qs = User.objects.none()
                return self._annotate_from_result_list(qs, [])
            qs = self._user_base_qs(current_user)
            return self._annotate_location(qs)

        max_distance = filters.get("distance_km", 300.0)
        connected = DiscoveryCache.connected_user_ids(uid)

        nearby = DiscoveryCache.nearby_user_ids(
            lat, lon, max_distance, exclude=connected | {uid},
        )

        results = []
        for n_uid, dist in nearby:
            n_meta = DiscoveryCache.get_metadata(n_uid)
            city = filters.get("city")
            state = filters.get("state")
            country = filters.get("country")

            if city and n_meta:
                if city.lower() not in n_meta.get("city", "").lower():
                    continue
            if state and n_meta:
                if state.lower() not in n_meta.get("state", "").lower():
                    continue
            if country and n_meta:
                if country.lower() not in n_meta.get("country", "").lower():
                    continue

            results.append({
                "id": n_uid,
                "distance_km": dist,
                **{k: (n_meta.get(k) if n_meta else None) for k in ("city", "state")},
            })

        DiscoveryCache.set_cached(uid, filters, results)

        return self._build_user_qs(current_user, results, filters)

    def _build_user_qs(self, current_user: User, results: list[dict], filters: dict):
        if not results:
            return User.objects.none()
        ids = [r["id"] for r in results]
        id_to_dist = {r["id"]: r["distance_km"] for r in results}
        id_to_city = {r["id"]: r.get("city") for r in results}
        id_to_state = {r["id"]: r.get("state") for r in results}

        qs = User.objects.filter(id__in=ids, is_active=True, is_deleted=False)
        qs = qs.exclude(id=current_user.id)

        from django.db.models import Value, Case, When, FloatField, CharField
        from django.db.models.functions import Cast

        preserved = Case(
            *[When(id=uid, then=Value(dist)) for uid, dist in id_to_dist.items()],
            default=Value(0.0),
            output_field=FloatField(),
        )
        qs = qs.annotate(distance_km=preserved)

        city_case = Case(
            *[When(id=uid, then=Value(city)) for uid, city in id_to_city.items()],
            default=Value(""),
            output_field=CharField(),
        )
        state_case = Case(
            *[When(id=uid, then=Value(state)) for uid, state in id_to_state.items()],
            default=Value(""),
            output_field=CharField(),
        )

        from accounts.models import UserLocation as UL
        latest_loc_qs = UL.objects.filter(user=OuterRef("pk")).order_by("-created_at")
        qs = qs.annotate(
            loc_city=city_case,
            loc_state=state_case,
            loc_lat=Subquery(latest_loc_qs.values("latitude")[:1]),
            loc_lon=Subquery(latest_loc_qs.values("longitude")[:1]),
        )

        return qs.order_by("distance_km")

    def _annotate_from_result_list(self, qs, results):
        return qs

    # ── Postgres fallback path (original) ────────────────────────

    def _get_discoverable_users_pg(self, current_user: User, filters: dict):
        qs = self._user_base_qs(current_user)

        current_loc = UserLocation.objects.filter(
            user=current_user
        ).order_by("-created_at").first()

        qs = self._annotate_location(qs)
        qs = qs.filter(loc_lat__isnull=False, loc_lon__isnull=False)

        if city := filters.get("city"):
            qs = qs.filter(loc_city__icontains=city)
        if state := filters.get("state"):
            qs = qs.filter(loc_state__icontains=state)
        if country := filters.get("country"):
            qs = qs.filter(loc_country__icontains=country)

        if current_loc and current_loc.latitude and current_loc.longitude:
            qs = self._annotate_distance(qs, current_loc)
            if max_distance := filters.get("distance_km"):
                qs = qs.filter(distance_km__lte=max_distance)
            return qs.order_by("distance_km")
        else:
            if filters.get("distance_km"):
                return qs.none()
            return qs

    def _user_base_qs(self, current_user: User):
        qs = User.objects.exclude(id=current_user.id).filter(
            is_active=True, is_deleted=False,
        )
        connected_req = Connection.objects.filter(
            requester=current_user,
        ).values_list("recipient_id", flat=True)
        connected_rec = Connection.objects.filter(
            recipient=current_user,
        ).values_list("requester_id", flat=True)
        return qs.exclude(id__in=connected_req).exclude(id__in=connected_rec)

    def _annotate_location(self, qs):
        latest_loc_qs = UserLocation.objects.filter(
            user=OuterRef("pk"),
        ).order_by("-created_at")
        return qs.annotate(
            loc_lat=Subquery(latest_loc_qs.values("latitude")[:1]),
            loc_lon=Subquery(latest_loc_qs.values("longitude")[:1]),
            loc_city=Subquery(latest_loc_qs.values("location_data__city")[:1]),
            loc_state=Subquery(latest_loc_qs.values("location_data__state")[:1]),
            loc_country=Subquery(latest_loc_qs.values("location_data__country")[:1]),
        )

    def _annotate_distance(self, qs, current_loc):
        lat1 = Radians(float(current_loc.latitude))
        lon1 = Radians(float(current_loc.longitude))
        lat2 = Radians(F("loc_lat"))
        lon2 = Radians(F("loc_lon"))

        dlon = lon2 - lon1
        dlat = lat2 - lat1

        a = Power(Sin(dlat / 2.0), 2) + Cos(lat1) * Cos(lat2) * Power(Sin(dlon / 2.0), 2)
        c = 2.0 * ASin(Sqrt(a))
        distance_expr = ExpressionWrapper(6371.0 * c, output_field=FloatField())

        return qs.annotate(distance_km=distance_expr)

    # ── Connection helpers (also warm Redis) ─────────────────────

    def send_connection_request(self, requester: User, recipient: User) -> Connection:
        from accounts.tasks import send_user_push_notification

        if requester == recipient:
            raise ValueError("You cannot connect with yourself.")

        connection, created = Connection.objects.get_or_create(
            requester=requester,
            recipient=recipient,
            defaults={"status": ConnectionStatus.PENDING.value},
        )

        DiscoveryCache.add_connection(
            str(requester.id), str(recipient.id),
        )

        send_user_push_notification.delay(
            user=requester.id,
            title="Connection Request Sent",
            body=f"You have sent a connection request to {recipient.username}.",
            data={"type": "connection_request_sent", "recipient_id": recipient.id},
        )

        send_user_push_notification.delay(
            user=recipient.id,
            title="New Connection Request",
            body=f"{requester.username} wants to connect with you.",
            data={"type": "connection_request", "requester_id": requester.id},
        )
        return connection

    def respond_to_connection(self, user: User, connection_id: str, action: str) -> Connection:
        from accounts.tasks import send_user_push_notification

        try:
            connection = Connection.objects.get(
                id=connection_id, recipient=user, status=ConnectionStatus.PENDING.value,
            )
        except Connection.DoesNotExist:
            raise ValueError("Connection request not found or already processed.")

        if action == "accept":
            connection.status = ConnectionStatus.ACCEPTED.value
            connection.accepted_at = timezone.now()

            DiscoveryCache.add_connection(
                str(connection.requester_id), str(connection.recipient_id),
            )

            send_user_push_notification.delay(
                user=connection.requester.id,
                title="Connection Request Accepted",
                body=f"{user.username} accepted your connection request.",
                data={"type": "connection_accepted", "recipient_id": user.id},
            )
        elif action == "reject":
            connection.status = ConnectionStatus.REJECTED.value

            DiscoveryCache.remove_connection(
                str(connection.requester_id), str(connection.recipient_id),
            )
        else:
            raise ValueError("Invalid action.")

        connection.save(
            update_fields=["status", "accepted_at"] if action == "accept" else ["status"],
        )
        return connection
