from pydantic import ValidationError

from app.core.exceptions import BookResolutionError, BusinessLogicError
from app.interfaces.client_interfaces import IBookSearchClient
from app.interfaces.repository_interfaces import IBookRepository
from app.schemas.models import Book
from app.services.book_intelligence import BookIntelligenceService

# A query that is only part of a remembered title must cover most of it, so
# "Dune" doesn't match a remembered "Dune Messiah".
_MIN_QUERY_TITLE_RATIO = 0.6


class BookService:
    def __init__(
        self,
        repo: IBookRepository,
        search_client: IBookSearchClient,
        intelligence: BookIntelligenceService,
    ):
        self.repo = repo
        self.search_client = search_client
        self.intelligence = intelligence

    async def search(
        self, query: str, search_by: str | None = None, max_results: int = 10
    ) -> list[Book]:
        if not (query or "").strip():
            raise BusinessLogicError("Give something to search for.")
        return await self.search_client.search_books(
            query.strip(), search_by=search_by, max_results=max_results
        )

    async def resolve(
        self,
        title: str | None = None,
        *,
        volume_id: str | None = None,
        recent_results: list[dict] | None = None,
    ) -> Book:
        if volume_id:
            book = await self.resolve_by_volume_id(volume_id)
            if book:
                return book
            if not title:
                raise BookResolutionError(
                    f"No book found with volume id '{volume_id}'."
                )
        if title:
            book = await self.resolve_book(title, recent_results=recent_results)
            if book:
                return book
            raise BookResolutionError(f"Couldn't find a book matching '{title}'.")
        raise BookResolutionError("Name a book by title or volume id.")

    async def resolve_by_volume_id(self, volume_id: str) -> Book | None:
        existing = await self.repo.get_by_google_volume_id(volume_id)
        if existing:
            return existing
        book = await self.search_client.get_volume(volume_id)
        return await self.repo.create(book) if book else None

    async def resolve_book(
        self, title: str, recent_results: list[dict] | None = None
    ) -> Book | None:
        # Stage 0: a book the user was just shown resolves to that exact volume,
        # so the edition (and page count) can't change between search and track.
        if recent_results:
            matched = self._match_recent_result(title, recent_results)
            if matched:
                book = await self._book_from_recent_result(matched)
                if book:
                    return book

        existing = await self.repo.get_by_title(title)
        if existing:
            return existing

        normalized = await self.intelligence.normalize_query(title)
        search_query = title
        if normalized:
            if not normalized.is_valid_book_query:
                return None
            search_query = normalized.normalized_query
            if search_query != title:
                existing = await self.repo.get_by_title(search_query)
                if existing:
                    return existing

        results = await self.search_client.search_books(search_query, max_results=5)
        if not results:
            return None

        best = await self.intelligence.select_best_match(title, results)
        if not best:
            return None

        # Deduplicate on volume id, not title: differently phrased lookups of
        # the same book converge on one row.
        existing = await self.repo.get_by_google_volume_id(best.google_books_id)
        if existing:
            return existing
        return await self.repo.create(best)

    @staticmethod
    def _match_recent_result(title: str, recent_results: list[dict]) -> dict | None:
        query = title.strip().lower()
        if not query:
            return None

        def shown(result: dict) -> str:
            return (result.get("title") or "").strip().lower()

        for result in recent_results:
            if shown(result) == query:
                return result

        contained = [r for r in recent_results if shown(r) and shown(r) in query]
        if contained:
            return max(contained, key=lambda r: len(shown(r)))

        partial = [
            r
            for r in recent_results
            if shown(r)
            and query in shown(r)
            and len(query) / len(shown(r)) >= _MIN_QUERY_TITLE_RATIO
        ]
        if partial:
            return min(partial, key=lambda r: len(shown(r)))

        return None

    async def _book_from_recent_result(self, data: dict) -> Book | None:
        volume_id = data.get("google_books_id")
        if not volume_id:
            return None

        existing = await self.repo.get_by_google_volume_id(volume_id)
        if existing:
            return existing

        try:
            book = Book(**data)
        except ValidationError:
            return None
        return await self.repo.create(book)
