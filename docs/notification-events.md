# Notification Events

This document catalogs every notification type in the system — what triggers it, who receives it, and how it's delivered.

## Architecture Overview

```
Action → Service Layer → NotificationService.create(dto) → dispatch_notification.delay(id)
                                                                    │
                                                    ┌───────────────┴───────────────┐
                                                    ▼                               ▼
                                        WebSocket (group_send)            Push (Celery → Firebase)
                                        notify_{recipient_id}             send_user_push_notification
```◊

**Key files:**

| File | Role |
|---|---|
| `notifications/services/notification_services.py` | `NotificationService.create()` — persists the record, checks preference/actor mutes, builds group_key, upserts batches |
| `notifications/services/dto.py` | `CreateNotificationDTO` — typed input for notification creation |
| `notifications/tasks.py` | `dispatch_notification` — Celery task that calls `NotificationDispatcher.dispatch()` |
| `notifications/dispatcher.py` | Sends WS broadcast + fires push Celery task |
| `notifications/consumers.py` | WebSocket consumer — each user joins group `notify_{user.id}` |
| `accounts/tasks.py` | `send_user_push_notification` — sends FCM/APNs to all trusted device tokens |
| `accounts/models.py` | `UserDevice.push_token` — push tokens for delivery |
| `accounts/services/device.py` | `DeviceService.get_trusted_push_tokens()` — queries active push tokens |

**Delivery guarantees:**
- **In-app (WebSocket):** Best-effort real-time via channel layer group `notify_{recipient_id}`. The `NotificationConsumer` forwards events to the client.
- **Push (FCM/APNs):** Fired as a Celery task (`send_user_push_notification`) with `autoretry_for=(Exception,), max_retries=3, retry_backoff=True`. Iterates all trusted device tokens and sends via Firebase.

---

## Notification Types

### 1. Follow — `new_follower`

| Field | Value |
|---|---|
| **Trigger** | `FollowService.follow()` in `social/services.py` |
| **Recipient** | User who was followed |
| **Actor** | User who followed |
| **Source model** | `Follow` record |
| **Notification type** | `"new_follower"` |
| **Category** | `"following"` |
| **Title** | `@{actor.username} started following you` |
| **WS + Push** | Yes |

**Code path:**
```
social/services.py: FollowService.follow()
  → NotificationService.create(dto)
  → dispatch_notification.delay()
    → NotificationDispatcher.dispatch()
      → WS group_send("notify_{recipient_id}")
      → send_user_push_notification.delay()
```

---

### 2. Post — `post_commented`

| Field | Value |
|---|---|
| **Triggers** | `CommentService.create()` in `social/services.py` |
| **Recipient** | Post author (if commenter ≠ author) |
| **Actor** | Comment author |
| **Source model** | `Post` |
| **Notification type** | `"post_commented"` |
| **Category** | `"social"` |
| **Title** | `@{actor.username} commented on your post` |
| **WS + Push** | Yes |

**Also notifies followers (fanout):**
The same action triggers `notify_followers.delay()` which iterates all followers of the commenter and creates a notification for each.

**Code path:**
```
social/services.py: CommentService.create()
  → NotificationService.create(dto)  (to post author)
  → dispatch_notification.delay()
  → notify_followers.delay()          (fanout to followers)
```

---

### 3. Reply — `comment_replied`

| Field | Value |
|---|---|
| **Trigger** | `CommentService.create()` when `parent_id` is set |
| **Recipient** | Parent comment author (if ≠ replier) |
| **Actor** | Reply author |
| **Source model** | `Comment` |
| **Notification type** | `"comment_replied"` |
| **Category** | `"social"` |
| **Title** | `@{actor.username} replied to your comment` |
| **WS + Push** | Yes |

---

### 4. Reshare — `post_reshared`

| Field | Value |
|---|---|
| **Trigger** | `ReshareService.create()` in `social/services.py` |
| **Recipient** | Original post author (if ≠ reshared_by) |
| **Actor** | User who reshared |
| **Source model** | `Post` (the original) |
| **Notification type** | `"post_reshared"` |
| **Category** | `"social"` |
| **Title** | `@{actor.username} reshared your post` |
| **WS + Push** | Yes |

**Also notifies followers (fanout):**
`notify_followers.delay()` fires to all followers of the resharer.

---

### 5. Like — `post_liked` / `comment_liked`

| Field | Value |
|---|---|
| **Trigger** | `LikeService.toggle()` in `social/services.py` |
| **Recipient** | Post/comment author (if ≠ liker) |
| **Actor** | User who liked |
| **Source model** | `Post` or `Comment` |
| **Notification type** | `"post_liked"` or `"comment_liked"` |
| **Category** | `"social"` |
| **Title** | `@{actor.username} liked your post` / `@{actor.username} liked your comment` |
| **WS + Push** | Yes |

