from __future__ import annotations

from typing import Any

from rest_framework import status as http_status
from rest_framework.response import Response

# Thin builders returning a DRF Response with the standard envelope.

class APIResponse:

    @staticmethod
    def success(
        message: str = "Request completed successfully.",
        data: Any = None,
        *,
        status_code: int = http_status.HTTP_200_OK,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        payload: dict[str, Any] = {
            "status": True,
            "message": message,
            "data": _coerce(data),
        }
        if extra:
            payload.update(extra)
        return Response(payload, status=status_code, headers=headers)

    @staticmethod
    def error(
        message: str = "Request failed.",
        *,
        data: Any = None,
        code: str | None = None,
        status_code: int = http_status.HTTP_400_BAD_REQUEST,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        payload: dict[str, Any] = {
            "status": False,
            "message": message,
            "data": _coerce(data),
        }
        if code:
            payload["code"] = code
        if extra:
            payload.update(extra)
        return Response(payload, status=status_code, headers=headers)

    @staticmethod
    def paginated(
        *,
        items: list[Any],
        message: str = "Items fetched successfully.",
        current_page: int,
        total_per_page: int,
        total_item: int,
        total_pages: int,
        next_page: int | None,
        previous_page: int | None,
        status_code: int = http_status.HTTP_200_OK,
        extra: dict[str, Any] | None = None,
    ) -> Response:
        payload: dict[str, Any] = {
            "status": True,
            "message": message,
            "data": items,
            "currentPage": current_page,
            "nextPage": next_page,
            "previousPage": previous_page,
            "totalPages": total_pages,
            "totalItem": total_item,
            "totalPerPage": total_per_page,
        }
        if extra:
            payload.update(extra)
        return Response(payload, status=status_code)

# Normalise None to an empty object so the schema is stable for clients.

def _coerce(data: Any) -> Any:
    if data is None:
        return {}
    return data

