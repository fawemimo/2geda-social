from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import (
    ObjectDoesNotExist,
    PermissionDenied,
    ValidationError as DjangoValidationError,
)
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


logger = logging.getLogger(__name__)

# Single source of truth for error responses.

def custom_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    # service-layer exceptions
    handled = _handle_service_error(exc)
    if handled is not None:
        return handled

    # Django-level wrappers DRF doesn't auto-translate cleanly
    if isinstance(exc, Http404):
        return _envelope("Resource not found.", code="not_found", status_code=http_status.HTTP_404_NOT_FOUND)

    if isinstance(exc, PermissionDenied):
        return _envelope(
            str(exc) or "You do not have permission to perform this action.",
            code="permission_denied",
            status_code=http_status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, ObjectDoesNotExist):
        return _envelope(
            str(exc) or "Resource not found.",
            code="not_found",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DjangoValidationError):
        return _envelope(
            "Validation failed.",
            code="validation_error",
            status_code=http_status.HTTP_400_BAD_REQUEST,
            data={"errors": _flatten_django_errors(exc)},
        )

    # DRF exceptions (let DRF render headers/throttle Retry-After)
    response = drf_exception_handler(exc, context)
    if response is not None:
        return _wrap_drf_response(exc, response)

    # everything else: 500
    logger.exception(
        "Unhandled exception in view: %s",
        exc,
        extra={"view": context.get("view"), "request": context.get("request")},
    )
    return _envelope(
        "An unexpected error occurred. Please try again later.",
        code="internal_error",
        status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

# Translate a ServiceError without forcing every app to know its module path.

def _handle_service_error(exc: Exception) -> Response | None:
    try:
        from accounts.services.exceptions import ServiceError
    except Exception:
        return None

    if not isinstance(exc, ServiceError):
        return None

    extra: dict[str, Any] = {}
    if exc.context:
        extra["data"] = exc.context
    return _envelope(
        exc.message,
        code=exc.code,
        status_code=exc.status_code,
        **extra,
    )


def _wrap_drf_response(exc: drf_exceptions.APIException, response: Response) -> Response:
    code = getattr(exc, "default_code", None) or "error"
    detail = response.data
    message = _humanise(detail)
    payload = {
        "status": False,
        "message": message,
        "data": _extract_field_errors(detail),
        "code": code,
    }
    if getattr(exc, "wait", None):
        payload["retry_after"] = exc.wait
    response.data = payload
    return response


def _envelope(
    message: str,
    *,
    code: str,
    status_code: int,
    data: Any = None,
) -> Response:
    return Response(
        {
            "status": False,
            "message": message,
            "data": data if data is not None else {},
            "code": code,
        },
        status=status_code,
    )

# Pull a human-readable summary out of DRF's nested error payloads.

def _humanise(detail: Any) -> str:
    if detail is None:
        return "Request failed."
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        if "detail" in detail and isinstance(detail["detail"], str):
            return detail["detail"]
        for value in detail.values():
            summary = _humanise(value)
            if summary and summary != "Request failed.":
                return summary
        return "Validation failed."
    if isinstance(detail, (list, tuple)) and detail:
        return _humanise(detail[0])
    return str(detail)


def _extract_field_errors(detail: Any) -> Any:
    if isinstance(detail, dict) and not (set(detail.keys()) == {"detail"}):
        return {"errors": detail}
    return {}


def _flatten_django_errors(exc: DjangoValidationError) -> Any:
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return list(exc.messages)

