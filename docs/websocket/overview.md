# WebSocket API Overview

All WebSocket endpoints across the project. Each connection authenticates via a JWT access token passed as a query parameter.

**Connection string format:**
```
ws://<host>/ws/<path>/?token=<JWT_ACCESS_TOKEN>
```

If the token is missing, expired, or invalid, the server closes the connection immediately.

---

## Endpoints

| Path | Consumer | File | Doc |
|------|----------|------|-----|
| `ws/chat/` | `DirectChatConsumer` | `chats/consumers.py` | [chat.md](./chat.md) |
| `ws/posts/<post_id>/` | `PostConsumer` | `social/consumers.py` | [social.md](./social.md) |
| `ws/feed/` | `FeedConsumer` | `social/consumers.py` | [social.md](./social.md) |
| `ws/notifications/` | `NotificationConsumer` | `notifications/consumers.py` | [notifications.md](./notifications.md) |
| `ws/polls/<poll_id>/` | `PollConsumer` | `polls/consumers.py` | [polls.md](./polls.md) |

---

## Common Patterns

### Heartbeat

All consumers support `ping` / `pong`:

```json
// Client → Server (every ~30s)
{"type": "ping"}

// Server → Client
{"type": "pong"}
```

### Channel Groups

| Group Pattern | Used By | Purpose |
|--------------|---------|---------|
| `user_{user_id}` | Chat, Feed | Per-user routing (presence, feed events, conversation_added) |
| `chat_{conversation_id}` | Chat | Per-conversation messaging & events |
| `post_{post_id}` | PostConsumer | Per-post live updates (likes, comments, reshares) |
| `notify_{user_id}` | NotificationConsumer | Per-user notification delivery |
| `poll_{poll_id}` | PollConsumer | Per-poll real-time voting |
| `trending_feed` | event_broadcaster | Global trending updates |

### Error Envelope

```json
{
  "type": "error",
  "request_id": "req-001",
  "code": "error_code_string",
  "message": "Human-readable message"
}
```
