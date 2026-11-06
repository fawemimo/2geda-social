# Polls WebSocket API

**Consumer**: `polls/consumers.py` — `PollConsumer`
**Endpoint**: `ws://<host>/ws/polls/<poll_id>/?token=<JWT_ACCESS_TOKEN>`
**Group**: `poll_{poll_id}`

The poll WebSocket is a **real-time broadcast channel**. Clients connect to receive live vote updates, poll status changes, and paid vote confirmations. Voting on free polls can be done over WebSocket or REST; paid polls always use REST + Paystack webhook.

Rate-limited: 30 actions per minute per user per poll.

---

## Connection

Connect with a valid JWT access token as a query parameter.

```
ws://localhost:8000/ws/polls/550e8400-e29b-41d4-a716-446655440000/?token=eyJ...
```

**Server response on success:**

```json
{
  "type": "connected",
  "poll_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user-uuid",
  "options": [
    { "id": "opt-uuid-1", "text": "Option A", "vote_count": 12, "position": 0 },
    { "id": "opt-uuid-2", "text": "Option B", "vote_count": 8, "position": 1 }
  ]
}
```

**Connection fails silently** (WebSocket closes) if:
- Token is missing or invalid
- Poll does not exist or is deleted

---

## Client → Server Commands

### `ping`

Keep-alive heartbeat.

```json
{ "type": "ping" }
```

**Response:**
```json
{ "type": "pong" }
```

---

### `vote` (free polls only)

Cast a vote. For paid polls, use the REST API (`POST /api/v2/polls/{id}/vote/pay/`).

**Request:**
```json
{
  "type": "vote",
  "option_id": "opt-uuid-1"
}
```

**Acknowledgment** (to the voter only):
```json
{
  "type": "vote.ack",
  "event": "vote.update",
  "poll_id": "poll-uuid",
  "option_id": "opt-uuid-1",
  "voter_id": "user-uuid",
  "options": [
    { "id": "opt-uuid-1", "text": "Option A", "vote_count": 13, "position": 0 },
    { "id": "opt-uuid-2", "text": "Option B", "vote_count": 8, "position": 1 }
  ],
  "total_votes": 21
}
```

**Broadcast** (to all viewers in the poll group — see [Outbound Events](#outbound-events-server--client)).

**Error cases:**
- `missing_option_id` — `option_id` not provided
- `already_voted` — user already voted (single-choice poll)
- `poll_closed` / `poll_expired` — poll is no longer active
- `rate_limited` — exceeded 30 actions/min

---

### `unvote` (free polls only)

Remove a vote. Pass `option_id` for multiple-choice polls; omit it to remove all votes.

**Request:**
```json
{
  "type": "unvote",
  "option_id": "opt-uuid-1"
}
```

**Acknowledgment:**
```json
{ "type": "unvote.ack" }
```

**Broadcast:** `vote.removed` event to all poll viewers.

---

## Outbound Events (Server → Client)

These events are broadcast to **all clients** connected to the poll group (`poll_{poll_id}`).

### `poll_event` — vote update

Sent when any vote is cast (via WebSocket, REST API, or paid vote webhook).

```json
{
  "type": "poll_event",
  "event": "vote.update",
  "poll_id": "poll-uuid",
  "option_id": "opt-uuid-1",
  "voter_id": "user-uuid",
  "vote_count": 3,
  "options": [
    { "id": "opt-uuid-1", "text": "Option A", "vote_count": 15, "position": 0 },
    { "id": "opt-uuid-2", "text": "Option B", "vote_count": 8, "position": 1 }
  ],
  "total_votes": 23
}
```

### `poll_event` — vote removed

```json
{
  "type": "poll_event",
  "event": "vote.removed",
  "poll_id": "poll-uuid",
  "option_id": "opt-uuid-1",
  "voter_id": "user-uuid",
  "options": [
    { "id": "opt-uuid-1", "text": "Option A", "vote_count": 14, "position": 0 },
    { "id": "opt-uuid-2", "text": "Option B", "vote_count": 8, "position": 1 }
  ],
  "total_votes": 22
}
```

### `poll_event` — poll closed

Sent when the poll author manually closes the poll via `POST /api/v2/polls/{id}/close/`.

```json
{
  "type": "poll_event",
  "event": "poll.closed",
  "poll_id": "poll-uuid"
}
```

---

## Paid Poll Voting Flow

Paid polls **cannot** use the WebSocket `vote` command. The flow is:

```
1. POST /api/v2/polls/{id}/vote/pay/
   → Returns { authorization_url, reference }

2. User completes payment on Paystack checkout page
   (no callback URL — Paystack shows success/failure on their page)

3. Paystack sends webhook → POST /api/v2/polls/webhook/payment/
   → Backend verifies payment, casts votes, broadcasts vote.update

4. Frontend polls status:
   GET /api/v2/polls/{id}/vote/status/?reference=VP-XXXX
   → Returns { reference, status, poll_id, option_id, quantity, amount, votes_cast }
```

**What the WebSocket viewer sees:** After a successful paid vote, all connected clients receive the same `vote.update` broadcast event shown above. The `vote_count` field indicates how many votes were cast in that payment.

The voter also receives a push notification: *"Your payment was successful and X vote(s) have been cast."*

### Payment status values

| Status | Meaning |
|--------|---------|
| `pending` | Payment initialized, waiting for Paystack |
| `successful` | Payment confirmed, votes cast |
| `failed` | Payment failed or was abandoned |

---

## Error Envelope

All errors follow this format:

```json
{
  "type": "error",
  "code": "error_code",
  "message": "Human-readable description"
}
```

| Code | Trigger |
|------|---------|
| `unknown_type` | Unrecognized message type |
| `missing_option_id` | `vote` sent without `option_id` |
| `rate_limited` | More than 30 actions per minute |
| `already_voted` | Duplicate vote on single-choice poll |
| `poll_closed` | Poll has been closed |
| `poll_expired` | Poll has expired |
| `option_not_found` | Invalid `option_id` |

---

## REST API Endpoints (for reference)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v2/polls/{id}/vote/` | Cast a free vote |
| `POST` | `/api/v2/polls/{id}/unvote/` | Remove a vote |
| `POST` | `/api/v2/polls/{id}/vote/pay/` | Initialize paid vote payment |
| `GET` | `/api/v2/polls/{id}/vote/status/?reference=` | Check payment status |
| `POST` | `/api/v2/polls/{id}/close/` | Close poll (author only) |
| `GET` | `/api/v2/polls/{id}/results/` | Get poll results |
| `GET` | `/api/v2/polls/{id}/analytics/` | Get poll analytics (author only) |
| `POST` | `/api/v2/polls/webhook/payment/` | Paystack webhook (no auth, signature verified) |
