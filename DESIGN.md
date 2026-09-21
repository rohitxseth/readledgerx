# ReadLedger — Low-Level Design

This document covers the key design decisions in ReadLedger's backend, the reasoning
behind each one, and — where it matters — what the decision costs and when I would
reverse it.

---

## Architecture Overview

```
Routers → Services → Repositories → Database
             ↑              ↑
         Interfaces     Interfaces
         (Protocols)   (Protocols)
```

Every layer talks to the layer below it through an interface, not a concrete class.
Services don't know what database you're using. Repositories don't know what business
logic runs on top of them.

The through-line for most of what follows: **push decisions to the boundary, keep the
middle pure.** Validation happens at construction, I/O happens behind interfaces, and
the business logic in between is ordinary Python that runs in milliseconds under test.

---

## 1. Protocol-Based Dependency Injection

**Files:** `app/interfaces/repository_interfaces.py`, `app/interfaces/client_interfaces.py`

Python's `typing.Protocol` lets you define structural interfaces — a class satisfies a
Protocol just by having the right method signatures, with no inheritance required.

```python
# Before: service was tightly coupled to concrete classes
class BookService:
    def __init__(self, conn: AsyncConnection):
        self.repo = BookRepository(conn)         # concrete — can't swap for tests
        self.google_client = GoogleBooksClient() # concrete — hits real HTTP

# After: service depends on abstractions
class BookService:
    def __init__(
        self,
        repo: IBookRepository,
        search_client: IBookSearchClient,
        intelligence: BookIntelligenceService,
    ):
        ...
```

### Why Protocol and not ABC?

Both give you dependency inversion. The difference is **which direction the import
arrow points**, and that turns out to matter.

With an ABC, a fake has to inherit from the abstraction, so the test module must import
from production code:

```python
from app.interfaces.repository_interfaces import IBookRepository  # test → production

class FakeBookRepository(IBookRepository):   # inheritance couples them
    ...
```

With a Protocol, the fake declares nothing and imports nothing:

```python
class FakeBookRepository:                    # no import, no base class
    async def get_by_id(self, book_id): ...
    async def get_by_title(self, title): ...
```

`tests/conftest.py` is written this way on purpose — it defines three fake repositories
and a fake search client, and **none of them import the interfaces they satisfy**. The
conformance is checked by the type checker statically, and by the fact that the service
under test actually calls the methods.

That yields three concrete properties:

1. Services depend on abstractions, not on a database driver — **DIP**
2. Swapping an implementation (in-memory for tests, OpenLibrary for Google Books)
   requires zero changes to service code — **OCP**
3. Unit tests need no database, no network, and no mocking framework — **testability**

The whole `backend/tests` suite runs in about two seconds with no I/O of any kind. That
is the payoff, and it is the reason to prefer the structural interface.

**The honest caveat:** `@runtime_checkable` makes `isinstance(x, IBookRepository)` work,
but it only verifies that *method names* exist — it does not check signatures, argument
types, or return types. A fake with the right names and wrong arguments passes
`isinstance` and fails at call time. Static checking is what actually enforces the
contract here; the runtime check is a convenience, not a guarantee. It is worth knowing
that before leaning on it.

**When I would use an ABC instead:** when there is real shared behaviour to inherit, not
just a contract to satisfy. Protocols give you a shape; ABCs give you a shape plus an
implementation. Nothing in this codebase needed the second one.

---

## 2. Domain Mappers

**Files:** `app/domain/mappers.py`

Mappers are pure static classes responsible for one thing: converting a raw DB row (or
API response) into a domain model.

```python
class UserMapper:
    @staticmethod
    def from_db(row: dict) -> User:
        return User(
            id=row["id"],
            email=row["email"],
            created_at=row["created_at"],
            hashed_password=row["password_hash"],
        )
```

The key benefit: if a DB column is renamed, you change the mapper — nothing else. The
domain model doesn't know about DB column names, and the repository doesn't know how to
construct domain objects.

