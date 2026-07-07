# Social WebSocket — Commands & Events

Two consumers handle real-time social events:

- **PostConsumer** — `ws://<host>/ws/posts/<post_id>/?token=<JWT>` — per-post live updates
- **FeedConsumer** — `ws://<host>/ws/feed/?token=<JWT>` — per-user feed events

---

## PostConsumer

**File**: `social/consumers.py` — `PostConsumer`  
**Group**: `post_{post_id}`  

### Connection

```json
{
  "type": "connected",
  "post_id": "770e8400-e29b-41d4-a716-446655440002"
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

### `typing.start` / `typing.stop`

Notify other viewers of the post that the user is typing a comment.

**Request:**
```json
{"type": "typing.start"}
```
```json
{"type": "typing.stop"}
```

**Broadcast to all post viewers** (wrapped in `post_event`):
```json
{
  "type": "post_event",
  "event": "typing.start",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice"
}
```

---

## Outbound Events (Server → Client)

All outbound events for `PostConsumer` use the `post_event` wrapper type.  
All outbound events for `FeedConsumer` use `feed_event`, `presence_event`, or `trending_event` wrappers.

---

### `like_update` — (PostConsumer)

Fired when a user likes or unlikes a post.

```json
{
  "type": "post_event",
  "event": "like_update",
  "action": "liked",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "likes_count": 42
}
```

| Field | Type | Description |
|-------|------|-------------|
| `action` | `"liked"` \| `"unliked"` | Whether the like was added or removed |
| `user_id` | UUID string | The user who performed the action |
| `username` | string | Username of that user |
| `likes_count` | int | Updated total likes on the post |

---

### `comment_like_update` — (PostConsumer)

Fired when a user likes or unlikes a comment.

```json
{
  "type": "post_event",
  "event": "comment_like_update",
  "action": "liked",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "likes_count": 7,
  "comment_id": "660e8400-e29b-41d4-a716-446655440001"
}
```

---

### `comment.new` — (PostConsumer)

Fired when a new comment or reply is created on a post.

```json
{
  "type": "post_event",
  "event": "comment.new",
  "comment_id": "660e8400-e29b-41d4-a716-446655440001",
  "author_id": "550e8400-e29b-41d4-a716-446655440000",
  "author_username": "alice",
  "body": "Great post!",
  "parent_id": null,
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "comments_count": 15
}
```

| Field | Type | Description |
|-------|------|-------------|
| `parent_id` | UUID string \| `null` | `null` = top-level; UUID = reply to that comment |
| `body` | string | Comment text |
| `comments_count` | int | Updated total comments on the post |

---

### `comment.deleted` — (PostConsumer)

Fired when a comment is soft-deleted.

```json
{
  "type": "post_event",
  "event": "comment.deleted",
  "comment_id": "660e8400-e29b-41d4-a716-446655440001",
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "comments_count": 14
}
```

---

### `post.updated` — (PostConsumer)

Fired when a post's body, visibility, or other editable fields are updated.

```json
{
  "type": "post_event",
  "event": "post.updated",
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "author_id": "550e8400-e29b-41d4-a716-446655440000",
  "body": "Updated post content...",
  "visibility": "public"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `visibility` | `"public"` \| `"followers"` \| `"private"` | New visibility setting |

---

### `post.deleted` — (PostConsumer)

Fired when a post is soft-deleted.

```json
{
  "type": "post_event",
  "event": "post.deleted",
  "post_id": "770e8400-e29b-41d4-a716-446655440002"
}
```

---

### `reshare.new` — (PostConsumer)

Fired when a user reshares a post.

```json
{
  "type": "post_event",
  "event": "reshare.new",
  "reshare_id": "880e8400-e29b-41d4-a716-446655440003",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "reshares_count": 5
}
```

---

### `reshare.deleted` — (PostConsumer)

Fired when a user removes a reshare.

```json
{
  "type": "post_event",
  "event": "reshare.deleted",
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "reshares_count": 4
}
```

---

## FeedConsumer

**File**: `social/consumers.py` — `FeedConsumer`  
**Group**: `user_{user_id}`  

### Connection

```json
{
  "type": "connected",
  "user_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

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

### `post.new` — (FeedConsumer)

Fired when a followed user creates a new post. Delivered to all followers via Celery fan-out.

```json
{
  "type": "feed_event",
  "event": "post.new",
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "author_id": "550e8400-e29b-41d4-a716-446655440000",
  "author_username": "alice",
  "body": "Hello world...",
  "visibility": "public"
}
```

---

### `presence.follow` / `presence.unfollow` — (FeedConsumer)

Fired when someone follows or unfollows the recipient user.

```json
{
  "type": "presence_event",
  "event": "presence.follow",
  "follower_id": "550e8400-e29b-41d4-a716-446655440000",
  "follower_username": "alice"
}
```

```json
{
  "type": "presence_event",
  "event": "presence.unfollow",
  "follower_id": "550e8400-e29b-41d4-a716-446655440000",
  "follower_username": "alice"
}
```

---

### `trending.updated` — (Trending group)

Fired to the global `trending_feed` group when a post's engagement changes (like, comment, reshare).

```json
{
  "type": "trending_event",
  "event": "trending.updated",
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "action": "liked",
  "likes_count": 42,
  "comments_count": 15,
  "reshares_count": 5
}
```

| Field | Type | Description |
|-------|------|-------------|
| `action` | `"liked"` \| `"unliked"` \| `"commented"` \| `"reshared"` | What triggered the update |