**Also notifies followers (fanout):**
`notify_followers.delay()` fires to all followers of the liker.

**Unlike:** When a like is removed, no notification is sent (no "unlike" event).

---

### 6. New Message — `new_message`

| Field | Value |
|---|---|
| **Trigger** | `ChatService.send_message()` in `chats/services/chat_service.py` |
| **Recipient** | All conversation members except sender, unless `is_muted=True` |
| **Actor** | Message sender |
| **Source model** | `Message` |
| **Notification type** | `"new_message"` |
| **Category** | `"chat"` |
| **Title** | `@{actor.username} sent you a message` |
| **Body** | Message preview (first 200 chars) |
| **WS + Push** | Yes |
| **Skip if** | Recipient has `ConversationMember.is_muted=True` |

**Code path:**
```
chats/services/chat_service.py: ChatService.send_message()
  → for each non-muted, non-sender member:
    → NotificationService.create(dto)
    → dispatch_notification.delay()
```

---

## Follower Notification Fanout

When a user creates a post, reshare, comment, or like, all their followers receive a notification via the `notify_followers` Celery task.

| Action | Notification type sent to followers |
|---|---|
| Post created | `"post_commented"` |
| Reshare created | `"post_reshared"` |
| Comment created | `"post_commented"` |
| Like toggled (on) | `"post_liked"` or `"comment_liked"` |

**Task:** `social/tasks.notify_followers`
- Queries `Follow.objects.filter(following_id=actor_id, status=ACCEPTED)`
- Creates one `Notification` per follower via `NotificationService.create()`
- Dispatches each via `dispatch_notification.delay()`
- Uses `transaction.on_commit()` in the service layer so the fanout only fires after DB commit
- Individual errors are caught per follower so one failure doesn't block others

---

## Notification Model Reference

```
Notification
├── recipient        FK → User         (who gets it)
├── actor            FK → User         (who triggered it, nullable for system)
├── notification_type CharField(30)    (from NotificationType enum)
├── category         CharField(15)     (derived from type)
├── priority         CharField(8)      (normal / high / urgent)
├── content_type     FK → ContentType  (source object type)
├── object_id        UUID              (source object PK)
├── title            CharField(200)
├── body             TextField(1000)
├── action_url       CharField(500)    (deep-link for client)
├── metadata         JSONField
├── is_read          BooleanField
├── group_key        CharField(200)    (for batch collapsing)
├── is_sent_push     BooleanField      (delivery tracking)
└── is_sent_ws       BooleanField      (delivery tracking)
```

---

## REST API Endpoints

All endpoints under `/api/v2/notifications/`, require JWT auth.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Inbox (paginated, `?category=`, `?unread_only=true`) |
| GET | `/unread-count/` | Total unread badge count |
| GET | `/unread-count-by-category/` | Per-category unread breakdown |
| POST | `/{id}/read/` | Mark single notification read |
| POST | `/{id}/unread/` | Mark single notification unread |
| POST | `/mark-all-read/` | Mark all read (`{"category": "social"}` optional) |
| DELETE | `/{id}/` | Soft-delete single |
| DELETE | `/delete-all/` | Delete all (`?category=social` optional) |
| GET | `/preferences/` | List per-category preferences |
| PUT | `/preferences/update/` | Upsert preference (`category`, `push_enabled`, etc.) |
| GET | `/mutes/` | List active mutes |
| POST | `/mutes/actor/` | Mute an actor |
| POST | `/mutes/source/` | Mute a source object |
| POST | `/mutes/{id}/unmute/` | Remove a mute |
| POST | `/devices/register/` | Register push token via `UserDevice` |
| DELETE | `/devices/unregister/` | Remove push token from `UserDevice` |

---

## WebSocket Channel

```
ws://host/ws/notifications/?token=<jwt>
```

- Authenticated via JWT query param
- Joins group `notify_{user.id}`
- Receives `{"type": "notification", ...}` payloads
- Supports inbound: `mark_read`, `mark_all_read`, `ping`

---

## Notification Categories (for Preference/Mute)

| Category | Contains |
|---|---|
| `social` | post_liked, post_commented, post_reshared, comment_liked, comment_replied |
| `following` | new_follower, follow_request, follow_accepted |
| `mention` | mention_post, mention_comment |
| `chat` | new_message, group_added, group_removed |
| `system` | kyc_*, new_device_login, password_changed, account_suspended, referral_joined |
| `marketing` | announcement, promotion |

Users can toggle per-category channels (in_app, push, email) via `PUT /preferences/update/` or mute specific actors/sources via the `/mutes/` endpoints.
