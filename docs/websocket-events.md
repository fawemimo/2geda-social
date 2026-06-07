# Social App — WebSocket Events Reference

## Overview

The Social app uses Django Channels (Redis-backed) to deliver real-time events to connected clients. There are **three WebSocket endpoints** in the social app, plus two from sibling apps (chats and notifications) documented separately.

All WebSocket connections authenticate via a **JWT access token** passed as a query-string parameter `token`.

---

## Connection & Authentication

All consumers follow the same authentication pattern:

```
ws://host:port/ws/<path>/?token=<JWT_ACCESS_TOKEN>
```

If the token is missing, expired, or invalid, the server closes the connection immediately.

On successful connection each consumer sends a `connected` confirmation:

```json
{
  "type": "connected",
  "user_id": "uuid",
  "post_id": "uuid"              // only present on PostConsumer
}
```

Clients should maintain a **heartbeat** by sending `{"type": "ping"}` periodically (e.g. every 30 s). The server replies with `{"type": "pong"}`.

---

## WebSocket Endpoints

### 1. `ws/posts/<post_id>/` — PostConsumer

**Group**: `post_{post_id}` — one group per post

**Purpose**: Delivers real-time events scoped to a single post — likes, comments, reshares, post updates/deletions, and typing indicators.

**Inbound Messages** (client → server):

| Type | Payload | Description |
|------|---------|-------------|
| `ping` | `{"type": "ping"}` | Heartbeat |
| `typing.start` | `{"type": "typing.start"}` | User started typing a comment |
| `typing.stop` | `{"type": "typing.stop"}` | User stopped typing a comment |

**Outbound Events** (server → client):

| Event | Triggered By | Group |
|-------|-------------|-------|
| `like_update` | Post liked/unliked | `post_{post_id}` |
| `comment_like_update` | Comment liked/unliked | `post_{parent_post_id}` |
| `comment.new` | New comment or reply created | `post_{post_id}` |
| `comment.deleted` | Comment soft-deleted | `post_{post_id}` |
| `post.updated` | Post body/visibility edited | `post_{post_id}` |
| `post.deleted` | Post soft-deleted | `post_{post_id}` |
| `reshare.new` | Post reshared | `post_{original_post_id}` |
| `reshare.deleted` | Reshare removed | `post_{original_post_id}` |
| `typing.start` | User started typing (relayed) | `post_{post_id}` |
| `typing.stop` | User stopped typing (relayed) | `post_{post_id}` |

---

### 2. `ws/feed/` — FeedConsumer

**Group**: `user_{user_id}` — one group per user

**Purpose**: Delivers events relevant to the authenticated user's personal feed — new posts from followed users and real-time follow/unfollow notifications.

**Inbound Messages** (client → server):

| Type | Payload | Description |
|------|---------|-------------|
| `ping` | `{"type": "ping"}` | Heartbeat |

**Outbound Events** (server → client):

| Event | Triggered By | Group |
|-------|-------------|-------|
| `post.new` | New post created by a followed user | `user_{follower_id}` |
| `presence.follow` | User followed the recipient | `user_{following_id}` |
| `presence.unfollow` | User unfollowed the recipient | `user_{following_id}` |

---

### 3. `ws/notifications/` — NotificationConsumer (notifications app)

**Group**: `notify_{user_id}`

**Purpose**: Delivers push-style notifications (likes, comments, follows, etc.) directly to the recipient.

**Reference**: See `notifications/consumers.py` and `notifications/dispatcher.py`.

---

### 4. `ws/chat/` — DirectChatConsumer (chats app)

**Group**: `user_{user_id}` / `chat_{conversation_id}`

**Purpose**: Real-time direct messaging, typing indicators, presence, and WebRTC call signalling.

**Reference**: See `chats/consumers.py`.

---

## Event Payloads — Full Reference

### `like_update` — (Post group)

Sent when a user likes or unlikes a post.

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

