"""Shared fixtures and fake implementations for testing.

The fakes here satisfy the Protocol interfaces via structural typing —
no inheritance from the production classes. That's the whole point of
using Protocol instead of ABC.
"""

import os

# Settings refuses to start without a real JWT_SECRET_KEY (see app/config/settings.py).
# Tests must not depend on a developer's .env, so supply a throwaway value here —
# before any app module is imported. It is never used to sign anything real.
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-used-in-production-0123456789")

import uuid
from datetime import datetime, timezone
from app.schemas.models import Book, User, ReadingSession, BookProgress


# ---------------------------------------------------------------------------
# Fake repositories
# ---------------------------------------------------------------------------

class FakeBookRepository:
    """In-memory book store. Satisfies IBookRepository structurally."""

    def __init__(self, books: list[Book] | None = None):
        self._books: dict[uuid.UUID, Book] = {}
        self._by_title: dict[str, Book] = {}
        self._by_volume_id: dict[str, Book] = {}
        for b in (books or []):
            self._index(b)

    def _index(self, book: Book):
        self._books[book.id] = book
        self._by_title[book.title.lower()] = book
        if book.google_books_id:
            self._by_volume_id[book.google_books_id] = book

    async def get_by_id(self, book_id: uuid.UUID) -> Book | None:
        return self._books.get(book_id)

    async def get_by_title(self, title: str) -> Book | None:
        # simple substring match, same logic as the real repo
        lower = title.lower()
        for key, book in self._by_title.items():
            if lower in key:
                return book
        return None

    async def get_by_google_volume_id(self, google_volume_id: str) -> Book | None:
        return self._by_volume_id.get(google_volume_id)

    async def create(self, book: Book) -> Book:
        self._index(book)
        return book


class FakeSearchClient:
    """Returns canned results. Satisfies IBookSearchClient structurally."""

    def __init__(self, results: list[Book] | None = None):
        self.results = results or []
        self.last_query = None

    async def search_books(self, query: str, search_by=None, max_results=10) -> list[Book]:
        self.last_query = query
        return self.results


class FakeReadingRepository:
    """Tracks sessions in memory. Satisfies IReadingRepository structurally."""

    def __init__(self):
        self._sessions: list[ReadingSession] = []

    async def create_session(self, user_id, book_id, pages_read, session_date=None):
        s = ReadingSession(
            id=uuid.uuid4(),
            user_id=user_id,
            book_id=book_id,
            pages_read=pages_read,
            session_date=session_date or datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        self._sessions.append(s)
        return s

    async def get_book_progress(self, user_id, book_id) -> BookProgress | None:
        total = sum(
            s.pages_read for s in self._sessions
            if s.user_id == user_id and s.book_id == book_id
        )
        if total == 0 and not any(
            s.user_id == user_id and s.book_id == book_id for s in self._sessions
        ):
            return None
        return BookProgress(
            book_id=book_id,
            title="Test Book",
            authors=["Author"],
            total_pages=300,
            pages_read=total,
            progress_percentage=round((total / 300) * 100, 2),
            last_read_date=datetime.now(timezone.utc),
        )

    async def get_all_progress(self, user_id) -> list[BookProgress]:
        book_ids = {s.book_id for s in self._sessions if s.user_id == user_id}
        results = []
        for bid in book_ids:
            p = await self.get_book_progress(user_id, bid)
            if p:
                results.append(p)
        return results

    async def reduce_reading_progress(self, user_id, book_id, pages_to_reduce, session_date=None):
        return {"pages_reduced": pages_to_reduce, "sessions_deleted": 0}

    async def set_reading_progress(self, user_id, book_id, target_pages, session_date=None):
        return {"action": "set", "pages": target_pages}

    async def remove_book_tracking(self, user_id, book_id) -> int:
        before = len(self._sessions)
        self._sessions = [
            s for s in self._sessions
            if not (s.user_id == user_id and s.book_id == book_id)
        ]
        return before - len(self._sessions)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_book(**overrides) -> Book:
    """Quick book factory for tests."""
    defaults = {
        "id": uuid.uuid4(),
        "title": "Dune",
        "authors": ["Frank Herbert"],
        "page_count": 412,
        "published_date": "1965",
        "google_books_id": f"vol_{uuid.uuid4().hex[:8]}",
    }
    defaults.update(overrides)
    return Book(**defaults)


def make_user(**overrides) -> User:
    defaults = {
        "id": uuid.uuid4(),
        "email": "test@example.com",
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return User(**defaults)
