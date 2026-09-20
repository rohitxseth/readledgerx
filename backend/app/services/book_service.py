"""
BookService — orchestrates book resolution.
"""

import logging
from app.interfaces.repository_interfaces import IBookRepository
from app.interfaces.client_interfaces import IBookSearchClient
from app.services.book_intelligence import BookIntelligenceService
from app.schemas.models import Book

logger = logging.getLogger(__name__)


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

    async def resolve_book(self, title: str) -> Book | None:
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
