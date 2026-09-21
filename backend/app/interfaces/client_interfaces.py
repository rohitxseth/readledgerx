from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.models import Book


@runtime_checkable
class IBookSearchClient(Protocol):
    async def search_books(
        self,
        query: str,
        search_by: str | None = None,
        max_results: int = 10,
    ) -> list[Book]: ...

    async def get_volume(self, volume_id: str) -> Book | None: ...
