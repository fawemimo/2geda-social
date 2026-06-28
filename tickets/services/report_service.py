import csv
import io

from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce

from tickets.models import Event, PaymentTransaction, SellerProfile, Ticket
from utils.enum import PaymentStatus, TicketStatus, TransactionType


class ReportService:

    @staticmethod
    def event_sales_report(event: Event) -> dict:
        tickets = Ticket.objects.filter(event=event, is_deleted=False)

        total_sold = tickets.filter(status=TicketStatus.SOLD.value).count()
        total_refunded = tickets.filter(status=TicketStatus.REFUNDED.value).count()
        total_cancelled = tickets.filter(status=TicketStatus.CANCELLED.value).count()

        revenue_agg = tickets.filter(
            status=TicketStatus.SOLD.value
        ).aggregate(
            total_revenue=Coalesce(Sum("price_paid"), 0, output_field=DecimalField()),
            total_fees=Coalesce(Sum("fees_paid"), 0, output_field=DecimalField()),
        )

        tier_breakdown = list(
            event.price_tiers.annotate(
                sold_count=Count(
                    "tickets",
                    filter=Q(tickets__status=TicketStatus.SOLD.value),
                ),
                refunded_count=Count(
                    "tickets",
                    filter=Q(tickets__status=TicketStatus.REFUNDED.value),
                ),
            ).values(
                "price_tag", "price", "quantity", "sold_count", "refunded_count"
            )
        )

        return {
            "event_title": event.title,
            "event_status": event.status,
            "total_tickets": event.tickets_available
            + event.total_tickets_sold
            + event.tickets_reserved,
            "total_sold": total_sold,
            "total_refunded": total_refunded,
            "total_cancelled": total_cancelled,
            "total_revenue": float(revenue_agg["total_revenue"]),
            "total_fees": float(revenue_agg["total_fees"]),
            "tier_breakdown": tier_breakdown,
        }

    @staticmethod
    def seller_aggregate_report(seller: SellerProfile) -> dict:
        events = Event.objects.filter(seller=seller, is_deleted=False)

        event_counts = events.aggregate(
            total=Count("id"),
            published=Count("id", filter=Q(status="published")),
            completed=Count("id", filter=Q(status="completed")),
            cancelled=Count("id", filter=Q(status="cancelled")),
        )

        tx_agg = PaymentTransaction.objects.filter(
            seller=seller,
            status=PaymentStatus.SUCCESSFUL.value,
        ).aggregate(
            gross_revenue=Coalesce(
                Sum("amount", filter=Q(transaction_type=TransactionType.PURCHASE.value)),
                0,
                output_field=DecimalField(),
            ),
            total_fees=Coalesce(
                Sum("fees"),
                0,
                output_field=DecimalField(),
            ),
            total_refunds=Coalesce(
                Sum("amount", filter=Q(transaction_type=TransactionType.REFUND.value)),
                0,
                output_field=DecimalField(),
            ),
        )

        net_revenue = (
            float(tx_agg["gross_revenue"])
            - float(tx_agg["total_fees"])
            - float(tx_agg["total_refunds"])
        )

        return {
            "business_name": seller.business_name,
            "seller_status": seller.status,
            "events": {
                "total": event_counts["total"],
                "published": event_counts["published"],
                "completed": event_counts["completed"],
                "cancelled": event_counts["cancelled"],
            },
            "financials": {
                "gross_revenue": float(tx_agg["gross_revenue"]),
                "total_fees": float(tx_agg["total_fees"]),
                "total_refunds": float(tx_agg["total_refunds"]),
                "net_revenue": net_revenue,
            },
        }

    @staticmethod
    def download_event_csv(event: Event) -> io.StringIO:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Ticket Code",
                "Buyer",
                "Buyer Email",
                "Price Tier",
                "Price Paid",
                "Fees Paid",
                "Status",
                "Purchased At",
            ]
        )

        tickets = Ticket.objects.filter(
            event=event, is_deleted=False
        ).select_related("buyer", "price_tier").order_by("-purchased_at")

        for ticket in tickets:
            writer.writerow(
                [
                    ticket.ticket_code,
                    ticket.buyer.username,
                    ticket.buyer.email,
                    ticket.price_tier.price_tag if ticket.price_tier else "N/A",
                    str(ticket.price_paid),
                    str(ticket.fees_paid),
                    ticket.status,
                    ticket.purchased_at.isoformat() if ticket.purchased_at else "",
                ]
            )

        output.seek(0)
        return output

    @staticmethod
    def download_full_transaction_report(seller: SellerProfile) -> io.StringIO:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Reference",
                "Type",
                "Event",
                "Amount",
                "Fees",
                "Status",
                "Buyer",
                "Notes",
                "Created At",
            ]
        )

        transactions = PaymentTransaction.objects.filter(
            seller=seller,
        ).select_related("event", "buyer").order_by("-created_at")

        for tx in transactions:
            writer.writerow(
                [
                    tx.reference,
                    tx.transaction_type,
                    tx.event.title if tx.event else "N/A",
                    str(tx.amount),
                    str(tx.fees),
                    tx.status,
                    tx.buyer.username if tx.buyer else "N/A",
                    tx.notes,
                    tx.created_at.isoformat(),
                ]
            )

        output.seek(0)
        return output
