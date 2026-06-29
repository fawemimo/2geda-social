from rest_framework import status as http_status


class ServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "error",
        status_code: int = http_status.HTTP_400_BAD_REQUEST,
        context: dict | None = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.context = context or {}
        super().__init__(message)


class SellerNotApproved(ServiceError):
    def __init__(self):
        super().__init__(
            "Seller account is not approved yet.",
            code="seller_not_approved",
            status_code=http_status.HTTP_403_FORBIDDEN,
        )


class SellerSuspended(ServiceError):
    def __init__(self):
        super().__init__(
            "Seller account has been suspended.",
            code="seller_suspended",
            status_code=http_status.HTTP_403_FORBIDDEN,
        )


class InsufficientTickets(ServiceError):
    def __init__(self):
        super().__init__(
            "Not enough tickets available for the requested quantity.",
            code="insufficient_tickets",
        )


class InvalidEventStatus(ServiceError):
    def __init__(self, message: str = "Event is not in a valid state for this action."):
        super().__init__(message, code="invalid_event_status")


class PricingMismatch(ServiceError):
    def __init__(self):
        super().__init__(
            "Price tier does not belong to this event.",
            code="pricing_mismatch",
        )


class PaymentVerificationFailed(ServiceError):
    def __init__(self, message: str = "Payment verification failed."):
        super().__init__(message, code="payment_verification_failed")


class DuplicateTransaction(ServiceError):
    def __init__(self):
        super().__init__(
            "This transaction has already been processed.",
            code="duplicate_transaction",
        )


class DisputeAlreadyResolved(ServiceError):
    def __init__(self):
        super().__init__(
            "This dispute has already been resolved.",
            code="dispute_already_resolved",
            status_code=http_status.HTTP_409_CONFLICT,
        )


class EventLinkExpired(ServiceError):
    def __init__(self):
        super().__init__(
            "This event link is no longer valid.",
            code="event_link_expired",
        )
