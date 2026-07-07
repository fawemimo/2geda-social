# Notifications WebSocket — Commands & Payloads

**Consumer**: `notifications/consumers.py` — `NotificationConsumer`  
**Endpoint**: `ws://<host>/ws/notifications/?token=<JWT_ACCESS_TOKEN>`  
**Group**: `notify_{user_id}`  

---

## Connection

On successful authentication the server responds with the current unread count:

```json
{
  "type": "connected",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "unread_count": 5
}
```

**Error envelope:**
```json
{
  "type": "error",
  "code": "unknown_type",
  "message": "Unknown type: invalid_type"
}
```

---

## Heartbeat

### `ping`

**Request:**
```json
{"type": "ping"}
```

**Response:**
```json
{"type": "pong"}
```

---

## Commands

### `mark_read`

Mark a single notification as read.

**Request:**
```json
{
  "type": "mark_read",
  "notification_id": "notif-uuid-1"
}
```

**Response:**
```json
{
  "type": "marked_read",
  "notification_id": "notif-uuid-1",
  "unread_count": 4
}
```

---

### `mark_all_read`

Mark all notifications as read.

**Request:**
```json
{
  "type": "mark_all_read"
}
```

**Response:**
```json
{
  "type": "marked_all_read",
  "marked_count": 5,
  "unread_count": 0
}
```

---

## Outbound Events (Server → Client)

### `notification`

Delivered when a new notification is created (like, comment, follow, message, etc.).

```json
{
  "type": "notification",
  "id": "notif-uuid-1",
  "notification_type": "new_follower",
  "category": "following",
  "title": "@alice started following you",
  "body": "",
  "is_read": false,
  "is_sent_push": false,
  "created_at": "2026-07-05T12:00:00+00:00",
  "actor": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "alice"
  },
  "source": {
    "content_type": "follow",
    "object_id": "follow-uuid-1"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `notification_type` | string | `new_follower`, `post_liked`, `post_commented`, `post_reshared`, `comment_liked`, `comment_replied`, `new_message`, etc. |
| `category` | string | `social`, `following`, `mention`, `chat`, `system`, `marketing` |
| `title` | string | Human-readable notification text |
| `body` | string | Optional detail text |
| `actor` | object | `{id, username}` of the user who triggered the notification |
| `source` | object | `{content_type, object_id}` of the source model (Post, Comment, Follow, etc.) |

---

### `unread_count`

Broadcast when the user's unread count changes (e.g. a new notification arrives while connected).

```json
{
  "type": "unread_count",
  "unread_count": 6
}
```
