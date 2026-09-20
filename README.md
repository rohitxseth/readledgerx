# ReadLedger

**A reading tracker you talk to.** Tell it "I read 40 pages of Dune last night" and it finds the book, logs the pages, and shows your progress — no forms, no dropdowns.

---

<!-- ─────────────────────────────────────────────────────────────────────
     TODO: ADD SCREENSHOT OR GIF HERE

     Record a ~15s GIF of a real chat turn. The sequence that shows the
     most in the least time:
       1. Type "I read 40 pages of Dune"
       2. Let the streaming text render live
       3. Let the progress card and action buttons appear

     Save it to docs/demo.gif, then replace this whole comment block with:
         ![ReadLedger chat demo](docs/demo.gif)

     Recording tools: Kap (free, macOS) or CleanShot X → "Record as GIF".
     Keep it under 5 MB so GitHub renders it inline.
     ───────────────────────────────────────────────────────────────────── -->

> **[ Screenshot / demo GIF goes here — see the comment above ]**

---

## What it does

- **Log reading in plain English** — "read 40 pages of Dune", "I'm at 25% of Sapiens", "undo that"
- **Finds the right book** — an LLM normalizes fuzzy titles ("harry potter 1") and picks the best Google Books match
- **Tracks progress** — pages read, percent complete, per book or across your whole shelf
- **Streams responses** over WebSocket, token by token
- **Renders server-driven UI** — the backend returns UI element trees (progress cards, buttons), the React client just renders them

## Architecture

**One chat turn, end to end:**

```
  Browser                    FastAPI                      External
 ─────────                  ─────────                    ──────────
 "read 40 pages
  of Dune"
     │
     │  WebSocket frame
     ▼
  ws_chat ──► authenticate (JWT) ──► ChatService
                                         │
                            ┌────────────┴────────────┐
                            │ 1. load/create session  │
                            │ 2. persist user message │
                            │ 3. load last 30 turns   │
                            └────────────┬────────────┘
                                         ▼
                                    RouterAgent
                                         │
                                  bind 4 tool schemas
                                         │
                                         ▼
                                 stream from LLM ──────────►  Azure OpenAI
                                         │                      (streaming)
                    ┌────────────────────┴───────────┐
                    │                                │
             returns text                     returns tool_call
                    │                                │
                    │                                ▼
                    │                      execute_tool(log_reading)
                    │                                │
                    │                        BookService ──────────►  Google Books
                    │                                │                    API
                    │                        ReadingService
                    │                                │
                    │                          Repositories ────────►  PostgreSQL
                    │                                │
                    └────────────────┬───────────────┘
                                     ▼
                          BDUI element tree
                    { text, book_progress, buttons }
                                     │
     ◄───────────────────────────────┘
  BduiRenderer switches on element.type → React components
```

**Layered backend** — each layer depends only on the one below it, through an interface:

```
   routers/          HTTP + WebSocket endpoints, no business logic
       │
       ▼
   services/         BookService, ReadingService, AuthService
       │                        │
       │             depends on Protocols, never concrete classes
       ▼                        │
   interfaces/       IBookRepository, IReadingRepository,
       │             IUserRepository, IBookSearchClient
       ▼
   repositories/     SQLAlchemy Core queries        integrations/
   + domain/         mappers, value objects         GoogleBooksClient
       │                                                  │
       ▼                                                  ▼
   PostgreSQL                                      Google Books API

   core/dependencies.py  ── the composition root: the one place that
                            wires concrete classes to those interfaces
```

## Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI (async), WebSocket streaming |
| Database | PostgreSQL 15, SQLAlchemy Core + asyncpg |
| LLM | LangChain + Azure OpenAI (tool calling, structured output) |
| Auth | JWT (python-jose), bcrypt |
| External data | Google Books API |
| Frontend | React 18 + Vite |
| Tooling | uv, pytest + pytest-asyncio |

