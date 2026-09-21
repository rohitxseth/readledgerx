"""
Tests for the chat tool helpers that carry book identity between turns.

These are the seam behind the edition-mismatch bug: search results have to
survive into the next turn, and action buttons have to name the volume they
refer to rather than just its title.
"""

import pytest

from app.chat import tools
from app.chat.tools import (
    _book_ref,
    _compact_search_results,
    _is_non_specific_query,
    _preferred_volume_id,
    _recent_results,
)
from app.services.book_service import BookService
from tests.conftest import FakeBookRepository, FakeSearchClient, make_book


class _NoOpIntelligence:
    async def normalize_query(self, raw_query):
        return None

    async def select_best_match(self, raw_query, results):
        return results[0] if results else None


# ---------------------------------------------------------------------------
# _compact_search_results — what gets stored in session metadata
# ---------------------------------------------------------------------------

def test_compact_truncates_long_descriptions():
    """Descriptions are the only unbounded field, so they're capped not dropped."""
    book = make_book(title="Dune")
    book.description = "x" * 5000

    [compacted] = _compact_search_results([book])

    assert len(compacted["description"]) <= 1001  # cap plus the ellipsis
    assert compacted["description"].endswith("…")
    assert compacted["title"] == "Dune"
    assert compacted["google_books_id"] == book.google_books_id


def test_compact_keeps_short_descriptions_intact():
    """A book stored from a remembered result shouldn't lose its blurb."""
    book = make_book(title="Dune")
    book.description = "A desert planet."

    [compacted] = _compact_search_results([book])

    assert compacted["description"] == "A desert planet."


def test_compact_handles_missing_description():
    book = make_book(title="Dune")
    book.description = None
    assert _compact_search_results([book])[0]["description"] is None


def test_compact_caps_the_number_of_results():
    books = [make_book(title=f"Book {i}") for i in range(25)]
    assert len(_compact_search_results(books)) == 10


def test_compact_preserves_the_fields_tracking_needs():
    book = make_book(title="The Fountainhead", page_count=740)
    [compacted] = _compact_search_results([book])

    assert compacted["page_count"] == 740
    assert compacted["authors"] == book.authors
    assert compacted["id"] == str(book.id)


async def test_compacted_payload_round_trips_into_a_resolved_book():
    """The stored shape must be rebuildable, or the whole fix is inert."""
    shown = make_book(title="The Fountainhead", google_books_id="vol_740", page_count=740)
    repo = FakeBookRepository()
    service = BookService(
        repo=repo,
        search_client=FakeSearchClient(results=[]),
        intelligence=_NoOpIntelligence(),
    )

    stored = _compact_search_results([shown])
    result = await service.resolve_book("The Fountainhead", recent_results=stored)

    assert result is not None
    assert result.google_books_id == "vol_740"
    assert result.page_count == 740


# ---------------------------------------------------------------------------
# _recent_results — reading them back off the tool context
# ---------------------------------------------------------------------------

def test_recent_results_read_from_metadata():
    ctx = {"metadata": {"recent_search_results": [{"title": "Dune"}]}}
    assert _recent_results(ctx) == [{"title": "Dune"}]


def test_recent_results_default_to_empty():
    assert _recent_results(None) == []
    assert _recent_results({}) == []
    assert _recent_results({"metadata": {}}) == []
    assert _recent_results({"metadata": None}) == []


def test_recent_results_tolerate_bad_shapes():
    """Metadata is user-adjacent JSON; a wrong type must not crash a turn."""
    assert _recent_results({"metadata": "not a dict"}) == []
    assert _recent_results({"metadata": {"recent_search_results": "nope"}}) == []


# ---------------------------------------------------------------------------
# Action button payloads
# ---------------------------------------------------------------------------

def test_book_ref_pins_the_volume_id():
    book = make_book(title="Dune", google_books_id="vol_dune")
    assert _book_ref(book) == {"book_title": "Dune", "google_books_id": "vol_dune"}


def test_book_ref_omits_missing_volume_id():
    book = make_book(title="Dune", google_books_id=None)
    assert _book_ref(book) == {"book_title": "Dune"}


def test_preferred_volume_id_read_from_clicked_action():
    args = {
        "book_title": "Dune",
        "action_data": {"action": "log_reading", "payload": {"google_books_id": "vol_dune"}},
    }
    assert _preferred_volume_id(args) == "vol_dune"


def test_preferred_volume_id_absent_without_an_action():
    assert _preferred_volume_id({"book_title": "Dune"}) is None
    assert _preferred_volume_id({}) is None
    assert _preferred_volume_id(None) is None
    assert _preferred_volume_id({"action_data": {"payload": {}}}) is None


def test_button_payload_feeds_preferred_volume_id():
    """The payload a button emits is the payload a click hands back."""
    book = make_book(title="Dune", google_books_id="vol_dune")
    clicked = {"action_data": {"action": "log_reading", "payload": _book_ref(book)}}
    assert _preferred_volume_id(clicked) == "vol_dune"


# ---------------------------------------------------------------------------
# search_books guard — the backstop behind the router's recommendation intercept
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "recommended",            # the literal query the agent was seen sending
    "bestsellers",            # what it sent for "any good books?"
    "good books",
    "something to read",
    "Best Books",
    "recommended books for me",
])
def test_filler_only_queries_are_non_specific(query):
    assert _is_non_specific_query(query)


@pytest.mark.parametrize("query", [
    "sci-fi",
    "fiction",                # a genre is a real search, even though the agent
    "science fiction",        # also invents it for recommendations
    "Ayn Rand",
    "stoicism",
    "best sci-fi books",      # one real word is enough
    "harry potter",
    "books recommended by Bill Gates",
])
def test_queries_that_name_something_are_specific(query):
    assert not _is_non_specific_query(query)


def _patch_search(monkeypatch, results):
    """Route execute_search_books at a fake client via the composition root."""
    client = FakeSearchClient(results=results)
    service = BookService(
        repo=FakeBookRepository(), search_client=client, intelligence=_NoOpIntelligence()
    )
    monkeypatch.setattr(tools, "get_book_service", lambda conn: service)
    return client


async def test_non_specific_search_declines_without_hitting_the_catalogue(monkeypatch):
    client = _patch_search(monkeypatch, results=[make_book(title="WHO Guidelines")])

    result = await tools.execute_search_books({"query": "recommended"}, {"conn": None})

    assert client.last_query is None  # Google Books never called
    assert [el["type"] for el in result["elements"]] == ["text", "action_buttons"]
    assert "can't recommend" in result["elements"][0]["content"]
    assert result["metadata_updates"] == {}  # nothing remembered as "shown"


@pytest.mark.parametrize("query, search_by", [
    ("sci-fi", None),
    ("Ayn Rand", "author"),
    ("stoicism", None),
])
async def test_genuine_searches_still_return_results(monkeypatch, query, search_by):
    found = make_book(title="A Real Result")
    client = _patch_search(monkeypatch, results=[found])

    result = await tools.execute_search_books(
        {"query": query, "search_by": search_by}, {"conn": None}
    )

    assert client.last_query == query
    book_lists = [el for el in result["elements"] if el["type"] == "book_list"]
    assert book_lists and book_lists[0]["books"][0]["title"] == "A Real Result"
    assert result["metadata_updates"]["recent_search_results"]


@pytest.mark.parametrize("query", ["", "   ", "??"])
def test_queries_without_words_are_not_treated_as_filler(query):
    """Blank isn't a recommendation request; the service rejects it instead."""
    assert not _is_non_specific_query(query)
