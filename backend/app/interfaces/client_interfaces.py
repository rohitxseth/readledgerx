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

    async def get_volume(self, volume_id: str) -> Book | None:
        """Fetch one exact volume by its catalogue id, or None if it doesn't exist.

        Needed to resolve a volume the caller already identified — a stateless
        REST client can't rely on the chat session remembering search results.
        """
        ...