That last line is the pattern doing real work: the database column is `password_hash`,
the domain field is `hashed_password`, and the mapper is where that translation lives. The same applies to
`reading_sessions`, where the columns are `pages` and `read_on` but the domain speaks in
`pages_read` and `session_date`.

---

## 3. Value Objects

**Files:** `app/domain/value_objects.py`

Value objects enforce domain invariants at construction time. They fail fast, at the
boundary, rather than letting invalid data propagate silently through the system.

```python
PageCount(-1)     # raises ValueError immediately
Email("notvalid") # raises ValueError immediately
```

`PageCount` is used in `ReadingRepository.create_session()` to validate pages before any
DB call is made. `Email` is validated in the registration endpoint before we even check
whether the user exists.

The rule being encoded: **the database's CHECK constraints are a backstop, not the
validation layer.** A `CHECK (pages >= 0)` violation surfaces as an `IntegrityError`
somewhere deep in a driver, with no useful message for the caller. `PageCount(-1)` fails
at the point the bad value entered the system, with a message that names the problem.
Both exist; they are defending different things.

---

## 4. Strategy Pattern for Password Hashing

**Files:** `app/services/password_hasher.py`, `app/services/auth_service.py`

```python
class IPasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, plain: str, hashed: str) -> bool: ...

class BcryptPasswordHasher:   # default — good general-purpose choice
    ...

class Argon2PasswordHasher:   # memory-hard — stronger against GPU brute-forcing
    ...
```

`AuthService` doesn't know which algorithm it uses — it just calls `self._hasher.hash()`.
Switching from bcrypt to Argon2 is a one-line change in `dependencies.py`.

**Caveat worth stating:** swapping the hasher only affects *new* hashes. Existing bcrypt
hashes in the database stay bcrypt, and a real migration means verifying against the old
algorithm and transparently re-hashing on successful login. The Strategy pattern makes
the swap possible; it does not make it free.

---

## 5. Event Bus

**Files:** `app/events/event_bus.py`, `app/events/user_events.py`, `app/events/handlers.py`

The event bus decouples side-effects from core flows. When a user registers, the
registration handler publishes a `UserRegisteredEvent`. Anything that needs to react —
audit logging, welcome emails, analytics — subscribes independently.

```python
# Registration flow: no knowledge of what happens next
await event_bus.publish(UserRegisteredEvent(user_id=..., email=...))

# Independently, handlers react
async def on_user_registered(event: UserRegisteredEvent):
    await _write_audit_log("user_registered", event.user_id, ...)
```

Events are frozen dataclasses — immutable and typed. Handlers are registered at startup
in `main.py`. Adding a new side-effect means adding one function and one `subscribe()`
call; the registration router never changes.

### What this implementation is not

Being precise about the limits matters more than the pattern itself:

- **It is in-process.** Nothing survives a restart, and there is no retry. A handler that
  fails has failed permanently.
- **`publish()` is sequential and awaited**, so a slow handler adds latency directly to
  the user's request. It looks asynchronous; it is not decoupled in time.
- **Handler exceptions are swallowed and logged.** That keeps a failing audit write from
  breaking registration, which is the right call for audit — but it means a handler can
  fail silently forever, and nothing surfaces it.
- **Handlers open their own database connections**, so they cannot see the caller's
  uncommitted transaction. Publishing an event *before* the surrounding request commits
  means a handler may observe a row that does not exist yet. Events should be published
  after commit, or handlers should join the caller's transaction.

For a production system with reliability requirements this becomes a real queue (SQS,
Kafka) with retries and a dead-letter queue — but the subscriber interface in application
code stays the same, which is the point of routing side-effects through a bus at all.

---

## 6. LangChain Router Agent

**Files:** `app/chat/router_agent.py`, `app/chat/tools.py`, `app/chat/prompt.py`

The chat interface is backed by an LLM agent that uses tool-calling to map user intent
onto backend operations. Per message:

