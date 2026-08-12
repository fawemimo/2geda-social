# Tickets API

Complete reference for every endpoint exposed by `tickets/views.py`.

All routes are mounted under **`/api/v2/tickets/`** (see `core/urls.py`).

---

## Executive summary

The Tickets module turns 2geda from a social network into a **marketplace**. It lets a vetted seller publish an event, sell tickets to it, get paid, and settle complaints — end to end, without leaving the platform.

**How the business makes money.** Every ticket sale flows through Paystack. The platform records a `PaymentTransaction` per sale, applies a per-seller `commission_rate`, and settles the remainder to the seller through a `Payout`. Revenue is therefore a direct function of gross ticket volume, and every naira is traceable to an event, a buyer, and a payment reference.

**Trust model.** Three gates protect the marketplace:

1. **Seller vetting** — nobody sells until an admin approves their application. Sellers submit business details plus ID/selfie images, and an admin approves or rejects with a reason. A seller can be suspended at any time, which immediately blocks new event creation.
2. **Money never moves on client say-so** — the platform confirms every payment directly with Paystack (server-to-server), and independently via a signed webhook. A malicious client cannot mint itself a ticket.
3. **Disputes are first-class** — a buyer can open a dispute against a sold ticket. Doing so automatically creates a private group chat containing the buyer, the seller, and (once assigned) a staff moderator. Resolution is admin-only and logged.

**Inventory integrity.** Overselling is the classic failure mode for ticketing. This module defends against it with a Redis lock per event plus a database row lock on the price tier, and it holds inventory in a **15-minute reservation** while the buyer completes payment. Unpaid reservations are swept back into inventory by a Celery job every 5 minutes, so abandoned checkouts do not permanently consume stock.

