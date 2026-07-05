# Chat WebSocket Client Flow

This is a minimal end-to-end payload flow for one client connection.

## 1. Connect

Client opens:

```text
ws://api.example.com/ws/chat/?token=<JWT_ACCESS_TOKEN>
```

Client receives:

```json
{
  "type": "connected",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "conversations": [],
  "online_users": []
}
```

## 2. Create or Open a Direct Conversation

Client sends:

```json
{
  "type": "create_direct_conversation",
  "request_id": "mobile-001",
  "recipient_id": "660e8400-e29b-41d4-a716-446655440001"
}
```

Client receives:

```json
{
  "type": "response",
  "request_id": "mobile-001",
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
      "last_message_at": null,
      "last_message_preview": "",
      "members": [],
      "last_message": null,
      "unread_count": 0
    }
  }
}
```

The recipient receives when online:

```json
{
  "type": "conversation_added",
  "created": true,
  "conversation": {
    "id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
    "conversation_type": "direct",
    "name": "",
    "description": "",
    "is_locked": false
  }
}
```

## 3. Fetch History

Client sends:

```json
{
  "type": "get_messages",
  "request_id": "mobile-002",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "limit": 50
}
```

Client receives:

```json
{
  "type": "response",
  "request_id": "mobile-002",
  "action": "get_messages",
  "resource": "messages",
  "message": "OK",
  "data": []
}
```

## 4. Send a Message

Client sends:

```json
{
  "type": "send_message",
  "request_id": "mobile-003",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "body": "Hello from the socket",
  "reply_to_id": null
}
```

Both clients receive:

```json
{
  "type": "new_message",
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "conversation_id": "7d2d7f84-c0df-42e2-a278-31f4dfdc19ef",
  "sender_id": "550e8400-e29b-41d4-a716-446655440000",
  "sender_username": "alice",
  "message_type": "text",
  "body": "Hello from the socket",
  "reply_to_id": null,
  "media_url": null,
  "is_edited": false,
  "delivery_status": "sent",
  "created_at": "2026-07-05T12:00:00+00:00",
  "is_deleted": false,
  "deleted_by_id": null
}
```

## 5. Keep Presence Fresh

Client sends periodically:

```json
{"type": "ping"}
```

Client receives:

```json
{"type": "pong"}
```

