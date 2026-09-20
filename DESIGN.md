# ReadLedger — Low-Level Design

This document covers the key design decisions made in ReadLedger's backend and the reasoning behind them.

---

## Architecture Overview

```
Routers → Services → Repositories → Database
             ↑              ↑
         Interfaces     Interfaces
         (Protocols)   (Protocols)
```

Every layer talks to the layer below it through an interface, not a concrete class. Services don't know what database you're using. Repositories don't know what business logic runs on top of them.

---

## 1. Protocol-Based Dependency Injection

**Files:** `app/interfaces/repository_interfaces.py`, `app/interfaces/client_interfaces.py`

Python's `typing.Protocol` lets you define structural interfaces — a class satisfies a Protocol just by having the right method signatures, with no inheritance required.

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

The concrete wiring happens in exactly one place — `app/core/dependencies.py`. Every other file in the codebase only knows about interfaces.

**Why Protocol over ABC?** With ABCs, your fake/test classes have to import from production modules to inherit. With Protocol, a `FakeBookRepository` in tests can satisfy `IBookRepository` without importing it — just by having the same methods. This breaks the dependency entirely.

---

## 2. Domain Mappers

**Files:** `app/domain/mappers.py`

Mappers are pure static classes responsible for one thing: converting a raw DB row (or API response) into a domain model.

```python
# Domain model is just data
class User(BaseModel):
    id: UUID
    email: str

# Mapper handles the DB → domain conversion
class UserMapper:
    @staticmethod
    def from_db(row: dict) -> User:
        return User(
            id=row["id"],
            email=row["email"],
            hashed_password=row.get("hashed_password") or row.get("password_hash"),
        )
```

The key benefit: if a DB column gets renamed, you change the mapper — nothing else. The domain model doesn't need to know about DB column names, and the repository doesn't need to know how to construct domain objects.

---

## 3. Value Objects

**Files:** `app/domain/value_objects.py`

Value objects enforce domain invariants at construction time. They fail fast, at the boundary, rather than letting invalid data propagate silently through the system.

```python
PageCount(-1)    # raises ValueError immediately
Email("notvalid") # raises ValueError immediately
```

`PageCount` is used in `ReadingRepository.create_session()` to validate pages before any DB call is made. `Email` is validated in the registration endpoint before we even check if the user exists.

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

`AuthService` doesn't know which algorithm it uses — it just calls `self._hasher.hash()`. Switching from bcrypt to Argon2 is changing one line in `dependencies.py`.

---

## 5. Event Bus

**Files:** `app/events/event_bus.py`, `app/events/user_events.py`, `app/events/handlers.py`

The event bus decouples side-effects from core flows. When a user registers, the registration handler publishes a `UserRegisteredEvent`. Anything that needs to react to registration — audit logging, welcome emails, analytics — subscribes independently.

```python
# Registration flow: no knowledge of what happens next
await event_bus.publish(UserRegisteredEvent(user_id=..., email=...))

# Independently, handlers react
async def on_user_registered(event: UserRegisteredEvent):
    await _write_audit_log("user_registered", event.user_id, ...)
```

Events are frozen dataclasses — immutable and typed. Handlers are registered at startup in `main.py`. Adding a new side-effect is adding one function and one `subscribe()` call. The registration router never changes.

One design constraint worth noting: the event bus is in-process. It doesn't survive restarts and has no retry logic. For a production system with reliability requirements, you'd replace it with a message queue (SQS, Kafka, etc.) — but the subscriber interface in the application code would stay the same.

---

## 6. LangChain Router Agent

**Files:** `app/chat/router_agent.py`, `app/chat/tools.py`

The chat interface is backed by an LLM agent that uses tool-calling (OpenAI function calling format) to map user intent to backend operations. The flow for each message:

1. Build message history (system prompt + last N turns)
2. Stream from LLM with tools bound
3. If LLM returns a tool call → execute the tool, return structured BDUI response
4. If LLM returns text → return it as a text element

Tool definitions are JSON schemas that tell the LLM what parameters each tool expects. The LLM fills in the arguments from context; the backend executes.

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

The frontend's `BduiRenderer` switches on `element.type` and renders the appropriate React component. This means the backend controls the entire UI experience — new widget types only require a backend change and a new case in the renderer. No feature flags, no coordinated deploys.

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

This is the only place in the entire codebase that mentions concrete class names together with their interfaces. Every other file talks in terms of protocols and abstractions.

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