**What stakeholders should know about current state.** The happy path — apply, approve, create, publish, sell, verify, report, dispute — is fully implemented and wired to live Paystack. There are, however, several gaps that should be closed before a public launch; they are catalogued honestly in [Known gaps](#known-gaps-and-risks) at the end of this document. The two that matter most commercially are that **event categories are writable by anonymous users**, and that **the public ticket-verification endpoint discloses the buyer's username**.

---

## Contents

- [Roles](#roles)
- [Response envelope](#response-envelope)
- [The core flow](#the-core-flow)
- [Endpoint reference](#endpoint-reference)
  - [Categories](#1-categories)
  - [Seller onboarding](#2-seller-onboarding)
  - [Events](#3-events)
  - [Buying tickets](#4-buying-tickets)
  - [Ticket verification at the gate](#5-ticket-verification-at-the-gate)
  - [Disputes](#6-disputes)
  - [Reports and money](#7-reports-and-money)
  - [Paystack webhook](#8-paystack-webhook)
- [Enumerations](#enumerations)
- [Error codes](#error-codes)
- [Known gaps and risks](#known-gaps-and-risks)

---

## Roles

| Role | How it is determined | Can do |
| --- | --- | --- |
| **Anonymous** | No token | Browse public events, look up an event by link, read price tiers, verify a ticket code |
| **Buyer** | Any authenticated user | Everything anonymous can, plus buy tickets, list own tickets, open disputes |
| **Seller** | Authenticated user with an **approved** `SellerProfile` | Create/publish/cancel own events, read own reports, transactions, payouts |
| **Admin** | `user.is_staff` | Approve/reject sellers, assign moderators, resolve disputes, read any event report |

Authenticate with a bearer token:

```http
Authorization: Bearer <access_token>
```

---

## Response envelope

Every JSON response uses the project-wide envelope from `utils/responses.py`.

**Success**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": { }
}
```

**Error**

```json
{
  "status": false,
  "message": "Not enough tickets available for the requested quantity.",
  "data": {},
  "code": "insufficient_tickets"
}
```

`code` is present only when the failure came from a typed service exception. `data` is never `null` — it is coerced to `{}`.

**Paginated** (used by `GET /events/public/`)

```json
{
  "status": true,
  "message": "Items fetched successfully.",
  "currentPage": 1,
  "nextPage": 2,
  "previousPage": null,
  "totalPages": 5,
  "totalItem": 87,
  "totalPerPage": 20,
  "data": [ ]
}
```

Page size defaults to 20, override with `?page_size=` up to 200.

Two endpoints break the envelope deliberately and stream **raw CSV** instead: the two report downloads.

---

## The core flow

### A. Seller onboarding

```
POST /sellers/apply/          → status: pending
        ↓  (admin reviews)
POST /admin/sellers/{id}/review/  {"action": "approve"}
        ↓
   status: approved  →  seller may now create events
```

A rejection carries a `rejection_reason`. A re-application overwrites the previous submission and resets status to `pending`. `SellerService.require_approved()` is the single gate — it raises `seller_not_approved` (403) or `seller_suspended` (403).

### B. Event lifecycle

```
draft ──publish──> published ──cancel──> cancelled
  │                    │
  │                    └──(time passes)──> completed
  └── editable                              (set by system)
```

Events are **only editable while in `draft`**. `EventService.update()` raises `invalid_event_status` otherwise. Publishing and cancelling both verify ownership.

An event is created with either a **flat** price (one implicit `general` tier) or **categorized** tiers (VIP, gold, …). `tickets_available` is computed as the sum of tier quantities.

### C. Purchase — the money path

This is the most important flow in the module. It is deliberately two-phase.

```
 BUYER                    2GEDA API                     PAYSTACK
   │                          │                             │
   │ POST /buy/initialize/    │                             │
   ├─────────────────────────>│                             │
   │                          │ 1. Redis lock on event      │
   │                          │ 2. SELECT FOR UPDATE tier   │
   │                          │ 3. check availability       │
   │                          │ 4. create TicketPurchase    │
   │                          │    (reserved_until = +15m)  │
   │                          │ 5. quantity_reserved += n   │
   │                          │ 6. create n RESERVED tickets│
   │                          │                             │
   │                          │  initialize transaction     │
   │                          ├────────────────────────────>│
   │                          │<────── authorization_url ───┤
   │<─── authorization_url ───┤                             │
   │                                                        │
   │ ─────────── buyer pays on Paystack ───────────────────>│
   │                                                        │
   │                          │<═══ webhook charge.success ═┤   (authoritative)
   │ POST /buy/verify/        │                             │
   ├─────────────────────────>│  verify transaction         │
   │                          ├────────────────────────────>│
   │                          │<──────── status: success ───┤
   │                          │ 7. purchase → successful    │
   │                          │ 8. tickets → SOLD + QR      │
   │                          │ 9. reserved -= n, sold += n │
   │                          │10. event totals updated     │
   │<──── tickets + QR ───────┤                             │
```

**Why two phases.** Reserving before payment prevents two buyers paying for the same last seat. Confirming only after a server-to-server check with Paystack prevents a client from forging a successful payment.

**Both `/buy/verify/` and the webhook call the same `TicketService.verify_purchase()`**, which is idempotent: a purchase already marked successful returns `{"status": "already_confirmed"}` without double-counting inventory. Whichever arrives first wins; the other is a no-op.

**Failure paths release inventory.** If Paystack reports anything other than success, or the amount paid is less than the amount owed, `_release_reservation()` marks the purchase failed, cancels the tickets, and returns the reserved quantity to the tier.

**Abandoned checkouts.** If the buyer simply walks away, nothing above fires. The Celery beat job `tickets.tasks.release_expired_reservations` runs every 5 minutes, finds purchases still `pending` past `reserved_until`, and releases them.

### D. Dispute lifecycle

```
open ──assign_moderator──> under_review ──resolve──> resolved_buyer
                                                   / resolved_seller
                                                   / closed
```

Opening a dispute creates a `Conversation` (group chat) containing buyer and seller, and broadcasts a WebSocket event. Assigning a moderator adds them to that chat as an admin and pushes a `dispute_assigned` event to their personal channel. Re-opening the same ticket returns the existing unresolved dispute rather than creating a duplicate.

---

## Endpoint reference

### 1. Categories

#### `GET /api/v2/tickets/categories/`

Lists active, non-deleted categories ordered by name. **Public.**

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": [
    {
      "id": "8f14e45f-ceea-467a-9f2c-3d1a5c9b7e01",
      "name": "Concerts",
      "description": "Live music events",
      "is_active": true,
      "created_at": "2026-01-12T09:00:00Z",
      "updated_at": "2026-01-12T09:00:00Z"
    }
  ]
}
```

#### `POST` / `PUT` / `PATCH` / `DELETE /api/v2/tickets/categories/{id}/`

Full CRUD via `ModelViewSet`.

> ⚠️ **These are currently `AllowAny`** — an unauthenticated caller can create, rename, or delete categories. See [Known gaps](#known-gaps-and-risks).

---

### 2. Seller onboarding

#### `POST /api/v2/tickets/sellers/apply/`

Submit or resubmit a seller application. **Auth required.**

**Request**

```json
{
  "business_name": "Lagos Live Events",
  "business_email": "hello@lagoslive.ng",
  "business_phone": "+2348012345678",
  "business_address": "12 Admiralty Way, Lekki, Lagos"
}
```

**Response `201`**

```json
{
  "status": true,
  "message": "Seller application submitted successfully.",
  "data": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "user": "9b2c1d4e-1111-4a2b-9c3d-5e6f7a8b9c0d",
    "user_email": "ada@example.com",
    "user_username": "ada",
    "business_name": "Lagos Live Events",
    "business_email": "hello@lagoslive.ng",
    "business_phone": "+2348012345678",
    "business_address": "12 Admiralty Way, Lekki, Lagos",
    "status": "pending",
    "commission_rate": "0.00",
    "total_events_created": 0,
    "total_revenue": "0.00",
    "created_at": "2026-08-10T10:15:00Z",
    "updated_at": "2026-08-10T10:15:00Z"
  }
}
```

Re-applying overwrites the existing profile and resets `status` to `pending`.

#### `GET /api/v2/tickets/sellers/me/`

Fetch the caller's seller profile. **Auth required.**

**Response `404`** when the user has never applied:

```json
{ "status": false, "message": "Seller profile not found.", "data": {} }
```

#### `PATCH /api/v2/tickets/sellers/me/`

Update editable business fields. `status`, `commission_rate`, and the revenue totals are read-only.

**Request**

```json
{ "business_phone": "+2349098765432" }
```

**Response `200`** — `{"message": "Profile updated.", "data": { ...full profile... }}`

#### `POST /api/v2/tickets/admin/sellers/{pk}/review/`

Approve or reject an application. **Admin only** (`IsAdminUser`).

**Request — approve**

```json
{ "action": "approve" }
```

**Request — reject**

```json
{ "action": "reject", "rejection_reason": "ID document was unreadable." }
```

**Response `200`**

```json
{
  "status": true,
  "message": "Seller approved successfully.",
  "data": { "id": "3fa85f64-...", "status": "approved", "...": "..." }
}
```

---

### 3. Events

Permissions are dynamic (`EventViewSet.get_permissions`): `list`, `retrieve`, `public`, `by_link`, and `price_tiers` are **public**; everything else requires authentication.

> **Important listing behaviour.** `get_queryset()` returns *the caller's own events* when the caller is an authenticated seller, and *all published events* otherwise. A logged-in seller therefore sees only their own catalogue on `GET /events/` and **cannot retrieve another seller's event by ID** through this route — they get a 404. Anonymous browsing and `/events/public/` are the discovery paths.

#### `GET /api/v2/tickets/events/`

List events (see the caveat above). Uses the compact `EventListSerializer`.

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": [
    {
      "id": "c1a2b3d4-0000-4111-8222-333344445555",
      "title": "Afrobeats Night 2026",
      "seller_name": "Lagos Live Events",
      "category_name": "Concerts",
      "platform_name": "2geda",
      "starts_at": "2026-09-20T19:00:00Z",
      "visibility": "public",
      "pricing_mode": "categorized",
      "event_link": "fIgEzRwTG4oWCc541RRgdw",
      "is_verified": true,
      "status": "published",
      "total_tickets_sold": 128,
      "tickets_available": 372,
      "cover_image": "https://cdn.2geda.net/events/afrobeats.jpg"
    }
  ]
}
```

#### `POST /api/v2/tickets/events/`

Create an event. **Requires an approved seller** — returns `403` with `seller_not_approved` or `seller_suspended` otherwise. The event starts in `draft`.

**Request — categorized pricing**

```json
{
  "title": "Afrobeats Night 2026",
  "description": "An all-night live set.",
  "category": "8f14e45f-ceea-467a-9f2c-3d1a5c9b7e01",
  "platform_name": "2geda",
  "location": "Eko Hotel, Victoria Island, Lagos",
  "starts_at": "2026-09-20T19:00:00Z",
  "ends_at": "2026-09-21T02:00:00Z",
  "visibility": "public",
  "fee_bearer": "buyer",
  "pricing_mode": "categorized",
  "price_tiers": [
    { "price_tag": "regular", "price": "10000.00", "quantity": 400 },
    { "price_tag": "vip",     "price": "35000.00", "quantity": 100 }
  ]
}
```

**Response `201`**

```json
{
  "status": true,
  "message": "Event created.",
  "data": {
    "id": "c1a2b3d4-0000-4111-8222-333344445555",
    "seller": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "seller_name": "Lagos Live Events",
    "title": "Afrobeats Night 2026",
    "status": "draft",
    "event_link": "fIgEzRwTG4oWCc541RRgdw",
    "pricing_mode": "categorized",
    "tickets_available": 500,
    "tickets_reserved": 0,
    "total_tickets_sold": 0,
    "total_revenue": "0.00",
    "is_verified": false,
    "created_at": "2026-08-10T10:30:00Z",
    "updated_at": "2026-08-10T10:30:00Z"
  }
}
```

For `pricing_mode: "flat"`, omit `price_tiers` and pass `price` and `quantity`; a single `general` tier is created automatically.

#### `GET /api/v2/tickets/events/{id}/`

Retrieve one event, full `EventSerializer` shape.

#### `PUT` / `PATCH /api/v2/tickets/events/{id}/`

Update an event. **Owner only** (403 otherwise) and **draft only** — a published event returns:

```json
{
  "status": false,
  "message": "Can only edit events in draft status.",
  "data": {},
  "code": "invalid_event_status"
}
```

Supplying `price_tiers` **replaces all existing tiers** (the old ones are deleted) and recomputes `tickets_available`.

#### `DELETE /api/v2/tickets/events/{id}/`

Soft-delete. **Owner only.** Returns `{"message": "Event deleted."}`.

#### `POST /api/v2/tickets/events/{id}/publish/`

Move `draft → published`. **Owner only.** Fails with `invalid_event_status` if already published or cancelled.

**Response `200`** — `{"message": "Event published.", "data": { ..., "status": "published" }}`

#### `POST /api/v2/tickets/events/{id}/cancel/`

Move `published → cancelled`. **Owner only.** Only published events can be cancelled.

#### `GET /api/v2/tickets/events/public/`

Discovery feed. **Public and paginated.** Returns only events that are `published`, `visibility: public`, non-deleted, and **starting in the future**.

`GET /api/v2/tickets/events/public/?page=2&page_size=50`

Returns the paginated envelope shown earlier.

#### `GET /api/v2/tickets/events/by_link/?link={slug}`

Resolve a shareable event link. **Public.** Unlike `/public/`, this finds an event regardless of status or visibility — it is the "someone sent me this link" path.

**Response `400`** when `link` is missing: `{"message": "link query parameter is required."}`
**Response `404`** when unknown: `{"message": "Event not found."}`

#### `GET /api/v2/tickets/events/{id}/price_tiers/`

List active tiers for an event. **Public.** This is what a checkout screen calls to render buying options.

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": [
    {
      "id": "aa11bb22-cc33-4dd4-8ee5-ff6600112233",
      "event": "c1a2b3d4-0000-4111-8222-333344445555",
      "price_tag": "regular",
      "price": "10000.00",
      "quantity": 400,
      "quantity_sold": 128,
      "quantity_reserved": 6,
      "available": 266,
      "is_active": true
    }
  ]
}
```

`available` = `quantity − quantity_sold − quantity_reserved`. **Always drive the UI from `available`**, not `quantity`.

---

### 4. Buying tickets

#### `POST /api/v2/tickets/buy/initialize/`

Reserve tickets and get a Paystack checkout URL. **Auth required.** The event must be `published`.

**Request**

```json
{
  "event_id": "c1a2b3d4-0000-4111-8222-333344445555",
  "price_tier_id": "aa11bb22-cc33-4dd4-8ee5-ff6600112233",
  "quantity": 2
}
```

`quantity` is bounded to 1–100.

**Response `201`**

```json
{
  "status": true,
  "message": "Purchase initialized. Redirect to Paystack.",
  "data": {
    "purchase_id": "77aa88bb-99cc-4dd0-8e11-f22233344455",
    "transaction_ref": "REF-2041548BCAC14A048BF1",
    "authorization_url": "https://checkout.paystack.com/0peioxfhpn",
    "access_code": "0peioxfhpn",
    "total_amount": 20000.0
  }
}
```

Redirect the buyer to `authorization_url`. The reservation is held for **15 minutes**.

**Errors**

| Status | `code` | When |
| --- | --- | --- |
| `400` | `insufficient_tickets` | Fewer than `quantity` available, **or** another purchase for this event is mid-flight (Redis lock held) |
| `400` | `pricing_mismatch` | `price_tier_id` does not belong to the event, or is inactive |
| `404` | — | Event not found or not published |

> Note: a contended lock and a genuinely sold-out tier both surface as `insufficient_tickets`. Clients should offer a retry, not just "sold out".

#### `POST /api/v2/tickets/buy/verify/`

Confirm payment and issue tickets. **Currently `AllowAny`** — see [Known gaps](#known-gaps-and-risks).

**Request**

```json
{ "reference": "REF-2041548BCAC14A048BF1" }
```

**Response `200` — first confirmation**

```json
{
  "status": true,
  "message": "Purchase verified successfully.",
  "data": {
    "status": "confirmed",
    "purchase_id": "77aa88bb-99cc-4dd0-8e11-f22233344455",
    "tickets": [
      {
        "id": "d1e2f3a4-5566-4778-899a-bbccddeeff00",
        "ticket_code": "TKT-SVVJD3",
        "qr_code_data": "{\"ticket_code\": \"TKT-SVVJD3\", \"event_id\": \"c1a2b3d4-...\", \"event_title\": \"Afrobeats Night 2026\", \"buyer_name\": \"ada\"}"
      }
    ]
  }
}
```

**Response `200` — replay / already processed by webhook**

```json
{
  "status": true,
  "message": "Purchase verified successfully.",
  "data": { "status": "already_confirmed", "purchase_id": "77aa88bb-...", "tickets": [ ] }
}
```

Clients should treat `confirmed` and `already_confirmed` identically.

**Error `400` — `payment_verification_failed`**, with `message` one of:

- `Purchase record not found.`
- `Paystack payment was not successful.` — reservation is released
- `Payment amount mismatch.` — underpayment; reservation is released

#### `GET /api/v2/tickets/buy/my-tickets/`

The caller's **sold** tickets, newest purchase first. **Auth required.** Reserved and cancelled tickets are excluded.

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": [
    {
      "id": "d1e2f3a4-5566-4778-899a-bbccddeeff00",
      "event": "c1a2b3d4-0000-4111-8222-333344445555",
      "event_title": "Afrobeats Night 2026",
      "buyer": "9b2c1d4e-1111-4a2b-9c3d-5e6f7a8b9c0d",
      "buyer_username": "ada",
      "price_tier": "aa11bb22-cc33-4dd4-8ee5-ff6600112233",
      "ticket_code": "TKT-SVVJD3",
      "qr_code_data": "{\"ticket_code\": \"TKT-SVVJD3\", \"...\": \"...\"}",
      "status": "sold",
      "price_paid": "10000.00",
      "fees_paid": "0.00",
      "is_verified": false,
      "purchased_at": "2026-08-10T11:02:31Z",
      "created_at": "2026-08-10T10:58:12Z"
    }
  ]
}
```

---

### 5. Ticket verification at the gate

#### `GET /api/v2/tickets/tickets/verify/{code}/`

Look up a ticket by its code — the endpoint a door scanner calls. **Public.**

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": {
    "ticket_code": "TKT-SVVJD3",
    "status": "sold",
    "event_title": "Afrobeats Night 2026",
    "event_date": "2026-09-20T19:00:00+00:00",
    "buyer_username": "ada",
    "is_verified": false,
    "price_paid": "10000.00",
    "purchased_at": "2026-08-10T11:02:31Z"
  }
}
```

**Response `404`** — `{"message": "Ticket not found."}`

> ⚠️ This endpoint is unauthenticated and returns `buyer_username`. It is also **read-only** — it does not flip `is_verified`, so it cannot by itself prevent the same ticket being admitted twice. See [Known gaps](#known-gaps-and-risks).

---

### 6. Disputes

#### `GET /api/v2/tickets/disputes/`

List disputes, scoped by role: **admins** see all, **sellers** see disputes against their events, **buyers** see their own.

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": [
    {
      "id": "ee11ff22-3344-4556-8778-99aabbccddee",
      "ticket": "d1e2f3a4-5566-4778-899a-bbccddeeff00",
      "ticket_code": "TKT-SVVJD3",
      "buyer": "9b2c1d4e-1111-4a2b-9c3d-5e6f7a8b9c0d",
      "buyer_username": "ada",
      "seller_name": "Lagos Live Events",
      "event": "c1a2b3d4-0000-4111-8222-333344445555",
      "event_title": "Afrobeats Night 2026",
      "reason": "event_cancelled",
      "description": "The event was called off and I was not refunded.",
      "status": "open",
      "assigned_moderator": null,
      "moderator_username": null,
      "resolution_notes": "",
      "resolved_at": null,
      "conversation_id": "1a2b3c4d-5e6f-4071-8293-a4b5c6d7e8f9",
      "created_at": "2026-08-11T08:00:00Z",
      "updated_at": "2026-08-11T08:00:00Z"
    }
  ]
}
```

Use `conversation_id` to open the dispute chat over the WebSocket API (see `docs/chat-websocket-api.md`).

#### `POST /api/v2/tickets/disputes/`

Open a dispute. **Auth required.** The ticket must belong to the caller and be `sold`.

**Request**

```json
{
  "ticket_id": "d1e2f3a4-5566-4778-899a-bbccddeeff00",
  "reason": "event_cancelled",
  "description": "The event was called off and I was not refunded."
}
```

`reason` ∈ `ticket_not_delivered`, `event_cancelled`, `wrong_description`, `refund_request`, `other`.

**Response `201`** — the dispute object above, plus a freshly created group conversation containing buyer and seller.

Opening a second dispute on the same ticket returns the **existing** unresolved one (still `201`).

**Response `404`** if the ticket is not the caller's, or is not `sold`.

#### `POST /api/v2/tickets/disputes/{id}/assign_moderator/`

Assign the calling admin as moderator; sets status to `under_review` and adds them to the dispute chat. **Admin only.**

Body: none required.

**Response `200`** — `{"message": "Moderator assigned.", "data": { ..., "status": "under_review" }}`
**Response `403`** — `{"message": "Only admins can assign moderators."}`
**Response `409`** — `dispute_already_resolved`

#### `POST /api/v2/tickets/disputes/{id}/resolve/`

Close out a dispute. **Admin only.**

**Request**

```json
{
  "resolution": "resolved_buyer",
  "notes": "Refund issued via Paystack on 2026-08-12."
}
```

`resolution` ∈ `resolved_buyer`, `resolved_seller`, `closed`.

**Response `200`** — `{"message": "Dispute resolved.", "data": { ..., "status": "resolved_buyer", "resolved_at": "..." }}`
**Response `409`** — `dispute_already_resolved`

---

### 7. Reports and money

#### `GET /api/v2/tickets/events/{pk}/report/`

Sales report for one event. **Owner or admin.**

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": {
    "event_title": "Afrobeats Night 2026",
    "event_status": "published",
    "total_tickets": 500,
    "total_sold": 128,
    "total_refunded": 3,
    "total_cancelled": 11,
    "total_revenue": 1280000.0,
    "total_fees": 0.0,
    "tier_breakdown": [
      { "price_tag": "regular", "price": "10000.00", "quantity": 400, "sold_count": 100, "refunded_count": 2 },
      { "price_tag": "vip",     "price": "35000.00", "quantity": 100, "sold_count": 28,  "refunded_count": 1 }
    ]
  }
}
```

**Response `403`** — `{"message": "You do not have access to this report."}`

#### `GET /api/v2/tickets/events/{pk}/report/download/`

Same data as CSV. **Owner or admin.** Returns `text/csv`, not the JSON envelope.

```http
Content-Type: text/csv
Content-Disposition: attachment; filename="event_c1a2b3d4-0000-4111-8222-333344445555_report.csv"
```

```csv
Ticket Code,Buyer,Buyer Email,Price Tier,Price Paid,Fees Paid,Status,Purchased At
TKT-SVVJD3,ada,ada@example.com,regular,10000.00,0.00,sold,2026-08-10T11:02:31+00:00
```

> This export contains buyer email addresses — treat it as personal data.

#### `GET /api/v2/tickets/reports/seller/`

Aggregate report across all of the caller's events. **Auth required**, returns `404` if the caller has no seller profile.

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": {
    "business_name": "Lagos Live Events",
    "seller_status": "approved",
    "events": { "total": 12, "published": 7, "completed": 4, "cancelled": 1 },
    "financials": {
      "gross_revenue": 4820000.0,
      "total_fees": 241000.0,
      "total_refunds": 60000.0,
      "net_revenue": 4519000.0
    }
  }
}
```

`net_revenue = gross_revenue − total_fees − total_refunds`.

#### `GET /api/v2/tickets/sellers/me/report/download/`

Full transaction ledger as CSV. **Auth required.**

```csv
Reference,Type,Event,Amount,Fees,Status,Buyer,Notes,Created At
REF-2041548BCAC14A048BF1,purchase,Afrobeats Night 2026,20000.00,1000.00,successful,ada,,2026-08-10T11:02:31+00:00
```

#### `GET /api/v2/tickets/sellers/me/transactions/`

Payment transactions for the caller's seller profile, newest first. Returns `{"data": []}` — **not** a 404 — when the caller has no seller profile.

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": [
    {
      "id": "b0c1d2e3-4455-4667-8889-aabbccddeeff",
      "seller": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "event": "c1a2b3d4-0000-4111-8222-333344445555",
      "event_title": "Afrobeats Night 2026",
      "buyer": "9b2c1d4e-1111-4a2b-9c3d-5e6f7a8b9c0d",
      "buyer_username": "ada",
      "transaction_type": "purchase",
      "amount": "20000.00",
      "fees": "1000.00",
      "currency": "NGN",
      "reference": "REF-2041548BCAC14A048BF1",
      "status": "successful",
      "notes": "",
      "created_at": "2026-08-10T11:02:31Z"
    }
  ]
}
```

#### `GET /api/v2/tickets/sellers/me/payouts/`

Payout records for the caller, newest first. Also returns `[]` when there is no seller profile.

**Response `200`**

```json
{
  "status": true,
  "message": "Request completed successfully.",
  "data": [
    {
      "id": "c3d4e5f6-7788-499a-8bbc-ddeeff001122",
      "seller": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "event": "c1a2b3d4-0000-4111-8222-333344445555",
      "event_title": "Afrobeats Night 2026",
      "amount": "1219000.00",
      "fees_deducted": "61000.00",
      "currency": "NGN",
      "status": "pending",
      "payout_ref": "PO-C3FF5E50E99F50EE",
      "paid_at": null,
      "created_at": "2026-08-13T09:00:00Z"
    }
  ]
}
```

---

### 8. Paystack webhook

#### `POST /api/v2/tickets/webhook/paystack/`

Server-to-server callback from Paystack. **Public route, but signature-protected.**

Every request must carry an `x-paystack-signature` header — an HMAC-SHA512 of the raw body keyed with `PAYSTACK_SECRET_KEY`. Verification uses a constant-time compare.

**Request headers**

```http
x-paystack-signature: 7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069
Content-Type: application/json
```

**Request body**

```json
{
  "event": "charge.success",
  "data": {
    "reference": "REF-2041548BCAC14A048BF1",
    "amount": 2000000,
    "status": "success",
    "metadata": {
      "purchase_id": "77aa88bb-99cc-4dd0-8e11-f22233344455",
      "event_id": "c1a2b3d4-0000-4111-8222-333344445555",
      "buyer_id": "9b2c1d4e-1111-4a2b-9c3d-5e6f7a8b9c0d",
      "quantity": 2
    }
  }
}
```

Handled events:

| `event` | Effect |
| --- | --- |
| `charge.success` | Runs `TicketService.verify_purchase(reference)` — issues tickets |
| `charge.failed` | Releases the reservation and cancels the tickets |
| `refund.processed` | Records a `refund` `PaymentTransaction` |
| anything else | Logged and ignored |

**Response `200`** — `{"status": true, "message": "Webhook received.", "data": {}}`
**Response `401`** — `{"status": false, "message": "Invalid signature."}`

> The handler catches and logs **any** processing exception, then still returns `200`. That guarantees Paystack will not retry — including when processing genuinely failed. See [Known gaps](#known-gaps-and-risks).

---

## Enumerations

| Enum | Values |
| --- | --- |
| `EventStatus` | `draft`, `published`, `cancelled`, `completed` |
| `EventVisibility` | `public`, (others per `utils/enum.py`) |
| `PricingMode` | `flat`, `categorized` |
| `PriceTag` | `general`, `vip`, `regular`, `gold` |
| `SellerStatus` | `not_submitted`, `pending`, `under_review`, `approved`, `rejected`, `suspended` |
| `TicketStatus` | `reserved`, `sold`, `refunded`, `cancelled` |
| `PaymentStatus` | `pending`, `successful`, `failed`, `refunded`, `partially_refunded` |
| `TransactionType` | `purchase`, `refund`, `fee`, `payout` |
| `DisputeReason` | `ticket_not_delivered`, `event_cancelled`, `wrong_description`, `refund_request`, `other` |
| `DisputeStatus` | `open`, `under_review`, `resolved_buyer`, `resolved_seller`, `closed` |

---

## Error codes

Typed service errors from `tickets/services/exceptions.py` — these arrive with a `code` field.

| `code` | HTTP | Meaning |
| --- | --- | --- |
| `seller_not_approved` | 403 | Caller has no seller profile, or it is not approved |
| `seller_suspended` | 403 | Seller account suspended |
| `insufficient_tickets` | 400 | Not enough inventory, or the event purchase lock is held |
| `invalid_event_status` | 400 | Action not allowed from the event's current status |
| `pricing_mismatch` | 400 | Price tier does not belong to the event |
| `payment_verification_failed` | 400 | Paystack rejected, or amounts did not match |
| `duplicate_transaction` | 400 | Transaction already processed |
| `dispute_already_resolved` | 409 | Dispute is already resolved or closed |
| `event_link_expired` | 400 | Event link no longer valid |

Untyped failures (`SellerApplyView`, `EventViewSet.create`, `DisputeViewSet.create`) catch broad `Exception` and return `400` with the raw exception string in `message` and **no** `code`. Clients should not parse those strings.

---

## Known gaps and risks

Documented honestly so they can be prioritised. None of these block the happy path; several should be closed before a public launch.

### Security

1. **`EventCategoryViewSet` is fully `AllowAny`.** Anonymous callers can `POST`, `PUT`, `PATCH`, and `DELETE` categories at `/categories/`. This is almost certainly unintended — reads should stay public, writes should be `IsAdminUser`.

2. **`/buy/verify/` is `AllowAny` and takes only a reference.** Anyone who learns a transaction reference can trigger verification for it. The blast radius is limited because the endpoint re-checks with Paystack and is idempotent, so it cannot mint tickets for an unpaid reference — but it does let a third party enumerate references and learn ticket codes and QR payloads from the response.

3. **`/tickets/verify/{code}/` is public and returns `buyer_username`.** A gate-scanning endpoint discloses who owns a ticket to anyone who can guess or observe a code.

4. **Event report CSV contains buyer email addresses.** Access is correctly gated to owner-or-admin, but the export should be treated as personal data for retention and transfer purposes.

### Correctness

5. **The webhook always returns `200`, even when handling failed.** `paystack_webhook` wraps `handle_webhook` in a bare `except`, logs, and returns success. Paystack therefore never retries a failed delivery, so a transient database error silently loses a paid order. The fix is to return a `5xx` on unexpected failure so Paystack retries.

6. **The webhook's duplicate guard never fires.** `_handle_charge_success` skips processing if a `PaymentTransaction` already exists for the reference — but `TicketService.verify_purchase()` never creates one. The check is dead code. Idempotency currently rests entirely on the `already_confirmed` short-circuit inside `verify_purchase`, which does hold.

7. **No `PaymentTransaction` is written on a successful purchase.** Because of the above, the seller transactions endpoint, the seller aggregate report, and `process_payout` all read from a ledger that the purchase flow does not populate. Seller-facing financials will read zero until this is wired up. **This is the most commercially significant gap in the module.**

8. **Multi-tier purchases mis-account.** `verify_purchase` and `_release_reservation` both use `tickets.first().price_tier_id` for the whole purchase. A single purchase only ever spans one tier today, so this is currently correct — but it will silently corrupt inventory counts if basket-style multi-tier purchases are ever added.

9. **`quantity_reserved` can drift negative.** The decrements use `F("quantity_reserved") - quantity` with no floor. The `PositiveIntegerField` will raise at the database level if a double-release ever occurs.

### Design

10. **A logged-in seller cannot browse other sellers' events** through `GET /events/` or `GET /events/{id}/`, because `get_queryset()` narrows to their own catalogue as soon as they have a seller profile. Clients must use `/events/public/` or `/events/by_link/` for discovery. This surprises integrators.

11. **`insufficient_tickets` is overloaded.** It means both "sold out" and "another purchase is in flight for this event" (Redis lock contention). Clients cannot distinguish a permanent from a transient failure, so they cannot decide between "sold out" and "please retry".

12. **The event purchase lock is coarse.** `lock:purchase:event:{event.id}` serialises *all* purchases for an event, not per tier. Under heavy load on a popular event this is a throughput ceiling, and losers get an error rather than queueing.

13. **`EventViewSet.perform_create` is a no-op `pass`.** `create()` is fully overridden so it is never reached — dead code that will mislead the next reader.

---

*Generated from `tickets/views.py`, `tickets/urls.py`, `tickets/serializers.py`, and `tickets/services/` as of 2026-08-10.*
