# Mobile Client Integration Guide — Chat, Presence & Calls

## Overview

The chat system uses a **WebSocket** for real-time messaging, presence, and WebRTC call
signalling, plus a **REST API** for fetching history and managing conversations.

| Transport | Purpose | Endpoint |
|-----------|---------|----------|
| **WebSocket** (WSS) | Real-time messaging, typing, presence, call signalling | `wss://host/ws/chat/?token=<JWT>` |
| **REST** (HTTPS) | Conversation list, messages, presence query | `https://host/api/v2/chats/` |

---

## 1. Connection & Authentication

### 1.1 Obtain a JWT

Call the login endpoint and store the **access** and **refresh** tokens.

```
POST /api/v2/accounts/auth/login/
{ "email": "smithEze@example.com", "password": "secret123" }
```

Response:

```json
{
  "status": true,
  "data": {
    "access": "eyJhbGciOiJIUzI1NiIs...",
    "refresh": "eyJhbGciOiJIUzI1NiIs...",
    "access_expires_at": 1717531200,
    "refresh_expires_at": 1720123200
  }
}
```

### 1.2 Open the WebSocket

Pass the **access** token as a query parameter:

```
wss://host/ws/chat/?token=eyJhbGciOiJIUzI1NiIs...
```

The server replies with a `connected` event:

```json
{
  "type": "connected",
  "user_id": "0fb7a3a4-...",
  "conversations": ["conv-uuid-1", "conv-uuid-2"],
  "online_users": [
    { "user_id": "peer-uuid-1" }
  ]
}
```

The `online_users` array contains every currently-online member of your
conversations — use it to initialise the presence indicators in your UI.

### 1.3 Token Refresh

Access tokens expire (default: 15 minutes). When the WebSocket closes with a
401 or you receive an error, refresh the token and reconnect:

```
POST /api/v2/accounts/auth/token/refresh/
{ "refresh": "eyJhbGciOiJIUzI1NiIs..." }
```

### 1.4 Reconnection Strategy

| Scenario | Action |
|----------|--------|
| Network drop | Auto-reconnect with exponential backoff (1s, 2s, 4s … max 30s) |
| Token expired (401 close) | Refresh token, reconnect |
| App foreground | Reconnect immediately |
| App background | Keep connection; server heartbeat will detect timeout |

On every reconnect the server sends a fresh `connected` event with the
current list of online users — no manual synchronisation is needed.

---

## 2. Messaging

### 2.1 Send a message

```json
// Client → Server
{
  "type": "send_message",
  "conversation_id": "conv-uuid-1",
  "body": "Hey, are you free for a call?",
  "reply_to_id": null
}
```

The server broadcasts to all participants:

```json
// Server → all members of chat_conv-uuid-1
{
  "type": "new_message",
  "id": "msg-uuid-abc123",
  "conversation_id": "conv-uuid-1",
  "sender_id": "0fb7a3a4-...",
  "sender_username": "smithEze",
  "message_type": "text",
  "body": "Hey, are you free for a call?",
  "created_at": "2026-06-04T14:30:00+00:00"
}
```

> **Client implementation note:** Append the new message to the local cache
> when you receive `new_message`. Optimistically insert it on send so the
> UI feels instant, then reconcile with the server event.

### 2.2 Mark as read

```json
// Client → Server
{ "type": "mark_read", "conversation_id": "conv-uuid-1" }
```

```json
// Server → all members
{
  "type": "read_receipt",
  "conversation_id": "conv-uuid-1",
  "user_id": "0fb7a3a4-...",
  "read_at": "2026-06-04T14:31:00+00:00"
}
```

The local client should update the unread counter of the conversation to 0
and show the last-read watermark in the UI.

### 2.3 Fetch message history

```
GET /api/v2/chats/conversations/<uuid>/messages/?before=<ISO-timestamp>
Authorization: Bearer <JWT>
```

The `before` parameter implements cursor-based pagination. Pass the
`created_at` of the oldest displayed message to get the next page.

---

## 3. Typing Indicators

```json
// Client → Server
{ "type": "typing.start", "conversation_id": "conv-uuid-1" }
{ "type": "typing.stop",  "conversation_id": "conv-uuid-1" }
```

```json
// Server → all members
{
  "type": "typing_indicator",
  "conversation_id": "conv-uuid-1",
  "user_id": "0fb7a3a4-...",
  "username": "smithEze",
  "status": "start"
}
```

**Client implementation:**

- Send `typing.start` once when the user begins typing.
- Send `typing.stop` when the message is sent OR after 3 seconds of
  inactivity (use a debounce timer).
- Show a "typing…" indicator when you receive `typing_indicator` with
  `status: "start"`. Clear it after 5 seconds or on `status: "stop"`.

---

## 4. Presence (Online / Offline)

Presence is **automatic** — you don't need to send any client messages.
The server tracks online status through the WebSocket connection.

