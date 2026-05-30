from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory

from utils.pagination import StandardPagination


pytestmark = pytest.mark.unit


@pytest.fixture
def request_factory() -> APIRequestFactory:
    return APIRequestFactory()


def _items(n: int) -> list[dict]:
    return [{"id": i} for i in range(n)]


class TestStandardPagination:
    def test_middle_page_envelope(self, request_factory):
        paginator = StandardPagination()
        request = request_factory.get("/items/?page=2&page_size=5")
        page = paginator.paginate_queryset(_items(20), request)
        resp = paginator.get_paginated_response(page)

        assert resp.data["status"] is True
        assert resp.data["currentPage"] == 2
        assert resp.data["nextPage"] == 3
        assert resp.data["previousPage"] == 1
        assert resp.data["totalPages"] == 4
        assert resp.data["totalItem"] == 20
        assert resp.data["totalPerPage"] == 5
        assert resp.data["data"] == [{"id": i} for i in (5, 6, 7, 8, 9)]

    def test_first_page_has_no_previous(self, request_factory):
        paginator = StandardPagination()
        request = request_factory.get("/items/?page=1&page_size=5")
        page = paginator.paginate_queryset(_items(7), request)
        resp = paginator.get_paginated_response(page)
        assert resp.data["previousPage"] is None
        assert resp.data["nextPage"] == 2

    def test_last_page_has_no_next(self, request_factory):
        paginator = StandardPagination()
        request = request_factory.get("/items/?page=2&page_size=5")
        page = paginator.paginate_queryset(_items(7), request)
        resp = paginator.get_paginated_response(page)
        assert resp.data["nextPage"] is None
        assert resp.data["previousPage"] == 1

    def test_page_size_capped_at_max(self, request_factory):
        paginator = StandardPagination()
        request = request_factory.get("/items/?page=1&page_size=10000")
        paginator.paginate_queryset(_items(500), request)
        assert paginator.get_page_size(paginator.request) == paginator.max_page_size

    def test_view_can_override_pagination_message(self, request_factory):
        paginator = StandardPagination()
        request = request_factory.get("/items/")

        class _View:
            pagination_message = "Custom listing message."

        page = paginator.paginate_queryset(_items(3), request, view=_View())
        resp = paginator.get_paginated_response(page)
        assert resp.data["message"] == "Custom listing message."

    def test_default_message_when_view_has_none(self, request_factory):
        paginator = StandardPagination()
        request = request_factory.get("/items/")
        page = paginator.paginate_queryset(_items(3), request)
        resp = paginator.get_paginated_response(page)
        assert resp.data["message"] == StandardPagination.default_message

