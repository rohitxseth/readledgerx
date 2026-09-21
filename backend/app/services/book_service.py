"""
BookService — orchestrates book resolution.
"""

import logging
from pydantic import ValidationError

from app.interfaces.repository_interfaces import IBookRepository
from app.interfaces.client_interfaces import IBookSearchClient
from app.services.book_intelligence import BookIntelligenceService
from app.schemas.models import Book

logger = logging.getLogger(__name__)

# How much of a remembered title a loose query must cover before it is treated
# as naming that book. "fountainhead" covers 75% of "The Fountainhead" (a
# match); "Dune" covers 33% of "Dune Messiah" (not a match).
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

    async def resolve_book(
        self,
        title: str,
        recent_results: list[dict] | None = None,
    ) -> Book | None:
        """Resolve *title* to a canonical Book.

        *recent_results* are book payloads the user was shown earlier in this
        conversation. When the title refers to one of them, that exact Google
        Books volume is used. Without this, typing the title of a book from a
        search result re-runs the whole pipeline against a different query and
        can land on a different edition with a different page count.
        """
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

            # Try DB again with normalized query if it changed
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

    # ------------------------------------------------------------------
    # Recent-result resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _match_recent_result(title: str, recent_results: list[dict]) -> dict | None:
        """Find the shown result the user most likely means, or None."""
        query = title.strip().lower()
        if not query:
            return None

        def shown(result: dict) -> str:
            return (result.get("title") or "").strip().lower()

        # 1. Exact title — unambiguous.
        for result in recent_results:
            if shown(result) == query:
                return result

        # 2. A shown title sitting inside a longer query:
        #    "The Fountainhead by Ayn Rand" -> "The Fountainhead".
        #    Prefer the longest such title, i.e. the most specific match.
        contained = [r for r in recent_results if shown(r) and shown(r) in query]
        if contained:
            return max(contained, key=lambda r: len(shown(r)))

        # 3. The query sitting inside a shown title ("fountainhead" ->
        #    "The Fountainhead"), but only when it covers most of that title.
        #    Without this guard, asking about "Dune" right after a search for
        #    "Dune Messiah" would resolve to the wrong book.
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
        """Return the stored Book for a shown result, persisting it if new."""
        volume_id = data.get("google_books_id")
        if not volume_id:
            return None

        existing = await self.repo.get_by_google_volume_id(volume_id)
        if existing:
            return existing

        try:
            book = Book(**data)
        except ValidationError:
            # Payload too sparse to rebuild (e.g. an action carrying only an id)
            # — fall through to the normal pipeline.
            return None
        return await self.repo.create(book)