1. Build message history (system prompt + last 20 turns)
2. Stream from the LLM with five tool schemas bound
3. If the LLM returns a tool call → execute it, return structured BDUI elements
4. If the LLM returns text → wrap it as a text element

### The loop is deliberately single-pass

Most agent frameworks run a loop: call tool → feed the result back to the LLM → let it
decide what to do next → repeat until it stops. This one does not. Tool results are
rendered and returned to the user directly, and the LLM never sees them.

That is a deliberate trade:

- **What it buys:** exactly one LLM round-trip per message, so latency and cost are
  bounded and predictable. No runaway loops, no token budget that grows with tool output.
  Tool results reach the user as structured cards rather than as an LLM paraphrase of
  structured cards — which also removes any opportunity for the model to garble a number.
- **What it costs:** no multi-step reasoning. *"Log 40 pages of whatever I was reading
  yesterday"* cannot be answered, because that needs a lookup and then a decision
  informed by it.

The bridge is `metadata_updates` — tools write small facts like `last_book_title` and
the last set of search results into session metadata, so limited cross-turn context
survives without a second LLM call. If multi-step requests became a requirement, this
is the decision I would revisit first.

The same constraint shapes how aggregate questions are answered. *"What is my most read
book?"* needs ranking, and a looping agent would fetch the list and then reason over it
in a second turn. Instead `show_progress` takes `sort_by` and `limit`, and
`ReadingService` does the ranking. The model picks the ordering; the backend computes
the answer. Pushing the aggregation into the service is what lets a superlative question
stay within one round-trip — and it keeps the model from arithmetic it is bad at.

### Determinism where determinism is cheap

`"help"` and its variants are intercepted before the LLM is called at all and answered
with a fixed help card. A known question with a fixed answer should not cost a network
round-trip or risk a rephrasing. Intercepts run before the check for LLM credentials,
so fixed replies keep working even when no model is configured.

**Recommendation requests are intercepted the same way, and the reason is specific.**
The app can't recommend books, and handing *"suggest a book"* to the agent does not
fail cleanly — the model launders it into a plausible search. Observed: *"suggest a
book"* became `search_books("fiction")` (magazines, a library catalogue), and *"any good
books?"* became `search_books("bestsellers")` (books *about* bestsellers).

That laundering is why the decline has to happen before the LLM. Once the request is
`search_books("fiction")`, it is indistinguishable from a user who asked for fiction —
the only signal that separates them is the user's own words. So the router matches the
*request form* ("recommend a…", "what should I read", "any good books") rather than
bare words, which keeps topic searches like *"books about recommendation systems"*
reaching the agent. The decline's "Search by genre/author/topic" buttons are answered
deterministically too: left to the model, "Search by genre" sometimes replied that
genre search wasn't supported, because `search_by` only enumerates `title|author`.

Two weaker layers sit behind it, because a regex will always miss some phrasing:

- `search_books` rejects queries made entirely of filler words (*"recommended"*,
  *"good books"*) and returns the same decline. It cannot catch `"fiction"`, a real
  genre — which is exactly why it is the backstop and not the fix.
- The system prompt and the `search_books` description tell the model not to invent
  queries for recommendations. A prompt is the least reliable of the three, so it is
  the last line rather than the first.

The same instinct shapes the retry policy: two attempts with a short backoff, then a
plain error element. An LLM call is treated as what it is — an unreliable network
dependency — rather than as a function call.

---

## 7. Backend-Driven UI (BDUI)

**Files:** `app/chat/ui.py`, `frontend/src/components/BduiRenderer.jsx`

Chat responses are structured JSON element trees, not raw HTML or markdown strings:

```json
{
  "type": "composite",
  "elements": [
    {"type": "text", "content": "Logged **50 pages** of *Dune*.", "style": "success"},
    {"type": "book_progress", "data": {...}},
    {"type": "action_buttons", "buttons": [...]}
  ]
}
```

The frontend's `BduiRenderer` switches on `element.type` and renders the matching React
component.

