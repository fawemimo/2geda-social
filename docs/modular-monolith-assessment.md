# Modular Monolith: Feasibility Assessment

**Question asked:** how far can this codebase move toward a modular monolith *without changing behaviour*?

**Short answer:** most of the way, and cheaply. The hard work — a services layer, DTOs, dedicated Celery queues — is already done. What is missing is not structure but *enforcement*: nothing today stops any app from reaching into any other app's internals, and 62 import sites have taken that option.

There is exactly **one** genuine circular dependency in production code, and half of it is already solved elsewhere in the repo.

> No code was changed to produce this document. Everything below is a proposal.

---

## Contents

- [Verdict](#verdict)
- [How this was measured](#how-this-was-measured)
- [Current shape](#current-shape)
- [What already works in your favour](#what-already-works-in-your-favour)
- [The four obstacles](#the-four-obstacles)
- [Target architecture](#target-architecture)
- [Phased plan](#phased-plan)
- [Enforcing it](#enforcing-it)
- [Three defects found during the audit](#three-defects-found-during-the-audit)
- [What not to do](#what-not-to-do)

---

## Verdict

| Dimension | Rating | Why |
| --- | --- | --- |
| **Feasibility** | **High** | 7 of 8 apps already have a `services/` layer; views are thin adapters |
| **Behavioural risk** | **Low** | Phases 0–2 are mechanical; no query, endpoint, or response changes |
| **Effort to a defensible boundary** | **~3–5 days** | Phases 0–3 |
| **Effort to full enforcement** | **~2–3 weeks** | Adds the event bus and public-API modules |
| **Worth extracting to microservices after?** | **No, not yet** | Traffic and team size do not justify it; see [What not to do](#what-not-to-do) |

The realistic goal is **enforced module boundaries inside one deployable**, not preparation for a service split. That is where the value is: onboarding, blast-radius control, and the ability to reason about one app without reading four others.

---

## How this was measured

Static analysis over every non-test, non-migration `.py` file in the eight business apps:

- Parsed each file's AST to build an app→app import graph, recording whether each import is **top-level** (module load time) or **deferred** (inside a function — a common workaround for cycles).
- Extracted every `ForeignKey` / `OneToOneField` / `ManyToManyField` whose target is another app.
- Cross-referenced Celery `.delay()` call sites and `channels` group names.

Raw counts below are from that pass, not from impression.

---

## Current shape

**Size** — ~20,200 LOC across 8 business apps, plus 1,223 in `utils/` and 766 in `clients/`.

| App | LOC | App | LOC |
| --- | --- | --- | --- |
| `accounts` | 5,031 | `notifications` | 2,604 |
| `social` | 3,820 | `polls` | 1,239 |
| `tickets` | 3,107 | `displays` | 733 |
| `chats` | 2,968 | `medias` | 654 |

**Cross-app imports: 102 total — 62 top-level, 40 deferred (39%).**

That 39% is the headline number. Deferred imports are almost always a symptom: someone hit a circular-import error and moved the import inside a function to make it go away. It works, but it hides the dependency from every static tool and defers the failure to runtime.

**App → app dependencies (production code):**

```
accounts       ->  medias(3)
medias         ->  accounts(1)
notifications  ->  accounts(4)
social         ->  accounts(22), notifications(16), medias(5)
chats          ->  notifications(9), accounts(2), medias(1)
tickets        ->  accounts(5), chats(2), notifications(1), medias(1)
polls          ->  accounts(5), medias(1)
displays       ->  accounts(9), notifications(3), medias(2)
```

**Cross-app foreign keys** — the coupling that cannot be removed by moving imports around:

| Target | Referenced by |
| --- | --- |
| `accounts.User` | every app (~25 FK fields) |
| `medias.Media` | `accounts` (5 fields), `chats`, `polls`, `displays` |
| `chats.Conversation` | `tickets` (dispute chat) |

---

## What already works in your favour

Do not underestimate how much is already right. Most codebases attempting this start far behind.

1. **A services layer exists in 7 of 8 apps.** `accounts`, `social`, `chats`, `tickets`, `notifications`, `polls`, `displays` all have `services/`. Views are thin HTTP adapters that call one service method and wrap the result. That is the single most expensive precondition, and it is done. Only `medias` lacks one (654 LOC, so it is a small gap).

2. **A DTO boundary already exists.** `notifications/services/dto.py` defines `CreateNotificationDTO`, `MuteActorDTO`, `UpdatePreferenceDTO`. Callers build a DTO and hand it over — they do not construct `Notification` rows. This is the exact shape a module's public API should take.

3. **A uniform response envelope.** `utils/responses.py` means module boundaries never leak into the API contract.

4. **Celery already has per-concern queues.** `core/celery.py` routes to `otp`, `notifications`, `media`, `default`. Task routing is already thinking in modules.

5. **The correct FK pattern already appears twice.** `accounts/models.py` references `"medias.Media"` as a *string* with the comment *"set via string ref to avoid circular import"*, and `notifications/models.py` uses `settings.AUTH_USER_MODEL` throughout. The good pattern is in-repo; it just was not applied consistently.

---

## The four obstacles

### 1. One real circular dependency: `accounts ↔ medias`

This is the only production cycle in the codebase.

```
accounts/tasks.py, accounts/views.py  ──deferred──>  medias.models.Media
medias/models.py:8                    ──top-level──> accounts.models.User
```

`accounts` already avoids its half correctly via the `"medias.Media"` string ref. `medias/models.py` closes the loop with a hard `from accounts.models import User`.

**Fix:** swap that one import for `settings.AUTH_USER_MODEL`, exactly as `notifications/models.py` already does. Six apps hard-import `User` this way (`social`, `chats`, `tickets`, `polls`, `medias`, `displays`); `medias` is the only one where it creates a cycle, but converting all six is uniform and mechanical.

> Verify with `makemigrations --check --dry-run` first. Switching an FK target from `User` to `settings.AUTH_USER_MODEL` usually deconstructs identically and produces no migration, but it can emit a no-op `AlterField` plus a swappable dependency. Confirm before committing — do not assume.

### 2. The other two "cycles" are phantom

Worth stating because a naive tool will report three cycles and overstate the problem.

- **`chats ↔ notifications`** — `chats → notifications` is 9 real production imports, but every one of the 8 `notifications → chats` imports is in `notifications/tests.py`. Not a production cycle.
- **`notifications ↔ social`** — the `notifications → social` edge exists only in `notifications/services.py`, which is **dead code** (see [defects](#three-defects-found-during-the-audit)). Delete that file and the edge disappears.

So the cycle count drops from 3 to 1 with one deletion and one import change.

### 3. Notification dispatch is copy-pasted across four apps

The single most repeated cross-app pattern. `social`, `chats`, `displays`, and `tickets` all contain this identical three-import block:

```python
from notifications.services.dto import CreateNotificationDTO
from notifications.services.notification_services import NotificationService
from notifications.tasks import dispatch_notification
```

followed by hand-built DTO construction and a `.delay()`. It appears at 16 sites in `social` alone (12 of them top-level).

The coupling is deeper than the imports suggest: `CreateNotificationDTO.source_model` takes a **Django model class** (`source_model=type(obj)`), so every caller passes a live ORM class across the boundary and `notifications` resolves it through `ContentType`.

**This is the best seam in the codebase.** Feature apps should not know that notifications are a database table, a Celery task, and a WebSocket broadcast. They should announce that something happened.

### 4. `utils/enum.py` is a 36-class shared kernel

Every domain's vocabulary lives in one file: `OTPPurpose`, `PostVisibility`, `MediaType`, `ConversationType`, `PollStatus`, `EventStatus`, `TicketStatus`, `DisputeReason`, `PaymentStatus`, and 27 more. Every app imports from it, so every app transitively depends on every other app's vocabulary, and any change to the file touches all of them.

It has already caused one real problem — `NotificationType` is defined **twice** in the same file (lines 95 and 237), and the second silently shadows the first.

---

## Target architecture

A four-layer stack. Dependencies point **downward only**; same-layer imports are forbidden.

```
┌──────────────────────────────────────────────────────────────┐
│  L3  FEATURES     social   chats   polls   displays   tickets │
│                   (no imports between these)                  │
├──────────────────────────────────────────────────────────────┤
│  L2  DELIVERY     notifications                               │
│                   (fan-in only; today depends on accounts)    │
├──────────────────────────────────────────────────────────────┤
│  L1  PLATFORM     accounts (identity)    medias (assets)      │
├──────────────────────────────────────────────────────────────┤
│  L0  KERNEL       utils    clients                            │
└──────────────────────────────────────────────────────────────┘
```

The measured graph already fits this almost perfectly. Two violations:

- **`tickets → chats`** (2 sites) — an L3→L3 edge. Opening a dispute creates a `Conversation`. Either grant a documented exception, or have `chats` expose a `create_conversation(...)` entry point that `tickets` calls without importing `chats.models`.
- **`accounts → medias`** — an L1→L1 edge. Both are platform-layer; treat `medias` as sitting just below `accounts`, or accept it as a documented exception once the import cycle is broken.

Each module then exposes exactly one public module:

```
<app>/api.py     # the ONLY module other apps may import
```

Everything else — `models`, `services/`, `serializers`, `tasks` — becomes internal. This is the enforcement point, and it is what the `services/` layer already prepared you for.

---

## Phased plan

Ordered by risk. Each phase is independently shippable and behaviour-preserving.

### Phase 0 — Cleanup and baseline *(hours, zero risk)*

- Delete the shadowed dead `notifications/services.py`.
- De-duplicate `NotificationType` in `utils/enum.py`.
- Add `import-linter` to CI with the **current** graph recorded as the contract. This does not fix anything; it stops the situation getting worse while you work.

### Phase 1 — Break the cycle *(half a day, low risk)*

- `medias/models.py`: `from accounts.models import User` → `settings.AUTH_USER_MODEL`.
- Apply the same to the other five apps for consistency.
- Confirm no migration is generated (or that the generated one is a no-op).

**Result:** zero circular dependencies. No behaviour change.

### Phase 2 — Split the shared kernel *(1 day, low risk)*

Move each enum to the app that owns it (`tickets/enums.py`, `social/enums.py`, …), leaving `utils/enum.py` re-exporting everything for backward compatibility. No import site has to change on day one; new code uses the owned location.

Keep genuinely shared primitives (`ProcessingStatus`, `MediaType`) in the kernel.

### Phase 3 — Public API modules *(2 days, low risk)*

Add `<app>/api.py` per module, starting with **`notifications`** (highest fan-in: 29 inbound imports). It re-exports the handful of things outsiders legitimately need. Update callers to import from `notifications.api` instead of reaching into `notifications.services.*` and `notifications.tasks`.

Purely a re-export layer at first — no logic moves — so it cannot change behaviour.

### Phase 4 — Domain events *(1 week, medium risk)*

Replace the copy-pasted dispatch block with an event bus in `utils/events.py`:

```python
# social/services/like.py  — publisher knows nothing about notifications
events.publish(PostLiked(post_id=..., actor_id=..., recipient_id=...))

# notifications/handlers.py — subscriber owns the delivery decision
@events.on(PostLiked)
def notify_post_liked(event): ...
```

This deletes the `social → notifications`, `chats → notifications`, `displays → notifications`, and `tickets → notifications` edges outright (29 import sites), and removes the `source_model=type(obj)` model-class leak.

Do this **after** Phases 0–3 — it is the only phase that changes runtime control flow, so it needs the test coverage and the stable boundaries underneath it.

### Phase 5 — Optional, probably skip

Per-module database schemas, separate migration histories, module-level HTTP boundaries. High cost, no benefit at current scale. Revisit only if a module needs independent scaling or a separate team owns it.

---

## Enforcing it

Structure without enforcement decays — that is exactly how 62 top-level cross-app imports accumulated. Add `import-linter` (`pip install import-linter`) with a `.importlinter` contract:

```ini
[importlinter]
root_packages = accounts, social, chats, tickets, notifications, medias, polls, displays, utils, clients

[importlinter:contract:layers]
name = Module layering
type = layers
layers =
    social | chats | polls | displays | tickets
    notifications
    accounts | medias
    utils | clients

[importlinter:contract:api-only]
name = Modules are reached only through their public API
type = forbidden
source_modules = social, chats, tickets, polls, displays
forbidden_modules = notifications.models, notifications.services, notifications.tasks
```

Run it in CI. Start with the contract matching reality (Phase 0), then tighten as each phase lands. A failing build is what makes the boundary real.

---

## Three defects found during the audit

Independent of any restructuring — these are worth fixing on their own.

### 1. `notifications/services.py` is dead code, shadowed by a package

Both `notifications/services.py` (4.5 KB) and `notifications/services/` (a package) exist. Python resolves the **package**, so the file is unreachable:

```
notifications.services resolves to: notifications/services/__init__.py
```

It also contains `from social.models import Notification`, which would raise `ImportError` if it ever were reached — `social.models` has no such class. It is the sole source of the phantom `notifications → social` cycle. **Delete it.**

### 2. `NotificationType` is defined twice in `utils/enum.py`

Lines 95 and 237. The second (30 members) silently wins; the first (11 members) is unreachable.

**No live breakage today** — the three members referenced elsewhere (`KYC_APPROVED`, `KYC_REJECTED`, `REFERRAL_JOINED`) happen to exist in both. But seven members exist only in the shadowed version — `FOLLOW`, `LIKE_POST`, `LIKE_COMMENT`, `COMMENT`, `REPLY`, `RESHARE`, `MENTION` — and any new code reaching for those names will fail with `AttributeError` at runtime. A latent trap, not a current outage.

### 3. 39% of cross-app imports are deferred inside functions

40 of 102. Each one is a cycle worked around rather than resolved. They are invisible to static analysis and turn an architectural problem into a runtime one. Phase 1 removes the reason they exist.

---

## What not to do

- **Do not extract microservices.** ~25 foreign keys point at `accounts.User`. Splitting that means either a distributed join on every request or duplicating identity into every service. The operational cost is not close to justified at this size.
- **Do not split the database.** Cross-module FKs give you transactional integrity for free — including the ticket-purchase flow that depends on `select_for_update` across `PriceTier`, `TicketPurchase`, and `Ticket`. Losing that trades a solved problem for a hard one.
- **Do not do Phase 4 first.** The event bus is the appealing part, but doing it before the boundaries are enforced just adds indirection on top of the same tangle.
- **Do not rewrite `accounts`.** At 5,031 LOC it is the largest app and the most depended-upon. It is also the most structured. Leave it; enforce what points *at* it.

---

## Bottom line

The codebase is already a modular monolith in structure — services layers, DTOs, thin views, per-concern queues. What it lacks is a rule that says which module may talk to which, and a build that fails when the rule is broken.

Phases 0–3 get you there in roughly a week of mechanical, behaviour-preserving work, and the single genuine cycle is a one-line fix using a pattern already present in two of your own files.

---

*Assessment based on static analysis of `accounts`, `social`, `chats`, `tickets`, `notifications`, `medias`, `polls`, `displays`, `utils`, `clients`, and `core` as of 2026-08-14. No source files were modified.*
