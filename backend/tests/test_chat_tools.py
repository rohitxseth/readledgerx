"""
Tests for the chat tool helpers that carry book identity between turns.

These are the seam behind the edition-mismatch bug: search results have to
survive into the next turn, and action buttons have to name the volume they
refer to rather than just its title.
"""

from app.chat.tools import (
    _book_ref,
    _compact_search_results,
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
