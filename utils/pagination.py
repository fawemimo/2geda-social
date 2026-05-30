from __future__ import annotations

from collections import OrderedDict
from typing import Any

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200

# Page-number pagination wrapped in the project's response envelope.

class StandardPagination(PageNumberPagination):
    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE
    page_query_param = "page"

    # Allow views to override the human-readable message via `pagination_message`.
    default_message = "Items fetched successfully."

    def get_paginated_response(self, data: list[Any]) -> Response:
        paginator = self.page.paginator
        current = self.page.number
        total_pages = paginator.num_pages

        next_page = current + 1 if self.page.has_next() else None
        previous_page = current - 1 if self.page.has_previous() else None

        view = getattr(self, "_view", None)
        message = (
            getattr(view, "pagination_message", None)
            or self.default_message
        )

        envelope = OrderedDict(
            [
                ("status", True),
                ("message", message),
                ("currentPage", current),
                ("nextPage", next_page),
                ("previousPage", previous_page),
                ("totalPages", total_pages),
                ("totalItem", paginator.count),
                ("totalPerPage", self.get_page_size(self.request)),
                ("data", data)
            ]
        )
        return Response(envelope)

    def paginate_queryset(self, queryset, request, view=None):
        # Stash the view so get_paginated_response can pull a custom message.
        self._view = view
        return super().paginate_queryset(queryset, request, view)

# Cursor pagination for unbounded feeds (timelines, notifications).

class CursorStandardPagination(CursorPagination):
    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE
    ordering = "-created_at"

    def get_paginated_response(self, data: list[Any]) -> Response:
        envelope = OrderedDict(
            [
                ("status", True),
                ("message", "Items fetched successfully."),
                ("data", data),
                ("nextPage", self.get_next_link()),
                ("previousPage", self.get_previous_link()),
                ("currentPage", None),
                ("totalPages", None),
                ("totalItem", None),
                ("totalPerPage", self.get_page_size(self.request)),
            ]
        )
        return Response(envelope)

