import csv
import io
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce

from tickets.models import Event, Payout, PaymentTransaction, SellerProfile, Ticket, TicketPurchase
from utils.enum import PaymentStatus, PayoutStatus, TicketStatus, TransactionType


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

    @staticmethod
    def seller_financial_insights(seller: SellerProfile) -> dict:
        commission_rate = seller.commission_rate

        successful_purchases = TicketPurchase.objects.filter(
            event__seller=seller,
            payment_status=PaymentStatus.SUCCESSFUL.value,
        )

        sales_agg = successful_purchases.aggregate(
            total_gross=Coalesce(Sum("total_amount"), 0, output_field=DecimalField()),
            total_fees_collected=Coalesce(Sum("fees_amount"), 0, output_field=DecimalField()),
            total_tickets_sold=Coalesce(Sum("quantity"), 0),
            total_purchases=Count("id"),
        )

        total_gross = Decimal(str(sales_agg["total_gross"]))
        total_commission = total_gross * (commission_rate / Decimal("100"))
        total_net = total_gross - total_commission

        refund_agg = Ticket.objects.filter(
            event__seller=seller,
            status=TicketStatus.REFUNDED.value,
        ).aggregate(
            total_refunded=Coalesce(Sum("price_paid"), 0, output_field=DecimalField()),
            refund_count=Count("id"),
        )

        payout_agg = Payout.objects.filter(seller=seller).aggregate(
            total_paid=Coalesce(
                Sum("amount", filter=Q(status=PayoutStatus.PAID.value)),
                0, output_field=DecimalField(),
            ),
            total_pending=Coalesce(
                Sum("amount", filter=Q(status__in=[
                    PayoutStatus.REQUESTED.value, PayoutStatus.PROCESSING.value,
                ])),
                0, output_field=DecimalField(),
            ),
            total_rejected=Coalesce(
                Sum("amount", filter=Q(status=PayoutStatus.REJECTED.value)),
                0, output_field=DecimalField(),
            ),
            payout_count=Count("id"),
        )

        total_paid_out = Decimal(str(payout_agg["total_paid"]))
        total_refunded = Decimal(str(refund_agg["total_refunded"]))
        unsettled_balance = total_net - total_paid_out - total_refunded

        events = Event.objects.filter(
            seller=seller,
            is_deleted=False,
        ).annotate(
            gross_revenue=Coalesce(
                Sum(
                    "purchases__total_amount",
                    filter=Q(purchases__payment_status=PaymentStatus.SUCCESSFUL.value),
                ),
                0, output_field=DecimalField(),
            ),
            event_tickets_sold=Coalesce(
                Sum(
                    "purchases__quantity",
                    filter=Q(purchases__payment_status=PaymentStatus.SUCCESSFUL.value),
                ),
                0,
            ),
            event_refund_count=Count(
                "tickets",
                filter=Q(tickets__status=TicketStatus.REFUNDED.value),
            ),
            event_dispute_count=Count(
                "disputes",
                filter=Q(disputes__is_deleted=False),
            ),
        ).order_by("-gross_revenue", "-created_at")

        events_breakdown = []
        for ev in events:
            ev_gross = Decimal(str(ev.gross_revenue))
            ev_commission = ev_gross * (commission_rate / Decimal("100"))
            ev_net = ev_gross - ev_commission
            events_breakdown.append({
                "event_id": str(ev.id),
                "title": ev.title,
                "status": ev.status,
                "starts_at": ev.starts_at.isoformat(),
                "ends_at": ev.ends_at.isoformat() if ev.ends_at else None,
                "tickets_sold": ev.event_tickets_sold,
                "tickets_available": ev.tickets_available,
                "tickets_refunded": ev.event_refund_count,
                "disputes": ev.event_dispute_count,
                "gross_revenue": float(ev_gross),
                "commission": float(ev_commission),
                "net_revenue": float(ev_net),
            })

        return {
            "overview": {
                "commission_rate": float(commission_rate),
                "total_gross_revenue": float(total_gross),
                "total_commission": float(total_commission),
                "total_net_revenue": float(total_net),
                "total_fees_collected_from_buyers": float(sales_agg["total_fees_collected"]),
                "total_refunds": float(refund_agg["total_refunded"]),
                "refund_count": refund_agg["refund_count"],
                "total_tickets_sold": sales_agg["total_tickets_sold"],
                "total_purchases": sales_agg["total_purchases"],
            },
            "payouts": {
                "total_paid_out": float(payout_agg["total_paid"]),
                "total_pending": float(payout_agg["total_pending"]),
                "total_rejected": float(payout_agg["total_rejected"]),
                "unsettled_balance": float(unsettled_balance),
                "payout_count": payout_agg["payout_count"],
            },
            "events_breakdown": events_breakdown,
        }
