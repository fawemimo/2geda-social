from __future__ import annotations

from accounts.services.exceptions import ServiceError
from django.utils.dateparse import parse_date, parse_datetime
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from search.enums import SearchType
from search.serializers import SearchResponseSerializer, serialize_results
from search.services import SearchService
from utils.pagination import MAX_PAGE_SIZE
from utils.responses import APIResponse


def _parse_datetime_param(request, name: str):
    """Accept either a bare date (2026-01-31) or a full ISO timestamp."""
    raw = request.query_params.get(name, "").strip()
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        parsed_date = parse_date(raw)
        if parsed_date is None:
            raise ServiceError(
                f"'{name}' must be an ISO 8601 date or datetime, got '{raw}'.",
                code="invalid_date",
            )
        from datetime import datetime, time, timezone as dt_timezone

        parsed = datetime.combine(parsed_date, time.min, tzinfo=dt_timezone.utc)
    return parsed


class SearchView(APIView):
    """One endpoint, every searchable type, with the matching types reported back.

    `GET /api/v2/search/?q=dancing` returns the ranked hits plus a `types` array
    of per-type counts, so a client can render "Users (4) Posts (128) Media (2)"
    tabs and then narrow with `?types=posts,media` without a second round trip.

    On PostgreSQL the matching is index-backed full-text search over each
    model's `search_vector` column, with web-search query syntax (quoted
    phrases, `or`, `-` exclusions) and stemming. Elsewhere -- or if the search
    triggers have not been migrated -- it falls back to substring matching, and
    the `engine` field in the response says which one ran.
    """

    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_id="search_all",
        manual_parameters=[
            openapi.Parameter(
                "q", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=True,
                description=(
                    "The search term. Minimum 2 characters. On PostgreSQL this "
                    'accepts web-search syntax: "quoted phrases", or, -exclusions.'
                ),
            ),
            openapi.Parameter(
                "types", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False,
                description=(
                    "Comma-separated types to search. Omit to search all. "
                    f"One or more of: {', '.join(SearchType.values())}."
                ),
            ),
            openapi.Parameter(
                "media_type", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False,
                description="Narrow media results to image/video/audio/document/gif. Requires types=media.",
            ),
            openapi.Parameter(
                "date_from", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False,
                description="Only items created on or after this ISO 8601 date/datetime.",
            ),
            openapi.Parameter(
                "date_to", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False,
                description="Only items created on or before this ISO 8601 date/datetime.",
            ),
            openapi.Parameter(
                "sort", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False,
                description="'relevance' (default) orders each type by match score and interleaves the types; 'recent' orders everything by newest first.",
            ),
            openapi.Parameter(
                "page", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False,
                description=(
                    "Page number, 1-based. Results are interleaved across types in "
                    "Python, so pages deeper than the first 200 rows per type may "
                    "return fewer results than totalItem implies."
                ),
            ),
            openapi.Parameter(
                "page_size", openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False,
                description=f"Items per page. Max {MAX_PAGE_SIZE}.",
            ),
        ],
        responses={200: SearchResponseSerializer()},
    )
    def get(self, request):
        query = request.query_params.get("q", "").strip()

        types_param = request.query_params.get("types", "").strip()
        types = [part.strip() for part in types_param.split(",")] if types_param else None

        page = self._positive_int(request.query_params.get("page", 1), "page", default=1)
        page_size = self._positive_int(
            request.query_params.get("page_size", 20), "page_size", default=20
        )
        if page_size > MAX_PAGE_SIZE:
            page_size = MAX_PAGE_SIZE

        try:
            result = SearchService().search(
                query=query,
                types=types,
                media_type=request.query_params.get("media_type", "").strip() or None,
                date_from=_parse_datetime_param(request, "date_from"),
                date_to=_parse_datetime_param(request, "date_to"),
                sort=request.query_params.get("sort", "relevance").strip() or "relevance",
                page=page,
                page_size=page_size,
                user=request.user,
            )
        except ServiceError as e:
            return APIResponse.error(message=e.message, code=e.code, status_code=e.status_code)

        return APIResponse.success(
            message="Search results fetched successfully.",
            data=serialize_results(result, request=request),
            extra={
                "query": result.query,
                "tokens": result.tokens,
                "types": result.facets,
                "appliedFilters": result.applied_filters,
                "engine": result.engine,
                "currentPage": result.page,
                "nextPage": result.page + 1 if result.has_next else None,
                "previousPage": result.page - 1 if result.has_previous else None,
                "totalPages": result.total_pages,
                "totalItem": result.total,
                "totalPerPage": result.page_size,
            },
        )

    def _positive_int(self, raw, name: str, *, default: int) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ServiceError(
                f"'{name}' must be a positive integer.", code="invalid_pagination",
            )
        if value < 1:
            raise ServiceError(
                f"'{name}' must be a positive integer.", code="invalid_pagination",
            )
        return value


class SearchTypeListView(APIView):
    """The valid `types` values, so a client need not hardcode the list."""

    permission_classes = [AllowAny]

    @swagger_auto_schema(operation_id="search_types", responses={200: "Available search types"})
    def get(self, request):
        return APIResponse.success(
            message="Search types fetched successfully.",
            data=[{"value": value, "label": label} for value, label in SearchType.choices()],
            status_code=status.HTTP_200_OK,
        )
