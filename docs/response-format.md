# Unified API Response Format

Every endpoint returns the same envelope — success or error, single object or paginated list. Clients get to parse one shape forever.

The contract lives in three files:

| File                      | Owns                                                          |
| ------------------------- | ------------------------------------------------------------- |
| `utils/responses.py`      | `APIResponse.success` / `.error` / `.paginated` builders      |
| `utils/pagination.py`     | `StandardPagination`, `CursorStandardPagination`              |
| `utils/exceptions.py`     | `custom_exception_handler` — wraps every error in the envelope |

`REST_FRAMEWORK["EXCEPTION_HANDLER"]` points at `custom_exception_handler` so views never need try/except.

---

## Shapes

### Success (single / object)

```json
{
  "status":  true,
  "message": "Profile fetched successfully.",
  "data":    { "...": "..." }
}
```

`data` is always present — `null` is normalised to `{}` so client parsers don't need null-handling per field.

### Error

```json
{
  "status":  false,
  "message": "OTP has expired.",
  "data":    {},
  "code":    "otp_expired"
}
```

`code` is a stable machine-readable identifier — clients should switch on it, not on `message`. Common codes:

| `code`                          | When                                                        | HTTP |
| ------------------------------- | ----------------------------------------------------------- | ---- |
| `validation_error`              | Bad/missing input                                           | 400  |
| `not_found`                     | Resource doesn't exist                                       | 404  |
| `conflict` / `account_exists`   | Unique-constraint clash                                      | 409  |
| `authentication_failed`         | Bad creds / invalid token                                    | 401  |
| `permission_denied`             | Auth'd but not allowed                                       | 403  |
| `account_locked`                | Brute-force lockout                                          | 423  |
| `account_inactive`              | Account is inactive                                          | 403  |
| `rate_limited`                  | DRF throttle hit                                             | 429  |
| `otp_invalid` / `otp_expired` / `otp_max_attempts` / `otp_cooldown` / `otp_quota_exceeded` | OTP problems | 400 / 429 |
| `pending_registration_missing`  | Lost/expired pre-signup payload                              | 404  |
| `internal_error`                | Uncaught exception                                           | 500  |

For DRF-thrown `Throttled` errors, the response additionally carries `retry_after` (seconds).

### Paginated

```json
{
  "status":       true,
  "message":      "Items fetched successfully.",
  "data":         [ /* the page of items */ ],
  "currentPage":  1,
  "nextPage":     2,
  "previousPage": null,
  "totalPages":   10,
  "totalItem":    200,
  "totalPerPage": 20
}
```

`nextPage` and `previousPage` are `null` at the edges. `currentPage`, `nextPage`, `previousPage`, `totalPages` are integers (or `null` for cursor pagination).

Custom message per view:

```python
class DeviceListCreateView(APIView):
    pagination_message = "Devices fetched successfully."
    ...
```

If `pagination_message` is unset, the paginator falls back to `"Items fetched successfully."`.

### Cursor pagination (unbounded feeds)

`CursorStandardPagination` uses the same envelope shape but reports unknowable fields as `null`:

```json
{
  "status":       true,
  "message":      "Items fetched successfully.",
  "data":         [ ... ],
  "nextPage":     "http://.../?cursor=cD0yMDI2LTA1LTIzKzEy",
  "previousPage": null,
  "currentPage":  null,
  "totalPages":   null,
  "totalItem":    null,
  "totalPerPage": 20
}
```

Clients should treat `currentPage`/`totalItem` as optional when paginating cursor-based endpoints.

---

## Using `APIResponse` in views

```python
from utils.responses import APIResponse

class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return APIResponse.success(
            message="Current user fetched successfully.",
            data=UserMeSerializer(request.user).data,
        )
```

For errors, just raise the appropriate `ServiceError` subclass — the global handler will wrap it.

```python
from accounts.services.exceptions import NotFoundError

if not user:
    raise NotFoundError("No account found for this email.", code="user_not_found")
```

For paginating:

```python
from utils.pagination import StandardPagination

paginator = StandardPagination()
page = paginator.paginate_queryset(qs, request, view=self)
return paginator.get_paginated_response(MySerializer(page, many=True).data)
```

The paginator's `get_paginated_response` already produces the standard envelope.

---

## The exception handler

`utils/exceptions.py` translates, in order:

1. `accounts.services.exceptions.ServiceError` → uses the exception's own `code` + `status_code`.
2. `django.http.Http404` → 404 `not_found`.
3. `django.core.exceptions.PermissionDenied` → 403 `permission_denied`.
4. `django.core.exceptions.ObjectDoesNotExist` → 404 `not_found`.
5. `django.core.exceptions.ValidationError` → 400 `validation_error` with field-level details under `data.errors`.
6. Any `rest_framework.exceptions.APIException` → DRF renders it; we re-wrap the body into the envelope and preserve `Retry-After`.
7. Anything else → 500 `internal_error`, logged with full stack.

Clients always see the same shape regardless of where the error originated.

---

## Do / Don't

**Do**

- Use `APIResponse.success(...)` everywhere a view returns data.
- Raise `ServiceError` subclasses with stable `code` values; let the handler translate.
- Set `pagination_message` on list views for clarity.

**Don't**

- Construct a `Response({...})` directly — drift starts there.
- Catch `ServiceError` inside a view to add fields — extend the exception (`context=...`) instead.
- Return `null` for `data` — always pick `{}` or `[]`.
