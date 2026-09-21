import uuid
import pytest

from app.services.book_service import BookService
from app.services.book_intelligence import BookIntelligenceService
from tests.conftest import FakeBookRepository, FakeSearchClient, make_book


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(repo=None, search=None):
    """Wire a BookService with fake deps. No DB, no HTTP."""
    return BookService(
        repo=repo or FakeBookRepository(),
        search_client=search or FakeSearchClient(),
        intelligence=_NoOpIntelligence(),
    )


class _NoOpIntelligence:
    """Intelligence that does nothing — skips LLM calls in unit tests."""

    async def normalize_query(self, raw_query: str):
        return None  # tells BookService to use the raw query as-is

    async def select_best_match(self, raw_query, results):
        return results[0] if results else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_returns_cached_book_without_hitting_search():
    """If the book is already in the DB, the search client is never called."""
    existing = make_book(title="Dune")
    repo = FakeBookRepository(books=[existing])
    search = FakeSearchClient(results=[])  # would return nothing if called

    service = _make_service(repo=repo, search=search)
    result = await service.resolve_book("Dune")

    assert result is not None
    assert result.title == "Dune"
    assert search.last_query is None  # search was never called


async def test_falls_back_to_search_when_not_in_db():
    """Cache miss → search client is called with the query."""
    remote_book = make_book(title="The Hobbit", google_books_id="abc123")
    search = FakeSearchClient(results=[remote_book])

    service = _make_service(search=search)
    result = await service.resolve_book("The Hobbit")

    assert result is not None
    assert result.title == "The Hobbit"
    assert search.last_query == "The Hobbit"


async def test_saves_book_to_db_after_search():
    """After finding a book via search, it gets persisted so the next lookup hits cache."""
    remote_book = make_book(title="Atomic Habits")
    repo = FakeBookRepository()
    search = FakeSearchClient(results=[remote_book])

    service = _make_service(repo=repo, search=search)
    await service.resolve_book("Atomic Habits")

    # should now be in the repo
    cached = await repo.get_by_title("Atomic Habits")
    assert cached is not None


async def test_returns_none_when_search_finds_nothing():
    """No DB hit + empty search results → None, not an exception."""
    service = _make_service(search=FakeSearchClient(results=[]))
    result = await service.resolve_book("xyzzy nonsense query 12345")
    assert result is None


async def test_deduplication_by_volume_id():
    """If search returns a book that's already in DB by volume_id, don't create a duplicate."""
    volume_id = "gbooks_vol_999"
    existing = make_book(title="Sapiens", google_books_id=volume_id)
    repo = FakeBookRepository(books=[existing])

    # search returns the same book (by volume_id), but with a slightly different title
    remote = make_book(title="Sapiens: A Brief History", google_books_id=volume_id)
    search = FakeSearchClient(results=[remote])

    service = _make_service(repo=repo, search=search)
    result = await service.resolve_book("Sapiens")

    # should return the already-stored version, not create a new row
    assert result.title == "Sapiens"
    assert len(repo._books) == 1


# ---------------------------------------------------------------------------
# Resolving against results the user was just shown
#
# Regression cover for the edition-mismatch bug: searching "ayn rand" showed
# The Fountainhead at 740 pages, but then typing "The Fountainhead" re-ran the
# whole pipeline against a normalized query and tracked a 754-page volume.
# ---------------------------------------------------------------------------

def _as_shown(book):
    """A book payload as execute_search_books stores it in session metadata."""
    data = book.model_dump(mode="json")
    data.pop("description", None)
    return data


async def test_recent_result_wins_over_pipeline():
    """A title naming a shown result resolves to that volume, not a fresh search."""
    shown = make_book(title="The Fountainhead", google_books_id="vol_740", page_count=740)
    different_edition = make_book(
        title="The Fountainhead", google_books_id="vol_754", page_count=754
    )
    search = FakeSearchClient(results=[different_edition])

    service = _make_service(search=search)
    result = await service.resolve_book(
        "The Fountainhead", recent_results=[_as_shown(shown)]
    )

    assert result.google_books_id == "vol_740"
    assert result.page_count == 740
    assert search.last_query is None  # the pipeline never ran


async def test_recent_result_matches_case_insensitive_partial_title():
    """Users retype titles loosely; "fountainhead" should still match."""
    shown = make_book(title="The Fountainhead", google_books_id="vol_740", page_count=740)
    service = _make_service(search=FakeSearchClient(results=[]))

    result = await service.resolve_book("fountainhead", recent_results=[_as_shown(shown)])

    assert result is not None
    assert result.google_books_id == "vol_740"


async def test_recent_result_matches_when_query_is_longer_than_title():
    """"The Fountainhead by Ayn Rand" should match the shown "The Fountainhead"."""
    shown = make_book(title="The Fountainhead", google_books_id="vol_740")
    service = _make_service(search=FakeSearchClient(results=[]))

    result = await service.resolve_book(
        "The Fountainhead by Ayn Rand", recent_results=[_as_shown(shown)]
    )

    assert result is not None
    assert result.google_books_id == "vol_740"


