# Chat WebSocket — Commands & Payloads

**Consumer**: `chats/consumers.py` — `DirectChatConsumer`  
**Endpoint**: `ws://<host>/ws/chat/?token=<JWT_ACCESS_TOKEN>`  
**Channel groups**: `user_{user_id}`, `chat_{conversation_id}`  

---

## Connection

On successful authentication the server responds:

```json
{
  "type": "connected",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "conversations": ["7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"],
  "online_users": [{"user_id": "660e8400-e29b-41d4-a716-446655440001"}]
}
```

**Response envelope** for command replies:

```json
{
  "type": "response",
  "request_id": "req-001",
  "action": "list_conversations",
  "resource": "conversations",
  "message": "OK",
  "data": { ... }
}
```

**Error envelope:**

```json
{
  "type": "error",
  "request_id": "req-001",
  "code": "not_a_member",
  "message": "not_a_member"
}
```

Error codes: `unknown_type`, `missing_conversation_id`, `missing_message_id`, `missing_user_id`, `missing_recipient_id`, `missing_group_name`, `missing_call_params`, `missing_join_request_id`, `not_a_member`, `not_allowed`, `member_not_found`, `recipient_not_found`, `invalid_recipient_id`, `invalid_member_ids`, `invalid_group`, `invalid_group_members`, `invalid_promotion`, `invalid_user_ids`, `conversation_not_found`, `message_not_found`, `join_request_not_found`, `group_locked`, `call_not_allowed`.

---

## Heartbeat

### `ping`

Keep the connection alive. Send every 30s.

**Request:**
```json
{"type": "ping"}
```

**Response:**
```json
{"type": "pong"}
```

---

## Conversation Management

### `list_conversations`

List all conversations the authenticated user is a member of.

**Request:**
```json
{
  "type": "list_conversations",
  "request_id": "req-list-1"
}
```

**Response** (`resource`: `conversations`):
```json
{
  "type": "response",
  "request_id": "req-list-1",
  "action": "list_conversations",
  "resource": "conversations",
  "message": "OK",
  "data": [
    {
      "id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
      "conversation_type": "direct",
      "name": "",
      "description": "",
      "is_locked": false,
      "members": [...]
    }
  ]
}
```

---

### `create_direct_conversation`

Create or retrieve a 1-on-1 conversation with another user.

**Request:**
```json
{
  "type": "create_direct_conversation",
  "request_id": "req-direct-1",
  "recipient_id": "660e8400-e29b-41d4-a716-446655440001"
}
```

**Response** (`resource`: `conversation`):
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

**Broadcast to recipient** (`conversation_added`):
```json
{
  "type": "conversation_added",
  "conversation": { ... },
  "created": true
}
```

---

### `create_group_conversation`

Create a group conversation with multiple members.

**Request:**
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

**Response** (`resource`: `conversation`):
```json
{
  "type": "response",
  "request_id": "req-group-1",
  "action": "create_group_conversation",
  "resource": "conversation",
  "message": "Group conversation created.",
  "data": { "id": "...", "conversation_type": "group", "name": "Lagos builders", ... }
}
```

**Broadcast to members** (`conversation_added`):
```json
{
  "type": "conversation_added",
  "conversation": { ... },
  "created": true
}
```

---

### `conversation.join`

Join a conversation group on the channel layer (listen for its events).

