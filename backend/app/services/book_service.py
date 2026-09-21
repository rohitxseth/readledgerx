import logging

from pydantic import ValidationError

from app.core.exceptions import BookResolutionError, BusinessLogicError
from app.interfaces.client_interfaces import IBookSearchClient
from app.interfaces.repository_interfaces import IBookRepository
from app.schemas.models import Book
from app.services.book_intelligence import BookIntelligenceService

logger = logging.getLogger(__name__)

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
                raise BookResolutionError(f"No book found with volume id '{volume_id}'.")
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
        if book is None:
            return None
        logger.info("Storing book fetched by volume id: '%s' (%s)", book.title, volume_id)
        return await self.repo.create(book)

    async def resolve_book(
        self,
        title: str,
        recent_results: list[dict] | None = None,
    ) -> Book | None:
        if recent_results:
            matched = self._match_recent_result(title, recent_results)
            if matched:
                book = await self._book_from_recent_result(matched)
                if book:
                    logger.info(
                        "Book resolved from recent search results: '%s' (volume %s)",
                        book.title,
                        book.google_books_id,
                    )
                    return book

        existing_book = await self.repo.get_by_title(title)
        if existing_book:
            logger.info(f"Book found in database (exact): '{existing_book.title}'")
            return existing_book

        logger.info(f"Normalizing query: '{title}'")
        normalized = await self.intelligence.normalize_query(title)

        search_query = title
        if normalized:
            if not normalized.is_valid_book_query:
                logger.warning(f"Query '{title}' deemed invalid by LLM. Aborting search.")
                return None
            search_query = normalized.normalized_query
            logger.info(f"Query normalized to: '{search_query}'")

            if search_query != title:
                existing_book_norm = await self.repo.get_by_title(search_query)
                if existing_book_norm:
                    logger.info(f"Book found in database (normalized): '{existing_book_norm.title}'")
                    return existing_book_norm

        logger.info(f"Book not in database, searching external catalogue: '{search_query}'")

        google_books = await self.search_client.search_books(search_query, max_results=5)
        if not google_books:
            logger.warning(f"No books found for: '{search_query}'")
            return None

        best_book = await self.intelligence.select_best_match(title, google_books)
        if not best_book:
            logger.warning(f"LLM could not find a good match for: '{title}'")
            return None

        existing_by_volume_id = await self.repo.get_by_google_volume_id(
            best_book.google_books_id
        )
        if existing_by_volume_id:
            logger.info(
                f"Book already exists in database by volume ID: '{existing_by_volume_id.title}'"
            )
            return existing_by_volume_id

        logger.info(f"Saving book to database: '{best_book.title}'")
        saved_book = await self.repo.create(best_book)
        logger.info(f"Book saved successfully: '{saved_book.title}' (ID: {saved_book.id})")
        return saved_book

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
            r for r in recent_results
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
