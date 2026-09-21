from typing import Protocol, runtime_checkable

from app.schemas.models import Book, NormalizedQuery


@runtime_checkable
class IBookSearchClient(Protocol):
    async def search_books(
        self,
        query: str,
        search_by: str | None = None,
        max_results: int = 10,
    ) -> list[Book]: ...

    async def get_volume(self, volume_id: str) -> Book | None: ...


@runtime_checkable
class IBookIntelligence(Protocol):
    async def normalize_query(self, raw_query: str) -> NormalizedQuery | None: ...

    async def select_best_match(
        self, raw_query: str, results: list[Book]
    ) -> Book | None: ...
