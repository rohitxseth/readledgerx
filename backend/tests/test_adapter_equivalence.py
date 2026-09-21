"""
The chat agent and the REST API are two adapters over the same services.

Every test runs one operation twice — through a REST route and through the
agent's tool — each against an identical, fresh set of in-memory fakes, and
checks three things:

  1. both adapters called the same service operation(s),
  2. both left the domain in the same state,
  3. both returned the same result (the agent's progress card carries the
     exact JSON the REST route returns).

Nothing here touches a database, the network, or the LLM.
"""

import inspect

import httpx
import pytest

from app.chat import tools
from app.core.dependencies import (
    get_book_service,
    get_current_user,
    get_reading_service,
)
from app.main import app
from app.services.book_service import BookService
from app.services.reading_service import ReadingService
from tests.conftest import (
    FakeBookRepository,
    FakeReadingRepository,
    FakeSearchClient,
    make_book,
    make_user,
)

# Module-level, so every world shares the same ids and outcomes are comparable.
DUNE = make_book(title="Dune", google_books_id="vol_dune", page_count=412)
HOBBIT = make_book(title="The Hobbit", google_books_id="vol_hobbit", page_count=300)
SAPIENS = make_book(title="Sapiens", google_books_id="vol_sapiens", page_count=400)
USER = make_user()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class _Spy:
    """Wraps a service and records the public operations an adapter calls.

    Only calls made through the wrapper are seen — the adapter's calls. When a
    service calls its own methods it goes through `self`, so those stay
    invisible, which is exactly the adapter/service boundary under test.
    """

    def __init__(self, target):
        self._target = target
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        attr = getattr(self._target, name)
        if name.startswith("_") or not inspect.iscoroutinefunction(attr):
            return attr

        async def recorded(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return await attr(*args, **kwargs)

        return recorded

    @property
    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]


class _NoOpIntelligence:
    async def normalize_query(self, raw_query):
        return None

    async def select_best_match(self, raw_query, results):
        return results[0] if results else None


class World:
    """One fresh, identical set of fakes and services."""

    def __init__(self, stored=(DUNE, HOBBIT, SAPIENS), catalogue=(DUNE, HOBBIT, SAPIENS)):
        self.book_repo = FakeBookRepository(books=list(stored))
        self.search_client = FakeSearchClient(results=list(catalogue))
        self.reading_repo = FakeReadingRepository(
            page_counts={b.id: b.page_count for b in catalogue},
            titles={b.id: b.title for b in catalogue},
        )
        self.books = _Spy(BookService(self.book_repo, self.search_client, _NoOpIntelligence()))
        self.reading = _Spy(ReadingService(self.reading_repo, self.book_repo))

    async def seed(self, book, pages):
        """Set up state without it counting as an adapter call."""
        await self.reading._target.add_reading_session(USER.id, book.id, pages)

    def state(self):
        """Domain state with no per-run randomness, so worlds are comparable."""
        sessions = sorted((str(s.book_id), s.pages_read) for s in self.reading_repo._sessions)
        stored = sorted(b.google_books_id for b in self.book_repo._books.values())
        return sessions, stored


async def via_rest(world: World, method: str, url: str, **kwargs) -> httpx.Response:
    app.dependency_overrides = {
        get_current_user: lambda: USER,
        get_book_service: lambda: world.books,
        get_reading_service: lambda: world.reading,
    }
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)
    finally:
        app.dependency_overrides = {}


async def via_agent(world: World, monkeypatch, tool: str, args: dict) -> dict:
    monkeypatch.setattr(tools, "get_book_service", lambda conn: world.books)
    monkeypatch.setattr(tools, "get_reading_service", lambda conn: world.reading)
    context = {"conn": None, "user": USER, "session_id": "s1", "metadata": {}}
    return await tools.execute_tool(tool, args, context)


def _of_type(result: dict, element_type: str) -> list[dict]:
    return [el for el in result["elements"] if el["type"] == element_type]


def card(result: dict) -> dict:
    """The progress card the agent rendered — the JSON it carries."""
    return _of_type(result, "book_progress")[0]["data"]


def text(result: dict) -> str:
    return " ".join(el["content"] for el in _of_type(result, "text"))


# ---------------------------------------------------------------------------
# GET /books/search  ==  search_books
# ---------------------------------------------------------------------------

async def test_search(monkeypatch):
    rest_world, agent_world = World(), World()

    r = await via_rest(rest_world, "GET", "/books/search", params={"q": "Dune"})
    a = await via_agent(agent_world, monkeypatch, "search_books", {"query": "Dune"})

    assert r.status_code == 200
    assert rest_world.books.calls == agent_world.books.calls == [
        ("search", ("Dune",), {"search_by": None})
    ]
    assert [b["title"] for b in r.json()] == [b["title"] for b in _of_type(a, "book_list")[0]["books"]]


