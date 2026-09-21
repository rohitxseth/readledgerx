"""
The chat turn's storage and its single failure boundary.

Covers the fixes for JSON being double-encoded into JSONB columns, storage
errors being swallowed (with a made-up message id in their place), and the
WebSocket reporting a failed turn as a proper error element.
"""

import uuid
from contextlib import asynccontextmanager

import pytest
from langchain_core.messages import AIMessageChunk
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from starlette.testclient import TestClient

from app.chat import chat_service, session_manager
from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.routers import chat as chat_router
from app.schemas.chat import ChatRequest
from tests.conftest import make_user

USER = make_user()


class _Result:
    def __init__(self, row=None):
        self._row = row

    def scalar_one(self):
        return self._row["id"]

    def one(self):
        return _Row(self._row)

    def first(self):
        return _Row(self._row) if self._row else None


class _Row:
    def __init__(self, mapping):
        self._mapping = mapping


class _RecordingConn:
    """Captures the bound parameters of every statement it is given."""

    def __init__(self, row=None):
        self.params: list[dict] = []
        self._row = row

    async def execute(self, stmt):
        self.params.append(stmt.compile(dialect=postgresql.dialect()).params)
        return _Result(self._row)


# ---------------------------------------------------------------------------
# JSONB columns receive objects, not JSON-encoded strings
# ---------------------------------------------------------------------------


async def test_ui_payload_is_stored_as_an_object():
    conn = _RecordingConn(row={"id": uuid.uuid4()})
    payload = {"type": "composite", "elements": [{"type": "text", "content": "Hi"}]}

    await session_manager.add_message(
        conn, uuid.uuid4(), "assistant", "Hi", ui_payload=payload
    )

    assert conn.params[0]["ui_payload"] == payload


async def test_new_session_metadata_is_stored_as_an_object():
    row = {"id": uuid.uuid4(), "user_id": USER.id, "metadata": {}}
    conn = _RecordingConn(row=row)

    await session_manager.create_session(conn, USER.id)

    assert conn.params[0]["metadata"] == {}


async def test_add_message_returns_the_stored_id():
    message_id = uuid.uuid4()
    conn = _RecordingConn(row={"id": message_id})

    assert await session_manager.add_message(conn, uuid.uuid4(), "user", "hi") == str(
        message_id
    )


# ---------------------------------------------------------------------------
# Storage failures propagate instead of being swallowed
# ---------------------------------------------------------------------------


@pytest.fixture
def stored_turn(monkeypatch):
    """Point process_message at in-memory session storage."""
    session = {"id": uuid.uuid4(), "user_id": USER.id, "metadata": {}}
    saved: list[dict] = []

    async def create_session(conn, user_id, name=None):
        return session

    async def add_message(
        conn, session_id, role, content=None, message_type="text", ui_payload=None
    ):
        saved.append({"role": role, "content": content, "ui_payload": ui_payload})
        return f"msg-{len(saved)}"

    async def get_conversation_history(conn, session_id, limit=50):
        return [dict(m) for m in saved[-limit:]]

    monkeypatch.setattr(chat_service, "create_session", create_session)
    monkeypatch.setattr(chat_service, "add_message", add_message)
    monkeypatch.setattr(
        chat_service, "get_conversation_history", get_conversation_history
    )
    return saved


async def test_the_reply_carries_the_real_message_id(stored_turn):
    reply = await chat_service.process_message(
        ChatRequest(message="help"), USER, conn=None
    )

    assert reply["message_id"] == "msg-2"  # the assistant row, not a generated uuid
    assert [m["role"] for m in stored_turn] == ["user", "assistant"]