### Why not just return markdown?

That was the obvious alternative, and rejecting it is the actual decision here.

A chat reply in this app is not prose — it is *"here is a progress bar, a book cover, and
two things you can do next."* Markdown can only describe that as text. Getting a real
progress bar out of a markdown reply means the client has to pattern-match the model's
output to decide what widget to draw, which makes the UI a function of LLM phrasing. It
breaks the moment the model words something differently.

The element tree inverts that. The backend already knows it just logged 40 of 412 pages,
so it says `book_progress` and the client draws a progress bar. **The LLM's phrasing
affects only the text element, never the structure of the response.** An LLM that has a
bad day produces an awkward sentence next to a correct progress card, rather than a
missing progress card.

### What it buys

- **New widgets don't need a coordinated deploy.** A new element type is a backend change
  plus one `case` in the renderer — no feature flags, no version negotiation.
- **Interaction is uniform.** A button carries `action` and `payload`; clicking it sends
  `message_type: "action_click"` back through the same WebSocket, and the agent handles it
  as another turn. Typing and clicking share one code path rather than one path plus a
  command API.
- **Responses are replayable.** Elements are persisted in `chat_messages.ui_payload`, so
  reloading a session re-renders the original cards instead of a flattened transcript.

### What it costs

- **The backend owns presentation now.** A copy tweak or a spacing change becomes a
  backend deploy. The clean layering above stops at `ui.py`, which is a presentation
  concern living in the service tier.
- **Version skew is a real risk.** An old client that doesn't know an element type renders
  nothing. `BduiRenderer` returning `null` for unknown types makes that a silent blank
  rather than a crash — the failure mode is chosen, but it is still a failure mode.
- **The payload is now a schema.** Old rows in `ui_payload` must stay renderable forever,
  so element shapes are effectively an append-only contract. Renaming a field means
  migrating history.
- **It only pays off for generated UI.** For a CRUD screen this would be pure overhead.
  It earns its keep here because the server decides what the response *is*, turn by turn.

---

## 8. Event-Sourced Reading Progress

**Files:** `backend/init_db.sql`, `app/repositories/reading_repository.py`

**There is no `progress` column anywhere in the schema.** `reading_sessions` is the fact
table — one row per *"I read N pages on date D"* — and every number the UI displays is
derived from it at read time:

```sql
SELECT books.page_count           AS total_pages,
       SUM(reading_sessions.pages) AS pages_read,
       MAX(reading_sessions.read_on) AS last_read_date
FROM reading_sessions JOIN books ON ...
GROUP BY books.id
```

### Why derive instead of store

A stored `pages_read` counter and the sessions that produced it are two sources of truth
for one fact, and they drift. Every write path has to remember to update both; a failure
between the two writes leaves them inconsistent, and nothing detects it because each
looks fine on its own. The bug that results — *"my total says 340 but my sessions add up
to 290"* — is invisible until a user reports it, and unfixable after the fact because you
cannot tell which number was wrong.

Deriving the total makes that class of bug unrepresentable. The sum **is** the progress;
there is nothing for it to disagree with.

Three things follow from it that are worth having:

- **Undo is one row.** `undo_last_log` deletes the newest session — the log's last event —
  whichever book it was for. That is exact for anything appended, and only for that:
  see the next bullet.
- **Corrections are natural.** *"I meant 20, not 40"* walks the sessions backwards from the most
  recent and trims them. With a stored counter it is arithmetic on a number nobody can
  audit; here it is an operation on the records that produced it.
- **History is free.** Reading streaks, pages-per-week, "what was I reading in March" are
  all queries against a table that already exists, with no migration and no new writes.
  None of that is built yet — the point is that the schema does not stand in the way.
- **Tracking with zero progress is representable.** `start_tracking` inserts a session of
  `pages = 0`, which is why "tracked but not started" is a real state and the
  `not_started` filter has something to filter. With a counter, "0" and "absent" are the
  same value.

