# Devices and Profile

## Devices

Each row in `accounts_user_device` represents one logged-in client. A user can have many. Devices are the unit of "session" — revoking a device clears its push token and forces logout on that surface.

### Key fields

| Field                 | Notes                                                                          |
| --------------------- | ------------------------------------------------------------------------------ |
| `device_fingerprint`  | Stable client-generated hash (screen + GPU + fonts, etc.). NOT a UUID we mint. |
| `platform`            | `ios` / `android` / `web` / `desktop`                                          |
| `push_token`          | FCM / APNs token                                                                |
| `is_trusted`          | If true, 2FA prompts are skipped on this device                                 |
| `last_seen_at`        | Updated on every authenticated request (via `DeviceService.touch`)              |

The pair `(user, device_fingerprint)` is unique. Registering the "same" device twice is an `update_or_create`, not a new row.

### Lifecycle

```
register  ─▶  list  ─▶  touch (per-request)
                  │
                  ├─▶  update_push_token
                  ├─▶  trust
                  └─▶  revoke (soft-delete + clears push token)
```

`UserDevice.revoke()` calls the soft-delete `delete()` from `BaseModel.SoftDeleteMixin` — the row is preserved with `is_deleted=True` for audit/recovery.

`AuthenticationService.logout_everywhere(user)` soft-deletes every device for that user and blacklists every outstanding refresh token in one shot.

### Endpoints

| Method | Path                                          | Service call                                                       |
| ------ | --------------------------------------------- | ------------------------------------------------------------------ |
| GET    | `/me/devices/`                                | `DeviceService.list_for_user(user)` — paginated                    |
| POST   | `/me/devices/`                                | `DeviceService.register(user, payload, ip_address)`                |
| DELETE | `/me/devices/<uuid>/`                         | `DeviceService.revoke(user, device_id)`                            |
| POST   | `/me/devices/<uuid>/push-token/`              | `DeviceService.update_push_token(user, device_id, push_token)`     |
| POST   | `/me/devices/<uuid>/trust/`                   | `DeviceService.trust(user, device_id)`                             |

Ownership is enforced inside the service — calling endpoints with another user's device ID raises `PermissionDeniedError` (403).

### Sample POST `/me/devices/`

```json
{
  "name":               "Alice's iPhone 15",
  "platform":           "ios",
  "device_fingerprint": "ab12cd34...",
  "os_version":         "iOS 17.4",
  "app_version":        "1.2.3",
  "push_token":         "fcm-token-..."
}
```

Returns the `UserDevice` row inside the standard envelope.

---

## Profile

`accounts_user_profile` is a 1-to-1 with `User`. The profile is created automatically:

- On successful registration (`RegistrationService._persist_user`)
- Lazily by `ProfileService.get(user=...)` if it does not exist (defensive)

### Updatable fields

Defined in `ProfileService.UPDATABLE_USER_FIELDS` and `UPDATABLE_PROFILE_FIELDS`:

| On `User`     | On `UserProfile`                                              |
| ------------- | ------------------------------------------------------------- |
| `username`    | `display_name`, `bio`, `website`, `date_of_birth`, `is_private`, `avatar`, `cover_photo` |
| `phone_number`|                                                               |

Any field outside the whitelist raises `ValidationError(code="unknown_fields")`. Sneaking columns into a `PATCH` body cannot bypass this — the service ignores anything not whitelisted *and* returns an explicit error so clients learn fast.

### Endpoints

| Method        | Path             | Service call                                       |
| ------------- | ---------------- | -------------------------------------------------- |
| GET           | `/me/profile/`   | `ProfileService.get(user)`                         |
| PATCH         | `/me/profile/`   | `ProfileService.update_partial(user, data=dict)`   |

### Sample PATCH

```json
{
  "display_name": "Alice Wonderland",
  "bio":          "Curiouser and curiouser.",
  "is_private":   true
}
```

Response: the full updated profile wrapped in `APIResponse.success`.

### Deactivation

```python
ProfileService.deactivate(user=user)
```

Calls `User.soft_delete()` — flips `is_active=False`, `is_deleted=True`, sets `deleted_at`. There is no public endpoint for this yet; expose one when product needs it.