async def test_a_storage_failure_fails_the_turn(stored_turn, monkeypatch):
    async def add_message(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(chat_service, "add_message", add_message)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await chat_service.process_message(ChatRequest(message="help"), USER, conn=None)


# ---------------------------------------------------------------------------
# The LLM sees the newest history, and the current message once
# ---------------------------------------------------------------------------


class _QueryConn:
    """Keeps the statement it is given and returns rows in the order supplied."""

    def __init__(self, rows):
        self.statement = None
        self._rows = rows

    async def execute(self, stmt):
        self.statement = stmt
        return [_Row(row) for row in self._rows]


async def test_history_is_the_newest_messages_oldest_first():
    # What the database returns for ORDER BY created_at DESC LIMIT 3 over m1..m5.
    conn = _QueryConn([{"content": f"m{i}"} for i in (5, 4, 3)])

    history = await session_manager.get_conversation_history(
        conn, uuid.uuid4(), limit=3
    )

    compiled = conn.statement.compile(dialect=postgresql.dialect())
    assert "ORDER BY chat_messages.created_at DESC" in str(compiled)
    assert 3 in compiled.params.values()
    assert [m["content"] for m in history] == ["m3", "m4", "m5"]


def test_the_history_route_returns_the_newest_messages_oldest_first(monkeypatch):
    session_id = uuid.uuid4()
    conn = _QueryConn([{"content": f"m{i}"} for i in (5, 4)])

    async def load_session(conn, session_id):
        return {"id": session_id, "user_id": USER.id}

    async def db():
        yield conn

    monkeypatch.setattr(chat_router, "load_session", load_session)
    app.dependency_overrides = {get_current_user: lambda: USER, get_db: db}
    try:
        r = TestClient(app).get(f"/chat/history?session_id={session_id}&limit=2")
    finally:
        app.dependency_overrides = {}

    assert r.status_code == 200
    assert [m["content"] for m in r.json()["messages"]] == ["m4", "m5"]


class _RecordingLLM:
    """Answers every call with plain text and keeps the messages it was sent."""

    def __init__(self):
        self.calls: list[list] = []

    def bind_tools(self, tools):
        return self

    async def astream(self, messages):
        self.calls.append(messages)
        yield AIMessageChunk(content="Sure.")


def _transcript(messages) -> list[tuple[str, str]]:
    return [(type(m).__name__, m.content) for m in messages[1:]]  # skip the system prompt


async def test_the_current_message_reaches_the_llm_once(stored_turn, monkeypatch):
    llm = _RecordingLLM()
    monkeypatch.setattr(chat_service, "get_llm", lambda: llm)

    await chat_service.process_message(
        ChatRequest(message="log 20 pages of Dune"), USER, conn=None
    )

    assert _transcript(llm.calls[0]) == [("HumanMessage", "log 20 pages of Dune")]


async def test_earlier_turns_come_before_the_current_message(stored_turn, monkeypatch):
    llm = _RecordingLLM()
    monkeypatch.setattr(chat_service, "get_llm", lambda: llm)

    await chat_service.process_message(
        ChatRequest(message="log 20 pages of Dune"), USER, conn=None
    )
    await chat_service.process_message(ChatRequest(message="undo that"), USER, conn=None)

    assert _transcript(llm.calls[1]) == [
        ("HumanMessage", "log 20 pages of Dune"),
        ("AIMessage", "Sure."),
        ("HumanMessage", "undo that"),
    ]


def test_a_malformed_session_id_is_rejected_at_the_boundary():
    """Previously a database error on the bad id was swallowed into "new session"."""
    with pytest.raises(ValidationError):
        ChatRequest(session_id="not-a-uuid", message="hi")


# ---------------------------------------------------------------------------
# The WebSocket is the one place a failed turn is handled
# ---------------------------------------------------------------------------


@pytest.fixture
def ws(monkeypatch):
    async def authenticate(token):
        return USER if token == "good" else None

    class _Engine:
        @asynccontextmanager
        async def begin(self):
            yield None

    monkeypatch.setattr(chat_router, "_authenticate_ws", authenticate)
    monkeypatch.setattr(chat_router, "async_engine", _Engine())
    with TestClient(app).websocket_connect("/chat/ws") as socket:
        socket.send_json({"type": "auth", "token": "good"})
        assert socket.receive_json()["type"] == "auth_ok"
        yield socket


def test_a_failed_turn_sends_an_error_element_and_keeps_the_socket_open(
    ws, monkeypatch
):
    async def failing_turn(body, user, conn, send_fn=None):
        raise RuntimeError("connection reset by database")

    monkeypatch.setattr(chat_router, "process_message", failing_turn)
    ws.send_json({"type": "message", "message": "log 20 pages of Dune"})
    frame = ws.receive_json()

    assert frame["type"] == "error"
    assert frame["element"] == {
        "type": "composite",
        "elements": [
            {
                "type": "text",
                "content": "Something went wrong processing your message.",
                "style": "error",
            }
        ],
    }
    assert "database" not in frame["message"]  # internals stay in the server log

    ws.send_json({"type": "ping"})
    assert ws.receive_json() == {"type": "pong"}


def test_a_successful_turn_streams_through_to_done(ws, monkeypatch):
    async def turn(body, user, conn, send_fn=None):
        await send_fn({"type": "done"})

    monkeypatch.setattr(chat_router, "process_message", turn)
    ws.send_json({"type": "message", "message": "hi"})
    assert ws.receive_json()["type"] == "done"