**How it works**: `LikeService.toggle()` in `social/services/like.py:84-95` calls `broadcast_post_event()` after creating or deleting the `Like` record. The denormalized `Post.likes_count` is read after the signal-based counter update so the value is accurate.

---

### `comment_like_update` — (Post group)

Sent when a user likes or unlikes a comment.

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

| Field | Type | Description |
|-------|------|-------------|
| `action` | `"liked"` \| `"unliked"` | Whether the like was added or removed |
| `user_id` | UUID string | The user who performed the action |
| `username` | string | Username of that user |
| `likes_count` | int | Updated total likes on the comment |
| `comment_id` | UUID string | The comment that was liked/unliked |

**How it works**: Same flow as `like_update` but for comments. The event is broadcast to the **parent post's group** (`post_{comment.post_id}`) so all viewers of the post see the comment's like count update.

---

### `comment.new` — (Post group)

Sent when a new comment (top-level or reply) is created on a post.

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
| `comment_id` | UUID string | The new comment's ID |
| `author_id` | UUID string | Comment author's user ID |
| `author_username` | string | Comment author's username |
| `body` | string | Comment text (truncated to 500 chars) |
| `parent_id` | UUID string \| `null` | `null` = top-level comment; UUID = reply to that parent |
| `post_id` | UUID string | The post the comment belongs to |
| `comments_count` | int | Updated total comments on the post |

**How it works**: `CommentService.create()` in `social/services/comment.py:44-53` calls `broadcast_post_event()` after the `Comment` is created and the post's `comments_count` is refreshed. The `parent_id` field allows clients to nest replies under the correct parent in the UI.

---

### `comment.deleted` — (Post group)

Sent when a comment is soft-deleted.

```json
{
  "type": "post_event",
  "event": "comment.deleted",
  "comment_id": "660e8400-e29b-41d4-a716-446655440001",
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "comments_count": 14
}
```

| Field | Type | Description |
|-------|------|-------------|
| `comment_id` | UUID string | The deleted comment's ID |
| `post_id` | UUID string | The parent post |
| `comments_count` | int | Updated total comments on the post |

**How it works**: `CommentService.delete()` calls `broadcast_post_event()` after the comment's `delete()` method runs. The post's `comments_count` is re-read from the database (already decremented by the signal).

---

### `post.updated` — (Post group)

Sent when a post's body, visibility, or other editable fields are updated.

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
| `post_id` | UUID string | The updated post |
| `author_id` | UUID string | Post author's user ID |
| `body` | string | New body text (truncated to 500 chars) |
| `visibility` | `"public"` \| `"followers"` \| `"private"` | New visibility setting |

**How it works**: `PostService.update()` in `social/services/post.py:95-101` broadcasts after `instance.save()` succeeds. Clients listening to the post's group can update the displayed content without a full page refresh.

---

### `post.deleted` — (Post group)

Sent when a post is soft-deleted.