async def test_search_rejects_an_empty_query_with_the_same_message(monkeypatch):
    rest_world, agent_world = World(), World()

    r = await via_rest(rest_world, "GET", "/books/search", params={"q": "  "})
    a = await via_agent(agent_world, monkeypatch, "search_books", {"query": "  "})

    assert r.status_code == 400
    assert r.json()["detail"] == text(a) == "Give something to search for."


# ---------------------------------------------------------------------------
# POST /books/track  ==  start_tracking
# ---------------------------------------------------------------------------

async def test_track_by_title(monkeypatch):
    rest_world, agent_world = World(stored=()), World(stored=())

    r = await via_rest(rest_world, "POST", "/books/track", json={"title": "Dune"})
    a = await via_agent(agent_world, monkeypatch, "start_tracking", {"book_title": "Dune"})

    assert r.status_code == 200
    assert rest_world.books.names == agent_world.books.names == ["resolve"]
    assert rest_world.reading.calls == agent_world.reading.calls == [
        ("start_tracking", (USER.id, DUNE.id), {"pages": 0})
    ]
    assert rest_world.state() == agent_world.state() == ([(str(DUNE.id), 0)], ["vol_dune"])
    assert r.json()["created"] is True
    assert r.json()["progress"] == card(a)


async def test_track_by_volume_id(monkeypatch):
    """REST sends the id from a search; the agent's button carries the same id.

    The volume isn't stored yet, so both must fetch that exact volume rather
    than re-resolving the title and risking another edition.
    """
    rest_world, agent_world = World(stored=()), World(stored=())

    r = await via_rest(rest_world, "POST", "/books/track", json={"google_volume_id": "vol_hobbit"})
    a = await via_agent(agent_world, monkeypatch, "start_tracking", {
        "book_title": "The Hobbit",
        "action_data": {"action": "start_tracking", "payload": {"google_books_id": "vol_hobbit"}},
    })

    assert r.status_code == 200
    rest_resolve, agent_resolve = rest_world.books.calls[0], agent_world.books.calls[0]
    assert rest_resolve[2]["volume_id"] == agent_resolve[2]["volume_id"] == "vol_hobbit"
    assert rest_world.search_client.last_volume_id == agent_world.search_client.last_volume_id == "vol_hobbit"
    assert rest_world.state() == agent_world.state()
    assert r.json()["progress"] == card(a)


async def test_tracking_twice_is_idempotent_in_both(monkeypatch):
    rest_world, agent_world = World(), World()
    await rest_world.seed(DUNE, 0)
    await agent_world.seed(DUNE, 0)

    r = await via_rest(rest_world, "POST", "/books/track", json={"title": "Dune"})
    a = await via_agent(agent_world, monkeypatch, "start_tracking", {"book_title": "Dune"})

    assert r.json()["created"] is False
    assert "already tracking" in text(a)
    assert rest_world.state() == agent_world.state() == ([(str(DUNE.id), 0)], sorted(["vol_dune", "vol_hobbit", "vol_sapiens"]))


# ---------------------------------------------------------------------------
# POST /reading/log  ==  log_reading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("amount, expected_pages", [
    ({"pages": 40}, 40),
    ({"percentage": 25}, 103),      # int(0.25 * 412) — the conversion now lives in the service
])
async def test_log(monkeypatch, amount, expected_pages):
    rest_world, agent_world = World(), World()

    r = await via_rest(rest_world, "POST", "/reading/log", json={"title": "Dune", **amount})
    a = await via_agent(agent_world, monkeypatch, "log_reading", {"book_title": "Dune", **amount})

    assert r.status_code == 200
    assert rest_world.books.names == agent_world.books.names == ["resolve"]
    assert rest_world.reading.calls == agent_world.reading.calls == [(
        "log_reading", (USER.id, DUNE.id),
        {"action": "add", "pages": amount.get("pages"), "percentage": amount.get("percentage"), "session_date": None},
    )]
    assert rest_world.state() == agent_world.state()
    assert r.json()["pages"] == expected_pages
    assert r.json()["progress"] == card(a)


