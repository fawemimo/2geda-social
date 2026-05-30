import logging
from django.db.models import F, OuterRef, Subquery, FloatField, ExpressionWrapper
from django.db.models.functions import Cos, Sin, ASin, Sqrt, Radians, Power
from django.utils import timezone
from accounts.models import User, UserLocation, Connection
from utils.enum import ConnectionStatus

logger = logging.getLogger(__name__)

# Service for finding nearby users and managing connections.

class ConnectService:
# Returns a queryset of Users with `distance_km` annotated.

    def get_discoverable_users(self, current_user: User, filters: dict):
        # Exclude self and inactive/deleted users
        qs = User.objects.exclude(id=current_user.id).filter(is_active=True, is_deleted=False)

        # Exclude already connected or pending connections
        connected_req = Connection.objects.filter(
            requester=current_user
        ).values_list("recipient_id", flat=True)
        connected_rec = Connection.objects.filter(
            recipient=current_user
        ).values_list("requester_id", flat=True)

        qs = qs.exclude(id__in=connected_req).exclude(id__in=connected_rec)

        # Get the latest location of the current user
        current_loc = UserLocation.objects.filter(user=current_user).order_by("-created_at").first()

        # Subqueries to get the latest location data for other users
        latest_loc_qs = UserLocation.objects.filter(user=OuterRef("pk")).order_by("-created_at")

        qs = qs.annotate(
            loc_lat=Subquery(latest_loc_qs.values("latitude")[:1]),
            loc_lon=Subquery(latest_loc_qs.values("longitude")[:1]),
            loc_city=Subquery(latest_loc_qs.values("location_data__city")[:1]),
            loc_state=Subquery(latest_loc_qs.values("location_data__state")[:1]),
            loc_country=Subquery(latest_loc_qs.values("location_data__country")[:1]),
        )

        # Filter out users who have no location
        qs = qs.filter(loc_lat__isnull=False, loc_lon__isnull=False)

        # Apply text filters if provided
        if city := filters.get("city"):
            qs = qs.filter(loc_city__icontains=city)
        if state := filters.get("state"):
            qs = qs.filter(loc_state__icontains=state)
        if country := filters.get("country"):
            qs = qs.filter(loc_country__icontains=country)

        # Calculate distance using Haversine formula directly in Postgres
        if current_loc and current_loc.latitude and current_loc.longitude:
            lat1 = Radians(float(current_loc.latitude))
            lon1 = Radians(float(current_loc.longitude))
            lat2 = Radians(F('loc_lat'))
            lon2 = Radians(F('loc_lon'))

            dlon = lon2 - lon1
            dlat = lat2 - lat1

            a = Power(Sin(dlat / 2.0), 2) + Cos(lat1) * Cos(lat2) * Power(Sin(dlon / 2.0), 2)
            c = 2.0 * ASin(Sqrt(a))
            distance_expr = ExpressionWrapper(6371.0 * c, output_field=FloatField())

            qs = qs.annotate(distance_km=distance_expr)

            # Apply distance filter if provided
            if max_distance := filters.get("distance_km"):
                qs = qs.filter(distance_km__lte=max_distance)

            return qs.order_by("distance_km")
        else:
            # If the current user has no location, we can't calculate distance
            if filters.get("distance_km"):
                # Return empty if distance filter is strictly required
                return qs.none()
            return qs
# Create a new connection request.

    def send_connection_request(self, requester: User, recipient: User) -> Connection:
        from accounts.tasks import send_user_push_notification
        if requester == recipient:
            raise ValueError("You cannot connect with yourself.")

        connection, created = Connection.objects.get_or_create(
            requester=requester,
            recipient=recipient,
            defaults={"status": ConnectionStatus.PENDING.value}
        )

        #  notify the requester
        send_user_push_notification.delay(
            user=requester.id,
            title="Connection Request Sent",
            body=f"You have sent a connection request to {recipient.username}.",
            data={"type": "connection_request_sent", "recipient_id": recipient.id}
        )

        # notify the recipient
        send_user_push_notification.delay(
            user=recipient.id,
            title="New Connection Request",
            body=f"{requester.username} wants to connect with you.",
            data={"type": "connection_request", "requester_id": requester.id}
        )
        return connection
# Accepts or rejects a connection request where the user is the recipient.

    def respond_to_connection(self, user: User, connection_id: str, action: str) -> Connection:

        from accounts.tasks import send_user_push_notification

        try:
            connection = Connection.objects.get(id=connection_id, recipient=user, status=ConnectionStatus.PENDING.value)
        except Connection.DoesNotExist:
            raise ValueError("Connection request not found or already processed.")

        if action == "accept":
            connection.status = ConnectionStatus.ACCEPTED.value
            connection.accepted_at = timezone.now()
                # notify the requester
            send_user_push_notification.delay(
                user=connection.requester.id,
                title="Connection Request Accepted",
                body=f"{user.username} accepted your connection request.",
                data={"type": "connection_accepted", "recipient_id": user.id}
            )
        elif action == "reject":
            connection.status = ConnectionStatus.REJECTED.value
        else:
            raise ValueError("Invalid action.")

        connection.save(update_fields=["status", "accepted_at"] if action == "accept" else ["status"])
        return connection


