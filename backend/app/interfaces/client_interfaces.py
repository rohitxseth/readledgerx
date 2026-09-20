"""
External client interfaces (Protocols) for the ReadLedger domain.

WHY ABSTRACT THE EXTERNAL CLIENT?
----------------------------------
`GoogleBooksClient` makes real HTTP calls. If `BookService` directly
instantiates it, you cannot test `BookService` without hitting the network.

By depending on `IBookSearchClient`, we can:
  - Pass a `FakeBookSearchClient` in tests (no HTTP required)
  - Swap Google Books for OpenLibrary or any other API without changing
    `BookService` at all                                            → OCP

INTERVIEW TALKING POINT:
  "External I/O — HTTP, databases, file systems — are the hardest things to
   test. I wrap every external dependency behind a Protocol so my domain
   services stay pure and fast to test."
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.models import Book


@runtime_checkable
class IBookSearchClient(Protocol):
    """Contract for searching an external book catalogue."""

    async def search_books(
        self,
        query: str,
        search_by: str | None = None,
        max_results: int = 10,
    ) -> list[Book]:
        """
        Search for books matching *query*.

        Args:
            query:      Free-text search string (title, author, ISBN, etc.)
            search_by:  Optional scope filter — ``"title"`` or ``"author"``.
            max_results: Upper bound on returned results.

        Returns:
            A (possibly empty) list of :class:`~app.schemas.models.Book` objects.
        """
        ...