## Local Setup

Verified from a clean clone on macOS.

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker, Node 18+, and an Azure OpenAI or OpenAI API key.

### 1. Clone and configure

```bash
git clone https://github.com/rohitx26/readledger.git
cd readledger
cp backend/.env.example backend/.env
```

Open `backend/.env` and fill in at minimum:

- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` — without these the chat replies "AI service is not configured"
- `JWT_SECRET_KEY` — generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`

`GOOGLE_BOOKS_API_KEY` is optional; book search works unauthenticated at low volume.

### 2. Start PostgreSQL

```bash
docker compose up postgres-db -d
```

The schema in `backend/init_db.sql` is applied automatically on first start.

### 3. Run the backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Check it: `curl localhost:8000/health` should return `{"status":"healthy","database":"connected"}`.
Interactive API docs at `http://localhost:8000/docs`.

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`, register an account, and start chatting.

### Running tests

```bash
cd backend
uv run pytest
```

Every test is a unit test — no database, no network. Repositories and the Google Books client are replaced with in-memory fakes that satisfy the same `typing.Protocol` interfaces the real implementations do.

## Design decisions

The backend is layered behind `typing.Protocol` interfaces, with all concrete wiring in a single composition root (`app/core/dependencies.py`). That choice is what makes the service tests above run without a database or an HTTP client.

[**DESIGN.md**](./DESIGN.md) covers the reasoning in full:

| Decision | Why |
|----------|-----|
| [Protocol over ABC](./DESIGN.md#1-protocol-based-dependency-injection) | Test fakes satisfy the interface without importing production code |
| [Composition root](./DESIGN.md#composition-root) | One file knows about concrete classes; everything else sees interfaces |
| [Domain mappers](./DESIGN.md#2-domain-mappers) | DB column renames stay contained to one file |
| [Value objects](./DESIGN.md#3-value-objects) | Invalid page counts and emails fail at construction, not at the DB |
| [Event bus](./DESIGN.md#5-event-bus) | Audit logging subscribes to registration instead of being called by it |
| [Backend-driven UI](./DESIGN.md#7-backend-driven-ui-bdui) | New chat widgets ship as a backend change plus one renderer case |

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/register` | POST | Register with email + password |
| `/auth/login` | POST | Login, returns JWT |
| `/chat/ws` | WS | Streaming chat (primary interface) |
| `/chat/message` | POST | Single-turn chat, non-streaming |
| `/chat/sessions` | GET | List chat sessions |
| `/chat/history` | GET | Message history for a session |
| `/health` | GET | Liveness + DB reachability |

<details>
<summary>WebSocket protocol</summary>

```
Client → {"type": "auth", "token": "<JWT>"}
Server → {"type": "auth_ok", "user_id": "...", "email": "..."}

Client → {"type": "message", "session_id": "...", "message": "log 30 pages of dune"}
Server → {"type": "text_chunk", "content": "..."}      # streamed, repeated
Server → {"type": "element", "element": {...}}          # BDUI elements
Server → {"type": "done", "response": {...}, "suggestions": [...]}
```

</details>

<details>
<summary>Project structure</summary>

```
backend/app/
├── chat/           # RouterAgent, tool implementations, BDUI helpers, session manager
├── config/         # Settings, LLM provider selection, logging
├── core/           # Composition root (dependencies.py), domain exceptions
├── domain/         # Mappers, value objects
├── events/         # In-process event bus, user events, handlers
├── integrations/   # Google Books client
├── interfaces/     # Protocol definitions
├── repositories/   # SQLAlchemy Core queries
├── routers/        # FastAPI route handlers
├── schemas/        # Pydantic request/response models
└── services/       # Business logic

frontend/src/
├── components/     # ChatPage, BduiRenderer, cards
├── hooks/          # useChatWebSocket (reconnect, ping, stream accumulation)
└── services/       # auth
```

</details>
