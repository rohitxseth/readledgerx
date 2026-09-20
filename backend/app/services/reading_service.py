"""ReadingService — business logic for reading sessions and progress."""

import uuid as uuid_module
import logging
from datetime import datetime

from app.interfaces.repository_interfaces import IReadingRepository, IBookRepository
from app.schemas.models import ReadingSession, BookProgress
from app.core.exceptions import ReadingLimitError

logger = logging.getLogger(__name__)


class ReadingService:
    def __init__(
        self,
        reading_repo: IReadingRepository,
        book_repo: IBookRepository,
    ):
        self.reading_repo = reading_repo
        self.book_repo = book_repo

    async def add_reading_session(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        pages_read: int,
        session_date: datetime | None = None,
    ) -> ReadingSession:
        # don't let users log more pages than the book actually has remaining
        if pages_read > 0:
            book = await self.book_repo.get_by_id(book_id)
            if book and book.page_count > 0:
                progress = await self.reading_repo.get_book_progress(user_id, book_id)
                already_read = progress.pages_read if progress else 0
                remaining = book.page_count - already_read

                if remaining <= 0:
                    raise ReadingLimitError(
                        f"You've already finished '{book.title}' ({book.page_count} pages). "
                        f"Use 'set' to adjust your progress."
                    )
                if pages_read > remaining:
                    raise ReadingLimitError(
                        f"'{book.title}' only has {remaining} pages left "
                        f"({already_read}/{book.page_count} read). "
                        f"Try logging {remaining} pages instead."
                    )

        session = await self.reading_repo.create_session(
            user_id, book_id, pages_read, session_date
        )
        return session

    async def get_book_progress(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> BookProgress | None:
        return await self.reading_repo.get_book_progress(user_id, book_id)

    async def get_all_progress(
        self, user_id: uuid_module.UUID,
        filter_by: str | None = None,
    ) -> list[BookProgress]:
        all_progress = await self.reading_repo.get_all_progress(user_id)

        if filter_by == "completed":
            return [p for p in all_progress if p.progress_percentage >= 100]
        elif filter_by == "in_progress":
            return [p for p in all_progress if 0 < p.progress_percentage < 100]
        elif filter_by == "not_started":
            return [p for p in all_progress if p.progress_percentage == 0]
        return all_progress

    async def reduce_reading_progress(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        pages_to_reduce: int,
        session_date: datetime | None = None,
    ) -> dict:
        return await self.reading_repo.reduce_reading_progress(
            user_id, book_id, pages_to_reduce, session_date
        )

    async def set_reading_progress(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        target_pages: int,
        session_date: datetime | None = None,
    ) -> dict:
        # sanity check against total page count
        book = await self.book_repo.get_by_id(book_id)
        if book and book.page_count > 0 and target_pages > book.page_count:
            raise ReadingLimitError(
                f"'{book.title}' only has {book.page_count} pages. "
                f"Can't set progress to page {target_pages}."
            )

        return await self.reading_repo.set_reading_progress(
            user_id, book_id, target_pages, session_date
        )

    async def remove_book_tracking(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> int:
        return await self.reading_repo.remove_book_tracking(user_id, book_id)

    async def compute_reading_stats(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> dict | None:
        """Compute derived stats (completion status, pages remaining) for a tracked book."""
        progress = await self.reading_repo.get_book_progress(user_id, book_id)
        if not progress:
            return None

        completed = progress.progress_percentage >= 100
        remaining = max(progress.total_pages - progress.pages_read, 0)

        return {
            "completed": completed,
            "pages_remaining": remaining,
            "pages_read": progress.pages_read,
            "total_pages": progress.total_pages,
            "percentage": progress.progress_percentage,
        }