| Event | When | Payload |
|-------|------|---------|
| `presence.online` | User connects | `{ "type": "presence.online", "user_id": "...", "username": "smithEze" }` |
| `presence.offline` | User disconnects | `{ "type": "presence.offline", "user_id": "...", "username": "smithEze" }` |
| `connected.online_users` | You connect | Array of currently-online peer IDs |

### REST presence query

```
GET /api/v2/chats/presence/?user_ids=uuid1,uuid2
Authorization: Bearer <JWT>
```

Response:
```json
{
  "status": true,
  "data": {
    "online_users": [{ "user_id": "uuid1" }]
  }
}
```

### Conversation member serialization

The `ConversationMemberSerializer` includes an `is_online` boolean, so the
conversation list REST response already marks which members are online.

**Client implementation:**

1. On `presence.online` / `presence.offline` → update the green dot in the
   conversation list and the chat header.
2. On reconnect → consume the `connected.online_users` array to re-sync all
   indicators.
3. Use the REST presence endpoint for bulk checks (e.g. when displaying a
   "who's online" screen).

---

## 5. Heartbeat

The client should send a `ping` every **30 seconds** to keep the connection
alive and refresh the server-side presence TTL.

```json
// Client → Server (every 30s)
{ "type": "ping" }

// Server → Client
{ "type": "pong" }
```

If no `ping` is received for ~5 minutes, the server considers the user
offline and broadcasts `presence.offline`.

---

## 6. Audio Call (WebRTC)

### 6.1 Call initiation flow

```
┌─────────┐                  ┌───────────┐                  ┌─────────┐
│  Caller  │                  │  Server   │                  │  Callee │
└────┬────┘                  └─────┬─────┘                  └────┬────┘
     │  call.offer (audio)         │                            │
     │ ──────────────────────────> │  call_offer                │
     │                             │ ──────────────────────────> │
     │                             │                            │
     │  ICE candidates             │  call.answer (audio)       │
     │ <══════════════════════════ │ <────────────────────────── │
     │  bidirectional              │                            │
     │                             │                            │
     │  call.end                   │  call_ended                │
     │ ──────────────────────────> │ ──────────────────────────> │
```

### 6.2 Step-by-step walkthrough for mobile

**Step 1 — Create peer connection (caller)**

```dart
// Flutter example
final pc = await createPeerConnection(config);
pc.onIceCandidate = (candidate) {
  ws.send(jsonEncode({
    'type': 'call.ice_candidate',
    'peer_id': calleeId,
    'candidate': candidate.toMap(),
  }));
};
```

**Step 2 — Create and send offer**

```dart
final offer = await pc.createOffer();
await pc.setLocalDescription(offer);
ws.send(jsonEncode({
  'type': 'call.offer',
  'peer_id': calleeId,
  'conversation_id': conversationId,
  'call_type': 'audio',
  'sdp': offer.sdp,
}));
```

**Step 3 — Callee receives offer**

```dart
// In WS message handler:
if (msg['type'] == 'call_offer') {
  final pc = await createPeerConnection(config);
  await pc.setRemoteDescription(
    RTCSessionDescription(msg['sdp'], 'offer'),
  );
  final answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  ws.send(jsonEncode({
    'type': 'call.answer',
    'peer_id': msg['caller_id'],
    'call_type': msg['call_type'],
    'sdp': answer.sdp,
  }));
}
```

**Step 4 — Caller sets remote description**

```dart
if (msg['type'] == 'call_answer') {
  await pc.setRemoteDescription(
    RTCSessionDescription(msg['sdp'], 'answer'),
  );
}
```

**Step 5 — ICE exchange**

Both sides handle `call_ice_candidate` by adding the candidate to the
peer connection:

```dart
if (msg['type'] == 'call_ice_candidate') {
  await pc.addIceCandidate(
    RTCIceCandidate(msg['candidate']['candidate'],
                    msg['candidate']['sdpMid'],
                    msg['candidate']['sdpMLineIndex']),
  );
}
```

**Step 6 — End the call**

```dart
ws.send(jsonEncode({
  'type': 'call.end',
  'peer_id': peerId,
  'reason': 'user_hangup',
}));
pc.close();
```

---

## 7. Video Call

The video call flow is **identical** to audio, except:

- `call_type` is set to `"video"` instead of `"audio"`.
- The SDP created by `createOffer()` / `createAnswer()` includes a video
  media line (`m=video …`).
- The mobile client requests camera permission and attaches a local video
  track before creating the offer.

```dart
final stream = await navigator.mediaDevices.getUserMedia({
  'audio': true,
  'video': true,
});
for (final track in stream.getVideoTracks()) {
  pc.addTrack(track, stream);
}
// … then createOffer() as above
```

---

## 8. Mid-Call Controls

### 8.1 Toggle video

```json
// Client → Server
{
  "type": "call.video_toggle",
  "peer_id": "peer-uuid-bob",
  "enabled": true
}
```

```json
// Server → Peer
{
  "type": "video_toggle",
  "user_id": "0fb7a3a4-...",
  "enabled": true
}
```