@pytest.mark.parametrize("body, status, message", [
    ({"pages": 500}, 400, "'Dune' only has 412 pages left (0/412 read). Try logging 412 pages instead."),
    ({}, 400, "How many pages? Give a page count or a percentage."),
    ({"percentage": 150}, 400, "A percentage must be between 0 and 100."),
    ({"pages": -5}, 400, "The number of pages can't be negative."),
    ({"action": "reduce", "pages": 5}, 400, "No pages have been logged for 'Dune' yet."),
])
async def test_log_rule_violations_are_identical(monkeypatch, body, status, message):
    """One rule, one message — whether it surfaces as an HTTP error or a chat reply."""
    rest_world, agent_world = World(), World()

    r = await via_rest(rest_world, "POST", "/reading/log", json={"title": "Dune", **body})
    a = await via_agent(agent_world, monkeypatch, "log_reading", {"book_title": "Dune", **body})

    assert r.status_code == status
    assert r.json()["detail"] == text(a) == message
    assert rest_world.state() == agent_world.state()  # nothing was written in either


async def test_unknown_book_is_a_404_and_a_not_found_reply(monkeypatch):
    rest_world, agent_world = World(stored=(), catalogue=()), World(stored=(), catalogue=())

    r = await via_rest(rest_world, "POST", "/reading/log", json={"title": "Nonexistent", "pages": 5})
    a = await via_agent(agent_world, monkeypatch, "log_reading", {"book_title": "Nonexistent", "pages": 5})

    assert r.status_code == 404
    assert rest_world.books.names == agent_world.books.names == ["resolve"]
    assert rest_world.reading.calls == agent_world.reading.calls == []
    assert "couldn't find a book" in text(a).lower()


# ---------------------------------------------------------------------------
# DELETE /reading/last  ==  undo_last_log
# ---------------------------------------------------------------------------

async def test_undo_last_log(monkeypatch):
    rest_world, agent_world = World(), World()
    for world in (rest_world, agent_world):
        await world.seed(DUNE, 40)
        await world.seed(HOBBIT, 25)      # the newest entry — the one undone

    r = await via_rest(rest_world, "DELETE", "/reading/last")
    a = await via_agent(agent_world, monkeypatch, "undo_last_log", {})

    assert r.status_code == 200
    assert rest_world.reading.calls == agent_world.reading.calls == [("undo_last_log", (USER.id,), {})]
    assert rest_world.state() == agent_world.state() == ([(str(DUNE.id), 40)], sorted(["vol_dune", "vol_hobbit", "vol_sapiens"]))
    assert r.json()["session"]["pages_read"] == 25
    assert "25 pages" in text(a) and "The Hobbit" in text(a)


async def test_nothing_to_undo(monkeypatch):
    rest_world, agent_world = World(), World()

    r = await via_rest(rest_world, "DELETE", "/reading/last")
    a = await via_agent(agent_world, monkeypatch, "undo_last_log", {})

    assert r.status_code == 404
    assert r.json()["detail"] == text(a) == "There's nothing to undo — no reading has been logged yet."


# ---------------------------------------------------------------------------
# GET /progress  ==  show_progress
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    {"sort_by": "pages_read", "limit": 1},
    {"sort_by": "percent_complete", "filter": "in_progress", "limit": 1},
    {"sort_by": "last_read"},
    {},
])
async def test_progress(monkeypatch, query):
    rest_world, agent_world = World(), World()
    for world in (rest_world, agent_world):
        await world.seed(DUNE, 300)       # most pages
        await world.seed(HOBBIT, 280)     # highest percentage (93%)
        await world.seed(SAPIENS, 50)     # logged last

    r = await via_rest(rest_world, "GET", "/progress", params=query)
    a = await via_agent(agent_world, monkeypatch, "show_progress", dict(query))

    assert r.status_code == 200
    assert rest_world.reading.calls == agent_world.reading.calls == [(
        "get_all_progress", (USER.id,),
        {"filter_by": query.get("filter"), "sort_by": query.get("sort_by"), "limit": query.get("limit")},
    )]
    agent_books = [card(a)] if _of_type(a, "book_progress") else _of_type(a, "book_list")[0]["books"]
    assert r.json() == agent_books


# ---------------------------------------------------------------------------
# The REST routes enforce JWT auth, like the chat endpoints
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method, url, kwargs", [
    ("GET", "/books/search", {"params": {"q": "Dune"}}),
    ("POST", "/books/track", {"json": {"title": "Dune"}}),
    ("POST", "/reading/log", {"json": {"title": "Dune", "pages": 5}}),
    ("DELETE", "/reading/last", {}),
    ("GET", "/progress", {}),
])
async def test_routes_require_a_token(method, url, kwargs):
    world = World()
    app.dependency_overrides = {
        get_book_service: lambda: world.books,
        get_reading_service: lambda: world.reading,
    }
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.request(method, url, **kwargs)
    finally:
        app.dependency_overrides = {}

    assert r.status_code in (401, 403)
    assert world.books.calls == world.reading.calls == []
