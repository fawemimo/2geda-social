# Chats App WebSocket API

All chat app communication should use the single authenticated WebSocket
connection:

```text
ws://<host>/ws/chat/?token=<JWT_ACCESS_TOKEN>
```

If the token is missing, expired, or invalid, the server closes the socket.

## Connection Event

Server sends this immediately after accepting the connection:

```json
{
  "type": "connected",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "conversations": ["7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"],
  "online_users": [{"user_id": "660e8400-e29b-41d4-a716-446655440001"}]
}
```

Send a heartbeat about every 30 seconds:

```json
{"type": "ping"}
```

Server replies:

```json
{"type": "pong"}
```

## Command Response Envelope

Commands that fetch or mutate chat state return a response payload. Include a
client-generated `request_id` whenever the client needs to match a response to a
specific request.

```json
{
  "type": "response",
  "request_id": "req-001",
  "action": "list_conversations",
  "resource": "conversations",
  "message": "OK",
  "data": []
}
```

Errors use:

```json
{
  "type": "error",
  "request_id": "req-001",
  "code": "not_a_member",
  "message": "not_a_member"
}
```

## Client Commands

### List Conversations

Client sends:

```json
{
  "type": "list_conversations",
  "request_id": "req-list-1"
}
```

Server responds with `resource: "conversations"` and `data` as an array of
conversation objects.

### Create Direct Conversation

Client sends:

```json
{
  "type": "create_direct_conversation",
  "request_id": "req-direct-1",
  "recipient_id": "660e8400-e29b-41d4-a716-446655440001"
}
```

Server responds:

```json
{
  "type": "response",
  "request_id": "req-direct-1",
  "action": "create_direct_conversation",
  "resource": "conversation",
  "message": "Conversation created.",
  "data": {
    "created": true,
    "conversation": {
      "id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
      "conversation_type": "direct",
      "name": "",
      "description": "",
      "is_locked": false,
      "members": []
    }
  }
}
```

Online members also receive `conversation_added`.

### Create Group Conversation

Client sends:

```json
{
  "type": "create_group_conversation",
  "request_id": "req-group-1",
  "name": "Lagos builders",
  "description": "Planning and support",
  "member_ids": [
    "660e8400-e29b-41d4-a716-446655440001",
    "770e8400-e29b-41d4-a716-446655440002"
  ]
}
```

Server responds with `resource: "conversation"` and the created group.

### Fetch Messages

Client sends:

```json
{
  "type": "get_messages",
  "request_id": "req-history-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "before": "2026-07-05T12:00:00Z",
  "limit": 50
}
```

Server responds with `resource: "messages"` and messages in chronological order.

### Send Message

Client sends:

```json
{
  "type": "send_message",
  "request_id": "req-send-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "body": "Hey, are we still meeting today?",
  "reply_to_id": null
}
```

All connected members receive:

```json
{
  "type": "new_message",
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "sender_id": "550e8400-e29b-41d4-a716-446655440000",
  "sender_username": "alice",
  "message_type": "text",
  "body": "Hey, are we still meeting today?",
  "reply_to_id": null,
  "media_url": null,
  "is_edited": false,
  "delivery_status": "sent",
  "created_at": "2026-07-05T12:00:00+00:00",
  "is_deleted": false,
  "deleted_by_id": null
}
```

### Delete Message

Client sends:

```json
{
  "type": "delete_message",
  "request_id": "req-delete-1",
  "message_id": "880e8400-e29b-41d4-a716-446655440003"
}
```

All connected members receive:

```json
{
  "type": "message_deleted",
  "message_id": "880e8400-e29b-41d4-a716-446655440003",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "deleted_by_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Mark Read

Client sends:

```json
{
  "type": "mark_read",
  "request_id": "req-read-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

All connected members receive:

```json
{
  "type": "read_receipt",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "read_at": "2026-07-05T12:01:00+00:00"
}
```

### Typing

Client sends:

```json
{
  "type": "typing.start",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

or:

```json
{
  "type": "typing.stop",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

Members receive:

```json
{
  "type": "typing_indicator",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "status": "start"
}
```

## Group Commands

Supported command types:

```text
add_group_members
remove_group_member
toggle_group_lock
request_group_join
list_join_requests
process_join_request
promote_group_admin
```

Each group command accepts `request_id` and `conversation_id`. For member
actions, send `member_ids` or `user_id`. For join request processing, send
`join_request_id` and `action` as `approve` or `reject`.

## Search and Presence Commands

Supported command types:

```text
search_messages
search_conversations
search_users
search_media
get_presence
```

Search commands accept `q`. `search_messages` may include `conversation_id`.
`search_media` may include `media_type`. `get_presence` accepts `user_ids`.

## Call Signalling

The same socket relays WebRTC call signalling:

```text
call.offer
call.answer
call.ice_candidate
call.end
call.video_toggle
call.screen_share
```

