from __future__ import annotations

import pytest
from rest_framework import status

from utils.responses import APIResponse


pytestmark = pytest.mark.unit


class TestAPIResponseSuccess:
    def test_default_envelope_shape(self):
        resp = APIResponse.success()
        assert resp.status_code == 200
        assert resp.data == {
            "status": True,
            "message": "Request completed successfully.",
            "data": {},
        }

    def test_carries_dict_data(self):
        resp = APIResponse.success(message="ok", data={"user_id": "u1"})
        assert resp.data["data"] == {"user_id": "u1"}
        assert resp.data["status"] is True

    def test_carries_list_data(self):
        resp = APIResponse.success(data=[{"x": 1}, {"x": 2}])
        assert resp.data["data"] == [{"x": 1}, {"x": 2}]

    def test_none_data_normalised_to_empty_object(self):
        resp = APIResponse.success(data=None)
        assert resp.data["data"] == {}

    def test_extra_fields_merged_at_top_level(self):
        resp = APIResponse.success(extra={"trace_id": "abc"})
        assert resp.data["trace_id"] == "abc"

    def test_custom_status_code(self):
        resp = APIResponse.success(status_code=status.HTTP_201_CREATED)
        assert resp.status_code == 201

    def test_headers_propagate(self):
        resp = APIResponse.success(headers={"X-Trace": "abc"})
        assert resp["X-Trace"] == "abc"


class TestAPIResponseError:
    def test_envelope_shape(self):
        resp = APIResponse.error(message="boom")
        assert resp.status_code == 400
        assert resp.data == {
            "status": False,
            "message": "boom",
            "data": {},
        }

    def test_with_code_included(self):
        resp = APIResponse.error("nope", code="some_code")
        assert resp.data["code"] == "some_code"

    def test_explicit_status_code(self):
        resp = APIResponse.error(status_code=418)
        assert resp.status_code == 418


class TestAPIResponsePaginated:
    def test_envelope_includes_pagination_fields(self):
        resp = APIResponse.paginated(
            items=[{"id": 1}, {"id": 2}],
            message="Fetched",
            current_page=2,
            total_per_page=20,
            total_item=200,
            total_pages=10,
            next_page=3,
            previous_page=1,
        )
        assert resp.status_code == 200
        assert resp.data["status"] is True
        assert resp.data["message"] == "Fetched"
        assert resp.data["data"] == [{"id": 1}, {"id": 2}]
        assert resp.data["currentPage"] == 2
        assert resp.data["nextPage"] == 3
        assert resp.data["previousPage"] == 1
        assert resp.data["totalPages"] == 10
        assert resp.data["totalItem"] == 200
        assert resp.data["totalPerPage"] == 20

    def test_edge_pages_have_null_next_or_previous(self):
        resp = APIResponse.paginated(
            items=[],
            current_page=1,
            total_per_page=20,
            total_item=0,
            total_pages=1,
            next_page=None,
            previous_page=None,
        )
        assert resp.data["nextPage"] is None
        assert resp.data["previousPage"] is None

