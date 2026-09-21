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