**Request:**
```json
{
  "type": "conversation.join",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

**Response** (`resource`: `conversation`):
```json
{
  "type": "response",
  "action": "conversation.join",
  "resource": "conversation",
  "message": "OK",
  "data": { "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef" }
}
```

---

## Messaging

### `get_messages`

Fetch message history for a conversation (paginated by `before` cursor).

**Request:**
```json
{
  "type": "get_messages",
  "request_id": "req-history-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "before": "2026-07-05T12:00:00Z",
  "limit": 50
}
```

**Response** (`resource`: `messages`):
```json
{
  "type": "response",
  "request_id": "req-history-1",
  "action": "get_messages",
  "resource": "messages",
  "message": "OK",
  "data": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440003",
      "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
      "sender_id": "550e8400-e29b-41d4-a716-446655440000",
      "body": "Hello!",
      "message_type": "text",
      "created_at": "2026-07-05T12:00:00+00:00",
      ...
    }
  ]
}
```

---

### `send_message`

Send a text message to a conversation.

**Request:**
```json
{
  "type": "send_message",
  "request_id": "req-send-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "body": "Hey, are we still meeting today?",
  "reply_to_id": null
}
```

**Broadcast to all conversation members** (`new_message`):
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

---

### `delete_message`

Soft-delete a message (only the sender can delete).

**Request:**
```json
{
  "type": "delete_message",
  "request_id": "req-delete-1",
  "message_id": "880e8400-e29b-41d4-a716-446655440003"
}
```

**Broadcast to all conversation members** (`message_deleted`):
```json
{
  "type": "message_deleted",
  "message_id": "880e8400-e29b-41d4-a716-446655440003",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "deleted_by_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### `mark_read`

Mark all messages in a conversation as read.

**Request:**
```json
{
  "type": "mark_read",
  "request_id": "req-read-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

**Broadcast to all conversation members** (`read_receipt`):
```json
{
  "type": "read_receipt",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "read_at": "2026-07-05T12:01:00+00:00"
}
```

---

## Typing Indicators

### `typing.start` / `typing.stop`

Notify other members that the user is typing.

**Request:**
```json
{
  "type": "typing.start",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

```json
{
  "type": "typing.stop",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

**Broadcast to all conversation members** (`typing_indicator`):
```json
{
  "type": "typing_indicator",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "status": "start"
}
```

---

## Group Management

### `add_group_members`

Add new members to a group conversation (admin only).

**Request:**
```json
{
  "type": "add_group_members",
  "request_id": "req-add-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "member_ids": ["990e8400-e29b-41d4-a716-446655440004"]
}
```

**Broadcast** (`group_members_updated`):
```json
{
  "type": "group_members_updated",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "action": "added",
  "member_ids": ["990e8400-e29b-41d4-a716-446655440004"]
}
```

**To new members** (`conversation_added`):
```json
{
  "type": "conversation_added",
  "conversation": { ... },
  "created": false
}
```

**Response** (`resource`: `conversation`):
```json
{
  "type": "response",
  "request_id": "req-add-1",
  "action": "add_group_members",
  "resource": "conversation",
  "message": "Members added successfully.",
  "data": { ... }
}
```

---

### `remove_group_member`

Remove a member from a group conversation (admin only).

**Request:**
```json
{
  "type": "remove_group_member",
  "request_id": "req-remove-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "user_id": "990e8400-e29b-41d4-a716-446655440004"
}
```

**Response** (`resource`: `conversation`):
```json
{
  "type": "response",
  "request_id": "req-remove-1",
  "action": "remove_group_member",
  "resource": "conversation",
  "message": "Member removed successfully.",
  "data": { ... }
}
```

**Broadcast** (`member_removed`):
```json
{
  "type": "member_removed",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "user_id": "990e8400-e29b-41d4-a716-446655440004",
  "removed_by_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### `toggle_group_lock`

Lock/unlock a group (only admins can send messages when locked).

**Request:**
```json
{
  "type": "toggle_group_lock",
  "request_id": "req-lock-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

**Response** (`resource`: `conversation`):
```json
{
  "type": "response",
  "request_id": "req-lock-1",
  "action": "toggle_group_lock",
  "resource": "conversation",
  "message": "OK",
  "data": {
    "id": "...",
    "is_locked": true,
    ...
  }
}
```

**Broadcast** (`group_locked` / `group_unlocked`):
```json
{
  "type": "group_locked",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "is_locked": true,
  "locked_by_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### `request_group_join`

Request to join a locked group.

**Request:**
```json
{
  "type": "request_group_join",
  "request_id": "req-join-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

**Response** (`resource`: `join_request`):
```json
{
  "type": "response",
  "request_id": "req-join-1",
  "action": "request_group_join",
  "resource": "join_request",
  "message": "Join request submitted.",
  "data": { "id": "...", "status": "pending", ... }
}
```

**Broadcast to group admins** (`join_request_created`):
```json
{
  "type": "join_request_created",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "join_request_id": "...",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice"
}
```

---

### `list_join_requests`

List pending join requests (admin only).

**Request:**
```json
{
  "type": "list_join_requests",
  "request_id": "req-list-jr-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

**Response** (`resource`: `join_requests`):
```json
{
  "type": "response",
  "request_id": "req-list-jr-1",
  "action": "list_join_requests",
  "resource": "join_requests",
  "message": "OK",
  "data": [
    { "id": "...", "user_id": "...", "username": "bob", "status": "pending", ... }
  ]
}
```

---

### `process_join_request`

Approve or reject a pending join request (admin only).

**Request:**
```json
{
  "type": "process_join_request",
  "request_id": "req-process-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "join_request_id": "jr-uuid",
  "action": "approve"
}
```

**Response** (`resource`: `join_request`):
```json
{
  "type": "response",
  "request_id": "req-process-1",
  "action": "process_join_request",
  "resource": "join_request",
  "message": "OK",
  "data": { "id": "...", "status": "approved", "conversation": { ... } }
}
```

**Broadcast** (`join_request_approved` / `join_request_rejected`):
```json
{
  "type": "join_request_approved",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "join_request_id": "jr-uuid",
  "user_id": "990e8400-e29b-41d4-a716-446655440004",
  "processed_by_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### `promote_group_admin`

Promote a member to admin (admin only).

**Request:**
```json
{
  "type": "promote_group_admin",
  "request_id": "req-promote-1",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "user_id": "990e8400-e29b-41d4-a716-446655440004"
}
```

**Response** (`resource`: `member`):
```json
{
  "type": "response",
  "request_id": "req-promote-1",
  "action": "promote_group_admin",
  "resource": "member",
  "message": "Member promoted to admin.",
  "data": { "user_id": "...", "role": "admin" }
}
```

**Broadcast** (`member_promoted`):
```json
{
  "type": "member_promoted",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "user_id": "990e8400-e29b-41d4-a716-446655440004",
  "new_role": "admin",
  "promoted_by_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## Search & Presence

### `search_messages`

Search through messages the user has access to.

**Request:**
```json
{
  "type": "search_messages",
  "request_id": "req-search-msg-1",
  "q": "meeting",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef"
}
```

**Response** (`resource`: `messages`):
```json
{
  "type": "response",
  "request_id": "req-search-msg-1",
  "action": "search_messages",
  "resource": "messages",
  "message": "OK",
  "data": [ ... ]
}
```

---

### `search_conversations`

Search conversations by name or participant.

**Request:**
```json
{
  "type": "search_conversations",
  "request_id": "req-search-conv-1",
  "q": "lagos"
}
```

**Response** (`resource`: `conversations`):
```json
{
  "type": "response",
  "request_id": "req-search-conv-1",
  "action": "search_conversations",
  "resource": "conversations",
  "message": "OK",
  "data": [ ... ]
}
```

---

### `search_users`

Search for users by username, email, or display name.

**Request:**
```json
{
  "type": "search_users",
  "request_id": "req-search-user-1",
  "q": "alice"
}
```

**Response** (`resource`: `users`):
```json
{
  "type": "response",
  "request_id": "req-search-user-1",
  "action": "search_users",
  "resource": "users",
  "message": "OK",
  "data": [ { "id": "...", "username": "alice", "display_name": "Alice", ... } ]
}
```

---

### `search_media`

Search shared media in conversations.

**Request:**
```json
{
  "type": "search_media",
  "request_id": "req-search-media-1",
  "q": "photo",
  "media_type": "image"
}
```

**Response** (`resource`: `media`):
```json
{
  "type": "response",
  "request_id": "req-search-media-1",
  "action": "search_media",
  "resource": "media",
  "message": "OK",
  "data": [ ... ]
}
```

---

### `get_presence`

Check online status of specific users.

**Request:**
```json
{
  "type": "get_presence",
  "request_id": "req-presence-1",
  "user_ids": ["660e8400-e29b-41d4-a716-446655440001"]
}
```

**Response** (`resource`: `presence`):
```json
{
  "type": "response",
  "request_id": "req-presence-1",
  "action": "get_presence",
  "resource": "presence",
  "message": "OK",
  "data": { "online_users": [{"user_id": "660e8400-e29b-41d4-a716-446655440001"}] }
}
```

---

## Presence Broadcasts

Broadcast automatically when users connect/disconnect.

**`presence.online`**:
```json
{
  "type": "presence.online",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice"
}
```

**`presence.offline`**:
```json
{
  "type": "presence.offline",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice"
}
```

---

## WebRTC Call Signalling

### `call.offer`

Initiate a call (audio or video) to a peer in a shared conversation.

**Request:**
```json
{
  "type": "call.offer",
  "peer_id": "660e8400-e29b-41d4-a716-446655440001",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "call_type": "audio",
  "sdp": "v=0\r\no=-..."
}
```

**Relayed to peer** (`call_offer`):
```json
{
  "type": "call_offer",
  "caller_id": "550e8400-e29b-41d4-a716-446655440000",
  "caller_username": "alice",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "call_type": "audio",
  "sdp": "v=0\r\no=-..."
}
```

---

### `call.answer`

Answer an incoming call.

**Request:**
```json
{
  "type": "call.answer",
  "peer_id": "550e8400-e29b-41d4-a716-446655440000",
  "sdp": "v=0\r\no=-..."
}
```

**Relayed to caller** (`call_answer`):
```json
{
  "type": "call_answer",
  "callee_id": "660e8400-e29b-41d4-a716-446655440001",
  "sdp": "v=0\r\no=-..."
}
```

---

### `call.ice_candidate`

Exchange ICE candidates during call setup.

**Request:**
```json
{
  "type": "call.ice_candidate",
  "peer_id": "660e8400-e29b-41d4-a716-446655440001",
  "candidate": "candidate:1..."
}
```

**Relayed to peer** (`call_ice_candidate`):
```json
{
  "type": "call_ice_candidate",
  "from_id": "550e8400-e29b-41d4-a716-446655440000",
  "candidate": "candidate:1..."
}
```

---

### `call.end`

End an active call.

**Request:**
```json
{
  "type": "call.end",
  "peer_id": "660e8400-e29b-41d4-a716-446655440001",
  "reason": "user_hangup"
}
```

**Relayed to peer** (`call_ended`):
```json
{
  "type": "call_ended",
  "ended_by": "550e8400-e29b-41d4-a716-446655440000",
  "reason": "user_hangup"
}
```

---

### `call.video_toggle`

Toggle video on/off during a call.

**Request:**
```json
{
  "type": "call.video_toggle",
  "peer_id": "660e8400-e29b-41d4-a716-446655440001",
  "enabled": true
}
```

**Relayed to peer** (`video_toggle`):
```json
{
  "type": "video_toggle",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "enabled": true
}
```

---

### `call.screen_share`

Start or stop screen sharing.

**Request:**
```json
{
  "type": "call.screen_share",
  "peer_id": "660e8400-e29b-41d4-a716-446655440001",
  "sdp": "v=0\r\no=-...",
  "sharing": true
}
```

**Relayed to peer** (`screen_share`):
```json
{
  "type": "screen_share",
  "from_id": "550e8400-e29b-41d4-a716-446655440000",
  "sdp": "v=0\r\no=-...",
  "sharing": true
}
```