### What it costs

- **`read_on` is a `DATE`, so the log alone cannot order two books read on the same
  day.** Progress therefore also carries `MAX(created_at)` as `last_session_at`, purely
  to break that tie when ranking by recency. Worth knowing that the fact table's
  natural key is coarser than it looks.
- **Every progress read is an aggregate.** Acceptable at this size, with
  `idx_rs_user_book` covering the grouping. At a scale where a user has tens of thousands
  of sessions, this wants a rollup table or a materialized view — reintroducing the stored
  total deliberately, as a *cache* that can be rebuilt from the log, rather than as a
  second source of truth.
- **The log is not actually append-only, and that is a real inconsistency.** `reduce` and
  `set` DELETE and UPDATE historical rows. A strict event-sourced design would append a
  compensating negative entry instead, preserving the audit trail and keeping the
  aggregate a pure `SUM`. The current approach destroys history to keep the sum correct.
  The schema comment calls the table append-only; today the write paths do not honour
  that. Appending corrections is the change I would make first.

---

## 9. The Book Resolution Pipeline

**Files:** `app/services/book_service.py`, `app/services/book_intelligence.py`

Turning *"harry potter 1"* into one specific Google Books volume is the hardest problem
in the app. `resolve_book()` handles it in six stages, ordered so that **the cheapest and
most deterministic step always runs first**:

| # | Stage | Cost |
|---|-------|------|
| 0 | Match against results already shown this session | in-memory |
| 1 | Ranked substring title lookup in the local DB | one indexed query |
| 2 | LLM normalizes the query, and flags non-book queries | one LLM call |
| 3 | Retry the DB lookup with the normalized title | one indexed query |
| 4 | Google Books search, top 5 English results | one HTTP call |
| 5 | LLM selects the best of the 5 candidates | one LLM call |
| 6 | Dedupe on `google_volume_id`, then persist | one indexed query |

The ordering is the design. An LLM call is the most expensive and least predictable step
available, so it is never the first thing tried — stages 1 and 3 are a cache, and a title
that anyone has already resolved costs a single indexed query with no LLM and no HTTP.

Stage 3 exists because of a specific failure: stage 2 may rewrite *"harry potter 1"* into
a title the database already holds under its formal name. Skipping the re-check would
search Google for a book already sitting in the local table.

### Stage 0: resolving against what the user was shown

Stages 1–6 resolve a title in isolation, which is wrong when the user is replying to
something on screen. Searching *"ayn rand"* shows The Fountainhead at 740 pages;
typing *"The Fountainhead"* used to re-enter at stage 1, where stage 2 rewrote the
query to *"The Fountainhead by Ayn Rand"*, stage 4 fetched a different candidate set,
and stage 5 picked a 754-page edition. The user tracked a book they never saw.

The fix is to treat the last search results as part of the conversation's state.
`execute_search_books` writes the volumes it displayed into session metadata, and
`resolve_book` takes an optional `recent_results` and matches the title against them
before anything else. A hit resolves on `google_volume_id`, which is the identity the
catalogue already canonicalizes on, so the tracked row is exactly the displayed volume.

Matching is ordered by how sure it is, because a loose substring test cuts both ways:

1. **Exact title** — unambiguous, wins outright.
2. **A shown title inside a longer query** — *"The Fountainhead by Ayn Rand"* names
   *"The Fountainhead"*. The longest such title wins, being the most specific.
3. **The query inside a shown title**, but only when it covers at least 60% of it.
   *"fountainhead"* is 75% of *"The Fountainhead"* and matches; *"Dune"* is 33% of
   *"Dune Messiah"* and does not. Without that floor, searching for a sequel would
   hijack every later mention of the original.

Action buttons carry the same identity. A button emitted for a resolved book includes
its `google_books_id`, and a click resolves that id directly rather than re-matching
on a title string, because titles are not unique.

