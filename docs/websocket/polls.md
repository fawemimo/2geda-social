# Polls WebSocket — Commands & Payloads

**Consumer**: `polls/consumers.py` — `PollConsumer`  
**Endpoint**: `ws://<host>/ws/polls/<poll_id>/?token=<JWT_ACCESS_TOKEN>`  
**Group**: `poll_{poll_id}`  

Rate-limited: 30 votes per minute per user per poll.

---

## Connection

On successful authentication the server responds with the poll's current options and vote counts:

```json
{
  "type": "connected",
  "poll_id": "poll-uuid-1",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "options": [
    {
      "id": "opt-1",
      "text": "Option A",
      "vote_count": 0,
      "position": 0
    },
    {
      "id": "opt-2",
      "text": "Option B",
      "vote_count": 0,
      "position": 1
    }
  ]
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

Error codes: `unknown_type`, `missing_option_id`, `rate_limited`, plus service-level error codes (e.g. `poll_closed`, `already_voted`, `option_not_found`).

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

### `vote`

Cast a vote on a poll option.

**Request:**
```json
{
  "type": "vote",
  "option_id": "opt-1"
}
```

**Acknowledgment** (sent only to the voter):
```json
{
  "type": "vote.ack",
  "event": "vote.update",
  "poll_id": "poll-uuid-1",
  "option_id": "opt-1",
  "voter_id": "550e8400-e29b-41d4-a716-446655440000",
  "options": [
    { "id": "opt-1", "text": "Option A", "vote_count": 1, "position": 0 },
    { "id": "opt-2", "text": "Option B", "vote_count": 0, "position": 1 }
  ],
  "total_votes": 1
}
```

**Broadcast to all poll viewers** (`poll_event`):
```json
{
  "type": "poll_event",
  "event": "vote.update",
  "poll_id": "poll-uuid-1",
  "option_id": "opt-1",
  "voter_id": "550e8400-e29b-41d4-a716-446655440000",
  "options": [
    { "id": "opt-1", "text": "Option A", "vote_count": 1, "position": 0 },
    { "id": "opt-2", "text": "Option B", "vote_count": 0, "position": 1 }
  ],
  "total_votes": 1
}
```

---

### `unvote`

Remove a vote from a poll option (or all votes if `option_id` is omitted).

**Request:**
```json
{
  "type": "unvote",
  "option_id": "opt-1"
}
```

**Acknowledgment** (sent only to the voter):
```json
{
  "type": "unvote.ack"
}
```

**Broadcast to all poll viewers** (`poll_event`):
```json
{
  "type": "poll_event",
  "event": "vote.removed",
  "poll_id": "poll-uuid-1",
  "option_id": "opt-1",
  "voter_id": "550e8400-e29b-41d4-a716-446655440000",
  "options": [
    { "id": "opt-1", "text": "Option A", "vote_count": 0, "position": 0 },
    { "id": "opt-2", "text": "Option B", "vote_count": 0, "position": 1 }
  ],
  "total_votes": 0
}
```

---

## Outbound Events (Server → Client)

### `poll_event`

General wrapper for poll events broadcast to all connected viewers.

**Sub-events:**

| Event | Description |
|-------|-------------|
| `vote.update` | A vote was cast on an option |
| `vote.removed` | A vote was removed from an option |
| `poll.closed` | The poll was closed (auto-closed after expiry or manually) |

Example `poll.closed`:

```json
{
  "type": "poll_event",
  "event": "poll.closed",
  "poll_id": "poll-uuid-1"
}
```

---

## Rate Limiting

If the client exceeds 30 votes per minute, the server responds with:

```json
{
  "type": "error",
  "code": "rate_limited",
  "message": "Too many requests. Please slow down."
}
```