async def test_recent_result_persists_new_volume():
    """A shown book that isn't stored yet gets created, once."""
    shown = make_book(title="The Fountainhead", google_books_id="vol_740", page_count=740)
    repo = FakeBookRepository()

    service = _make_service(repo=repo)
    result = await service.resolve_book(
        "The Fountainhead", recent_results=[_as_shown(shown)]
    )

    assert result.google_books_id == "vol_740"
    assert len(repo._books) == 1


async def test_recent_result_reuses_stored_volume_without_duplicating():
    """If that volume is already stored, return the stored row."""
    stored = make_book(title="The Fountainhead", google_books_id="vol_740", page_count=740)
    repo = FakeBookRepository(books=[stored])
    shown = make_book(title="The Fountainhead", google_books_id="vol_740", page_count=740)

    service = _make_service(repo=repo)
    result = await service.resolve_book(
        "The Fountainhead", recent_results=[_as_shown(shown)]
    )

    assert result.id == stored.id
    assert len(repo._books) == 1


async def test_unrelated_recent_results_fall_back_to_pipeline():
    """Recent results for other books must not hijack an unrelated title."""
    shown = make_book(title="Letters of Ayn Rand", google_books_id="vol_letters")
    found = make_book(title="Dune", google_books_id="vol_dune")
    search = FakeSearchClient(results=[found])

    service = _make_service(search=search)
    result = await service.resolve_book("Dune", recent_results=[_as_shown(shown)])

    assert result.google_books_id == "vol_dune"
    assert search.last_query == "Dune"  # pipeline did run


async def test_id_only_recent_entry_falls_back_when_volume_unknown():
    """A button payload carrying only an unknown id must not crash or win.

    _resolve_book prepends {"google_books_id": ..., "title": ...} for a clicked
    button. If that volume isn't stored, there isn't enough data to rebuild a
    Book, so resolution must fall through to the pipeline.
    """
    found = make_book(title="Dune", google_books_id="vol_dune")
    search = FakeSearchClient(results=[found])

    service = _make_service(search=search)
    result = await service.resolve_book(
        "Dune", recent_results=[{"google_books_id": "vol_never_seen", "title": "Dune"}]
    )

    assert result.google_books_id == "vol_dune"
    assert search.last_query == "Dune"


async def test_empty_recent_results_behave_like_before():
    """No recent results → unchanged behaviour."""
    found = make_book(title="Dune", google_books_id="vol_dune")
    search = FakeSearchClient(results=[found])

    service = _make_service(search=search)
    assert (await service.resolve_book("Dune", recent_results=[])).title == "Dune"
    assert (await service.resolve_book("Dune", recent_results=None)).title == "Dune"


async def test_recent_result_does_not_hijack_a_shorter_distinct_title():
    """Searching "Dune Messiah" must not capture a later question about "Dune".

    "Dune" is a substring of "Dune Messiah", but it names a different book.
    Stage 0 should decline and let the DB lookup answer.
    """
    real_dune = make_book(title="Dune", google_books_id="vol_dune")
    repo = FakeBookRepository(books=[real_dune])
    shown = make_book(title="Dune Messiah", google_books_id="vol_messiah")
    search = FakeSearchClient(results=[])

    service = _make_service(repo=repo, search=search)
    result = await service.resolve_book("Dune", recent_results=[_as_shown(shown)])

    assert result.google_books_id == "vol_dune"


async def test_recent_result_still_matches_a_substantial_partial_title():
    """The guard must not break "fountainhead" -> "The Fountainhead"."""
    shown = make_book(title="The Fountainhead", google_books_id="vol_740")
    service = _make_service(search=FakeSearchClient(results=[]))

    result = await service.resolve_book("fountainhead", recent_results=[_as_shown(shown)])
    assert result.google_books_id == "vol_740"


async def test_recent_result_prefers_the_most_specific_contained_title():
    """With both remembered, "Dune Messiah ..." should pick Dune Messiah."""
    dune = make_book(title="Dune", google_books_id="vol_dune")
    messiah = make_book(title="Dune Messiah", google_books_id="vol_messiah")
    service = _make_service(search=FakeSearchClient(results=[]))

    result = await service.resolve_book(
        "Dune Messiah by Frank Herbert",
        recent_results=[_as_shown(dune), _as_shown(messiah)],
    )
    assert result.google_books_id == "vol_messiah"


async def test_exact_match_beats_a_longer_remembered_title():
    dune = make_book(title="Dune", google_books_id="vol_dune")
    messiah = make_book(title="Dune Messiah", google_books_id="vol_messiah")
    service = _make_service(search=FakeSearchClient(results=[]))

    result = await service.resolve_book(
        "Dune", recent_results=[_as_shown(messiah), _as_shown(dune)]
    )
    assert result.google_books_id == "vol_dune"