Stage 1 has the same hazard and gets the same treatment. `get_by_title` is a substring
`LIKE`, so *"Dune"* also matches *"Dune Messiah"*; it now ranks exact titles first,
then prefixes, then the shortest remaining title, and takes one row. Previously it
returned whichever row the planner happened to produce first, which was not even
stable between runs.

The fallback is deliberate and total: no recent results, no match, or a payload too
sparse to rebuild a book all drop straight through to the normal pipeline. Stage 0
can only ever pin a volume the user actually saw; it can never block resolution.

### Two LLM calls, two different jobs

They are deliberately not merged into one prompt. **Normalization** (stage 2) is
open-ended generation — it turns a fuzzy string into a canonical title and decides
whether the request is about a book at all. **Selection** (stage 5) is constrained
classification — given five concrete candidates, return an index. Both use structured
output (`with_structured_output`) so the response is a validated Pydantic model rather
than a string to be parsed.

Keeping them separate means stage 5 cannot invent a book: it returns an index into a list
the backend already holds, or `-1`. The model chooses among real options rather than
producing a title that may not exist. Merging them would trade that guarantee for one
saved round-trip.

### Degrading without an LLM

If no LLM credentials are configured, `get_langchain_llm()` returns `None` and both
stages degrade rather than fail — stage 2 passes the raw query through, stage 5 returns
the first search result. Resolution keeps working; it just gets dumber. The chat agent,
by contrast, requires the LLM and says so plainly. That asymmetry is intentional: book
lookup has a sensible non-AI fallback, and intent routing does not.

### Canonicalizing on volume ID

Stage 6 deduplicates on `google_volume_id`, which carries a `UNIQUE` constraint, rather
than on title. `books` is a **global catalogue shared by all users**, not a per-user list,
so two users who reach the same book by different phrasings converge on one row — and
their reading sessions point at the same book. Title-based dedup would have produced
near-duplicate rows for every spelling variation.

---

## 10. The Agent Is a Routing Layer

**Files:** `app/chat/tools.py`, `app/routers/books.py`, `app/routers/reading.py`,
`app/services/`, `tests/test_adapter_equivalence.py`

The chat agent translates sentences into service calls. It decides *which* operation a
message means; it does not decide *what that operation does*. Every rule — how a
percentage becomes a page count, what "already tracking" means, which entry "undo"
removes, whether 500 pages fits in a 412-page book — belongs to the services.

The REST API exists to prove that. It is a second adapter over the same services, and
its routes are one or two lines each: resolve the book, call the operation, return the
result. If a route ever needs an `if`, a rule has leaked out of the service layer.

### Why this needed a second adapter to hold

When the agent was the only caller, "tools contain no business logic" was a convention
with nothing enforcing it, and it had quietly eroded. An audit before adding REST found
eight rules living in `tools.py` or in the model itself:

- percentage-to-pages conversion, and the "unknown page count" rule
- "pages or a percentage is required" — checked as `if not pages`, so **setting progress
  to page 0 was impossible**
- which service method each of add / set / reduce / remove maps to
- what tracking means: a zero-page entry, idempotent, and never silently dropping pages
- precedence between a clicked volume id and a typed title — with no domain operation at
  all for "resolve this exact volume", which a stateless REST client needs
- search, which the tool reached by going *through* `BookService` to its client, because
  the service had no search operation
- translating repository `ValueError`s into messages — which over HTTP would have been
  `500`s
- **undo, which didn't exist.** *"Undo that"* worked by the model recalling the last
  amount and book from chat history and issuing a `reduce`. The business logic was
  running inside the LLM.

Each became a service operation. A boundary with a single client is only a convention;
a second client is what makes it a contract.

### One rule, one message, two renderings

Services raise domain exceptions — `BusinessLogicError`, `EntityNotFoundError`,
`BookResolutionError` — never `ValueError`. The REST layer maps them to `400` / `404` /
`502` in one place (`main.py`); the agent renders the same message as chat text. So a
violated rule produces the same sentence through both doors, and the equivalence tests
assert exactly that, string for string.