**Client implementation:**

```dart
// Sender
ws.send(jsonEncode({
  'type': 'call.video_toggle',
  'peer_id': peerId,
  'enabled': cameraIsOn,
}));
// Then locally enable/disable the video track:
for (final sender in pc.getSenders()) {
  if (sender.track?.kind == 'video') {
    await sender.track.setEnabled(cameraIsOn);
  }
}

// Receiver: show/hide the remote video renderer
if (msg['type'] == 'video_toggle') {
  setState(() => remoteVideoEnabled = msg['enabled']);
}
```

### 8.2 Screen share

```json
// Client → Server
{
  "type": "call.screen_share",
  "peer_id": "peer-uuid-bob",
  "sdp": "v=0\n…",
  "sharing": true
}
```

**Client implementation:**

```dart
// Start sharing
final screenStream = await navigator.mediaDevices.getDisplayMedia();
for (final track in screenStream.getVideoTracks()) {
  await pc.addTrack(track, screenStream);
}
// Create a new offer with the screen track and send it via screen_share

// Receiving: when screen_share arrives, set the remote SDP
if (msg['type'] == 'screen_share') {
  await pc.setRemoteDescription(
    RTCSessionDescription(msg['sdp'], 'offer'),
  );
  final answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  // Send answer via call.answer
}
```

### 8.3 Missed / busy calls

```json
// Timeout on callee side — caller sends:
{ "type": "call.end", "peer_id": "bob", "reason": "no_answer" }

// Busy — callee automatically rejects:
{ "type": "call.end", "peer_id": "smithEze", "reason": "busy" }
```

---

## 9. Incoming Call UX (Mobile)

When a `call_offer` arrives while the app is in the foreground:

1. Play a ringtone and show a full-screen incoming call UI.
2. On "accept" → create `RTCPeerConnection`, set remote description,
   create answer, send `call.answer`.
3. On "decline" → send `call.end` with reason `"declined"`.

If the app is in the **background**, the platform push notification layer
should trigger a **CallKit** (iOS) or **ConnectionService** (Android) UI
that displays the incoming call natively.

---

## 10. Error Handling

| Server response | Meaning | Client action |
|-----------------|---------|---------------|
| `{ "type": "error", "code": "not_a_member" }` | You tried to act on a conversation you don't belong to | Refresh conversation list |
| `{ "type": "error", "code": "missing_conversation_id" }` | Required field missing | Fix payload |
| `{ "type": "error", "code": "missing_call_params" }` | Call offer/answer missing peer/conv/sdp | Fix payload |
| `{ "type": "error", "code": "call_not_allowed" }` | You and the peer are not in the same conversation | Validate before offer |
| `{ "type": "error", "code": "unknown_type" }` | Unknown message type | Upgrade client or fix typo |

---

## 11. Full Sequence Diagram (Video Call)

```
Mobile A                  Server                   Mobile B
   │                         │                         │
   │  ── wss connect ──────> │                         │
   │  <── connected ──────── │                         │
   │                         │                         │
   │  ── ping ─────────────> │                         │
   │  <── pong ───────────── │                         │
   │                         │                         │
   │  ── call.offer(video) ─> │                         │
   │                         │ ── call_offer ─────────> │
   │                         │                         │
   │  <── call_answer ────── │ <── call.answer ──────── │
   │                         │                         │
   │  <══ ICE candidates ═══ │ ══ ICE candidates ════> │
   │  ─═ ICE candidates ═══> │ ══ ICE candidates ════> │
   │                         │                         │
   │     ◄───── WebRTC P2P audio/video ──────────►     │
   │                         │                         │
   │  ── call.video_toggle ─> │                         │
   │    (camera off)          │ ── video_toggle ───────> │
   │                         │    (enabled: false)      │
   │                         │                         │
   │  ── call.end ──────────> │                         │
   │                         │ ── call_ended ─────────> │
   │  <── (close PC)         │    (reason: user_hangup) │
```

---

## 12. Implementation Checklist

- [ ] JWT login and token refresh
- [ ] WebSocket connect with token in query string
- [ ] Handle `connected` event (store conversations, init online users)
- [ ] Handle `new_message` (append to local store)
- [ ] Handle `read_receipt` (update unread counts)
- [ ] Handle `typing_indicator` (show/hide typing bubble)
- [ ] Handle `presence.online` / `presence.offline` (update green dot)
- [ ] Heartbeat: send `ping` every 30s
- [ ] Reconnection with exponential backoff
- [ ] Create `RTCPeerConnection` on offer
- [ ] `call.offer` / `call.answer` / `call.ice_candidate` relay
- [ ] `call.end` with appropriate reason
- [ ] `call_type: "audio"` vs `"video"`
- [ ] `call.video_toggle` to mute/unmute camera mid-call
- [ ] `call.screen_share` for screen sharing
- [ ] Incoming call UI (foreground + CallKit/ConnectionService)
- [ ] REST endpoints: conversations, messages, presence