```json
{
  "type": "post_event",
  "event": "post.deleted",
  "post_id": "770e8400-e29b-41d4-a716-446655440002"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `post_id` | UUID string | The deleted post |

**How it works**: `PostService.delete()` in `social/services/post.py:107-113` broadcasts after soft-delete. Clients should remove the post from the view or show a "deleted" placeholder.

---

### `reshare.new` — (Post group)

Sent when a user reshares a post.

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

| Field | Type | Description |
|-------|------|-------------|
| `reshare_id` | UUID string | The reshare record ID |
| `user_id` | UUID string | The user who reshared |
| `username` | string | Username of that user |
| `post_id` | UUID string | The original post that was reshared |
| `reshares_count` | int | Updated total reshares on the original post |

**How it works**: `ReshareService.create()` in `social/services/reshare.py:49-56` broadcasts after creating the `Reshare` record and refreshing the original post's counter. The event goes to the **original post's group** so viewers see the reshare count update.

---

### `reshare.deleted` — (Post group)

Sent when a user removes their reshare.

```json
{
  "type": "post_event",
  "event": "reshare.deleted",
  "post_id": "770e8400-e29b-41d4-a716-446655440002",
  "reshares_count": 4
}
```

| Field | Type | Description |
|-------|------|-------------|
| `post_id` | UUID string | The original post |
| `reshares_count` | int | Updated total reshares |

---

### `typing.start` / `typing.stop` — (Post group)

Relayed from one client to all other clients viewing the same post.

**Inbound** (client → server):

```json
{
  "type": "typing.start"
}
```

**Outbound** (server → all other group members):

```json
{
  "type": "post_event",
  "event": "typing.start",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | UUID string | The user who is typing |
| `username` | string | Username of the typing user |

**How it works**: `PostConsumer._handle_typing_start()` and `_handle_typing_stop()` in `social/consumers.py:79-99` relay the event to the entire post group via `channel_layer.group_send()`. The sender does **not** receive their own typing event back — Channels sends only to other members of the group. Clients should debounce `typing.start` and send `typing.stop` after a pause (e.g. 3 s without input).

---

### `post.new` — (Feed group)

Sent to a user's feed when someone they follow creates a new post.

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

| Field | Type | Description |
|-------|------|-------------|
| `post_id` | UUID string | The new post |
| `author_id` | UUID string | Post author's user ID |
| `author_username` | string | Post author's username |
| `body` | string | Post text (truncated to 500 chars) |
| `visibility` | `"public"` \| `"followers"` \| `"private"` | Post visibility |

**How it works**: `PostService.create()` in `social/services/post.py:58-69` enqueues a **Celery task** `broadcast_post_to_followers.delay()`. The task (`social/tasks.py:153-171`) queries all accepted followers of the author and sends the event to each follower's `user_{follower_id}` group via `sync_broadcast_to_group()`. This fan-out is async so the post creation response is not blocked.

**Scalability note**: For users with hundreds of thousands of followers, this task can be optimised by batching group_send calls or using Redis pub/sub directly. The current implementation iterates serially; for high-traffic deployments, consider chunking the follower list and using `asyncio.gather()` or a dedicated stream processor.

---

### `presence.follow` / `presence.unfollow` — (Feed group)

Sent to a user in real-time when someone follows or unfollows them.

**Follow**:

```json
{
  "type": "presence_event",
  "event": "presence.follow",
  "follower_id": "550e8400-e29b-41d4-a716-446655440000",
  "follower_username": "alice"
}
```

**Unfollow**:

```json
{
  "type": "presence_event",
  "event": "presence.unfollow",
  "follower_id": "550e8400-e29b-41d4-a716-446655440000",
  "follower_username": "alice"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `follower_id` | UUID string | The user who followed/unfollowed |
| `follower_username` | string | Username of that user |

**How it works**: `FollowService.follow()` and `FollowService.unfollow()` in `social/services/follow.py:49-52, 69-72` call `broadcast_presence_event(following.id, ...)` after the follow record is created or deleted. The recipient's `user_{id}` group receives the event so their UI can update the follower count and show a notification in real-time.

---

### `trending.updated` — (Trending group)

Sent to the global `trending_feed` group whenever a post's engagement changes (like, comment, or reshare).

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
| `post_id` | UUID string | The post whose engagement changed |
| `action` | `"liked"` \| `"unliked"` \| `"commented"` \| `"reshared"` | What happened |
| `likes_count` | int | Updated likes on the post |
| `comments_count` | int | Updated comments on the post |
| `reshares_count` | int | Updated reshares on the post |

**How it works**: `broadcast_trending_event()` is called from three service methods:
- `LikeService._broadcast_like_event()` (`social/services/like.py:96-103`) — on like/unlike
- `CommentService.create()` (`social/services/comment.py:55-62`) — on new comment
- `ReshareService.create()` (`social/services/reshare.py:58-65`) — on new reshare

The `trending_feed` group is **global** — any client can subscribe by connecting to any consumer that adds itself to this group. Currently, no dedicated consumer subscribes to this group; clients that want trending updates can connect to a lightweight consumer or receive it through the feed consumer (extend `FeedConsumer` to join `trending_feed` on connect).

---

## Real-World Application Architecture

### Event Flow Diagram

```
┌──────────────┐      POST /api/v2/social/posts/{id}/like/
│   Mobile/Web  │ ───────────────────────────────────────────────►┌──────────────────┐
│   Client      │                                                   │  Django REST API  │
│              │◄─────────────────────────────────────────────────│  (PostViewSet)     │
└──────────────┘     200 { "liked": true }                        └────────┬─────────┘
       │                                                                    │
       │  ┌─────────────────────────────────────┐                          │
       │  │  WebSocket Connection (already open) │                         │
       │  │  ws://host/ws/posts/{id}/            │                         │
       │  └──────────────┬──────────────────────┘                          │
       │                 │                                                 │
       │                 │  {"type":"post_event",                          │
       │                 │   "event":"like_update",                        │
       │                 │   "action":"liked",                             ▼
       │                 │   "user_id":"...",                    ┌──────────────────┐
       │                 │   "likes_count":42}                   │  LikeService     │
       │                 │                                        │  .toggle()        │
       │                 │                                        └────────┬─────────┘
       │                 │                                                 │
       │                 │                                          ┌──────▼──────┐
       │                 │                                          │  Redis       │
       │                 │                                          │  Channel     │
       │                 │                                          │  Layer       │
       │                 │                                          │  (pub/sub)   │
       │                 │                                          └──────┬──────┘
       │                 │                                                 │
       │                 │◄─────── group_send("post_{id}", payload) ───────┘
       │                 │
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│  Client A    │  │  Client B    │
│ (liked post) │  │ (viewing)    │
│  ↑ receives  │  │  ↑ receives  │
│  same event  │  │  same event  │
│  (via group) │  │  (via group) │
└──────────────┘  └──────────────┘
```

### Channel Layer Groups

| Group Pattern | Purpose | Lifetime |
|--------------|---------|----------|
| `post_{post_id}` | Live updates for a single post | As long as ≥ 1 client is connected |
| `user_{user_id}` | Personal feed and presence | As long as the user is connected via `ws/feed/` |
| `trending_feed` | Global trending updates | Persistent (single group) |
| `notify_{user_id}` | Push notifications | As long as the user is connected via `ws/notifications/` |

### Broadcast Function Overview (`social/event_broadcaster.py`)

| Function | Used By | Group Target |
|----------|---------|-------------|
| `broadcast_post_event(post_id, event)` | LikeService, CommentService, PostService, ReshareService | `post_{post_id}` |
| `broadcast_feed_event(user_id, event)` | Celery task `broadcast_post_to_followers` | `user_{user_id}` |
| `broadcast_trending_event(event)` | LikeService, CommentService, ReshareService | `trending_feed` |
| `broadcast_presence_event(user_id, event)` | FollowService | `user_{user_id}` |
| `async_broadcast_post_event(post_id, event)` | Async context (consumer-to-consumer) | `post_{post_id}` |

The `sync_broadcast_to_group()` function bridges the sync service layer to the async Channels layer using `asyncio.run()`. The `async_broadcast_to_group()` variant is available for direct use in async consumers.

### Client-Side Integration Guide

#### Connecting to Post Events

```javascript
// Using native WebSocket
const postId = "770e8400-e29b-41d4-a716-446655440002";
const token = "eyJhbGciOi..."; // JWT access token

const ws = new WebSocket(`wss://host/ws/posts/${postId}/?token=${token}`);

ws.onopen = () => {
  console.log("Connected to post channel");
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch (data.type) {
    case "connected":
      console.log("Post WS ready:", data.post_id);
      break;

    case "post_event":
      handlePostEvent(data);
      break;
  }
};

function handlePostEvent(data) {
  switch (data.event) {
    case "like_update":
      // Update like button and counter
      updateLikeButton(data.user_id, data.action);
      updateLikeCount(data.likes_count);
      break;

    case "comment.new":
      // Prepend or append new comment
      addComment(data);
      updateCommentCount(data.comments_count);
      break;

    case "comment.deleted":
      // Remove comment from view
      removeComment(data.comment_id);
      updateCommentCount(data.comments_count);
      break;

    case "post.updated":
      // Refresh post content
      updatePostBody(data.body);
      break;

    case "post.deleted":
      // Show "post deleted" placeholder
      showPostDeleted();
      break;

    case "reshare.new":
    case "reshare.deleted":
      updateReshareCount(data.reshares_count);
      break;

    case "typing.start":
    case "typing.stop":
      showTypingIndicator(data.user_id, data.username, data.event === "typing.start");
      break;
  }
}

// Heartbeat
setInterval(() => {
  ws.send(JSON.stringify({ type: "ping" }));
}, 30000);

// Typing indicator
let typingTimeout;
function onCommentInput() {
  ws.send(JSON.stringify({ type: "typing.start" }));
  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(() => {
    ws.send(JSON.stringify({ type: "typing.stop" }));
  }, 3000);
}
```

#### Connecting to Feed Events

```javascript
const token = "eyJhbGciOi...";
const ws = new WebSocket(`wss://host/ws/feed/?token=${token}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === "feed_event" && data.event === "post.new") {
    // Prepend new post to the feed
    prependPostToFeed(data);
  }

  if (data.type === "presence_event") {
    if (data.event === "presence.follow") {
      showFollowNotification(data.follower_username);
      incrementFollowersCount();
    }
    if (data.event === "presence.unfollow") {
      showUnfollowNotification(data.follower_username);
      decrementFollowersCount();
    }
  }
};
```

---

## Performance & Scaling Considerations

1. **Fan-out on post creation**: The `broadcast_post_to_followers` task iterates followers serially over Redis `group_send`. For users with >100k followers, use chunked iteration with `asyncio.gather()` or a dedicated stream processor (e.g. Kafka → consumers).

2. **Group lifetime**: Channel layer groups are ephemeral — they exist only while at least one consumer is connected. There is no storage cost for inactive posts.

3. **Trending group**: The `trending_feed` group receives events on every like/comment/reshare system-wide. In high-traffic deployments, throttle or batch these events (e.g. send aggregated updates every 5 s instead of per-action).

4. **Redis memory**: Each group membership is stored in Redis SETs. With millions of concurrent connections, monitor Redis memory and consider sharding the channel layer.

5. **JWT Authentication**: The consumer manually parses the JWT from the query string. For production, consider using Django Channels' built-in `AuthMiddlewareStack` with a custom auth function that reads the JWT from the query string, simplifying the consumer code.

---

## Error Handling

If a client sends an unknown message type to `PostConsumer`, the server responds with an error:

```json
{
  "type": "error",
  "code": "unknown_type",
  "message": "Unknown type: invalid_type"
}
```

Clients should log or surface these errors gracefully.

---

## Testing

Tests for all WebSocket events are in `social/tests.py` in the following test classes:

| Test Class | Items Covered |
|------------|---------------|
| `TestRealTimeLikeBroadcast` | `like_update`, `comment_like_update` |
| `TestRealTimeCommentBroadcast` | `comment.new`, `comment.deleted` |
| `TestRealTimePostUpdateDelete` | `post.updated`, `post.deleted` |
| `TestRealTimePostCreateFeedBroadcast` | `post.new` (Celery task enqueued) |
| `TestRealTimeReshareBroadcast` | `reshare.new`, `reshare.deleted` |
| `TestRealTimeFollowPresence` | `presence.follow`, `presence.unfollow` |
| `TestRealTimeTrendingBroadcast` | `trending.updated` |

Run with:

```bash
pytest social/tests.py -v --reuse-db --no-migrations
```