Result types are shared too. `start_tracking` returns a `TrackingResult`, which REST
serialises as the response body and the agent renders as a card — the progress JSON
inside the agent's card is byte-for-byte the JSON the REST route returns.

### What deliberately stays in the agent

Anything that exists because the input is a conversation stays in the conversational
adapter:

- natural-language dates (*"yesterday"*); REST takes an ISO date instead
- the search results remembered in session metadata, and the volume ids in button
  payloads — conversation state a stateless client doesn't have
- the filler-query guard and the recommendation intercept, which defend against the
  *model* inventing queries rather than enforcing a rule about searching
- headers, cards, suggestions — presentation

The test for where something belongs: would a REST client need the same behaviour? If
yes, it's a rule and goes in a service. If it only makes sense because a model or a
chat transcript is involved, it stays in the adapter.

### How it's enforced

`tests/test_adapter_equivalence.py` runs each operation once through a REST route and
once through the corresponding tool, each against a fresh, identical set of in-memory
fakes. A thin spy around each service records which operations the *adapter* invoked —
calls a service makes to itself go through `self` and stay invisible, which is exactly
the boundary under test. The tests then assert the same calls, the same resulting
state, and the same result or error message.

---

## Composition Root

**File:** `app/core/dependencies.py`

All wiring of concrete implementations to interfaces happens in one place:

```python
def get_book_service(conn) -> BookService:
    return BookService(
        repo=BookRepository(conn),
        search_client=GoogleBooksClient(),
        intelligence=BookIntelligenceService(),
    )
```

This is the only module that names concrete classes alongside the interfaces they
satisfy. Everything else talks in abstractions.

**Where this leaks today:** `app/chat/tools.py` imports `get_book_service` and
`get_reading_service` and calls them directly as factories, outside of FastAPI's
dependency system. It works — they are ordinary functions — but it means those providers
serve two roles at once, and the chat layer reaches into the DI wiring instead of being
handed its dependencies. The clean fix is to separate the factory from the FastAPI
provider and have the tool context carry pre-built services.

---

## Other Decisions Worth Naming

**SQLAlchemy Core rather than the ORM.** Every query here is a deliberate SELECT with an
explicit GROUP BY. Core gives composable, type-checked SQL without a session cache,
identity map, or lazy-loading — none of which this app wants, and all of which introduce
implicit queries that are hard to reason about under async. The trade is writing the
joins by hand. For a read pattern this specific, that is the better side of the trade.

**`init_db.sql` rather than migrations.** The schema is applied once by the Postgres
entrypoint. That is fine for a project with no production data and no second
environment, and it is honestly the wrong tool the moment either exists — there is no
way to evolve a schema in place. Alembic is the correct answer for anything beyond this;
the current setup is chosen for reviewer setup time, not because migrations were
considered unnecessary.

**JWT rather than server-side sessions.** Tokens carry `sub` and `exp` and nothing else,
so authenticating a request is a signature check plus one user lookup, with no session
store. The cost is that logout cannot invalidate a live token — seven days is a long
window for a leaked one. A production version wants shorter expiry plus refresh tokens,
or a revocation list.

---

## Design Summary

| Pattern | Applied Where |
|---------|--------------|
| Protocol interfaces (DIP) | `interfaces/` → `services/` |
| Composition Root | `core/dependencies.py` |
| Domain Mappers (SRP) | `domain/mappers.py` |
| Value Objects | `domain/value_objects.py` |
| Strategy (password hashing) | `services/password_hasher.py` |
| Observer / Event Bus | `events/` |
| Tool-calling Agent | `chat/router_agent.py` |
| Backend-Driven UI | `chat/ui.py` + `BduiRenderer.jsx` |
| Event sourcing (derived state) | `reading_sessions` → `BookProgress` |
| Layered resolution w/ LLM fallback | `services/book_service.py` |
| Ports & adapters (agent + REST) | `chat/tools.py`, `routers/` → `services/` |
