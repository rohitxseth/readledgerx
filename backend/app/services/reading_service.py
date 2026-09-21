import logging
import uuid as uuid_module
from datetime import date, datetime
from typing import get_args

from app.core.exceptions import (
    BusinessLogicError,
    EntityNotFoundError,
    ReadingLimitError,
)
from app.domain.value_objects import PageCount
from app.interfaces.repository_interfaces import IBookRepository, IReadingRepository
from app.schemas.models import (
    Book,
    BookProgress,
    LogAction,
    ProgressFilter,
    ProgressSort,
    ReadingLogResult,
    ReadingSession,
    TrackingResult,
    UndoResult,
)

logger = logging.getLogger(__name__)


class ReadingService:
    _SORT_KEYS = {
        "pages_read": lambda p: p.pages_read,
        "percent_complete": lambda p: p.progress_percentage,
        "last_read": lambda p: (
            p.last_read_date,
            p.last_session_at.timestamp() if p.last_session_at else 0.0,
        ),
    }

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
        filter_by: ProgressFilter | str | None = None,
        sort_by: ProgressSort | str | None = None,
        limit: int | None = None,
    ) -> list[BookProgress]:
        all_progress = await self.reading_repo.get_all_progress(user_id)

        if filter_by == "completed":
            all_progress = [p for p in all_progress if p.progress_percentage >= 100]
        elif filter_by == "in_progress":
            all_progress = [p for p in all_progress if 0 < p.progress_percentage < 100]
        elif filter_by == "not_started":
            all_progress = [p for p in all_progress if p.progress_percentage == 0]

        sort_key = self._SORT_KEYS.get(sort_by)
        if sort_key:
            all_progress = sorted(all_progress, key=sort_key, reverse=True)

        if limit is not None and limit > 0:
            all_progress = all_progress[:limit]

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

    async def start_tracking(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID, pages: int = 0
    ) -> TrackingResult:
        book = await self._require_book(book_id)
        self._validate_pages(pages)
        existing = await self.reading_repo.get_book_progress(user_id, book_id)

        if existing and pages == 0:
            return TrackingResult(book=book, progress=existing, created=False)

        await self.add_reading_session(user_id, book_id, pages)
        progress = await self.reading_repo.get_book_progress(user_id, book_id)
        return TrackingResult(
            book=book, progress=progress, created=existing is None, pages_logged=pages
        )

    async def log_reading(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        *,
        action: LogAction = "add",
        pages: int | None = None,
        percentage: float | None = None,
        session_date: datetime | date | None = None,
    ) -> ReadingLogResult:
        if action not in get_args(LogAction):
            raise BusinessLogicError(f"Unknown action '{action}'.")
        book = await self._require_book(book_id)

        if action == "remove":
            removed = await self.reading_repo.remove_book_tracking(user_id, book_id)
            return ReadingLogResult(action=action, book=book, pages=0, sessions_removed=removed)

        amount = self._amount(book, action, pages, percentage)
        pages_reduced = None

        if action == "add":
            await self.add_reading_session(user_id, book_id, amount, session_date)
        elif action == "set":
            await self.set_reading_progress(user_id, book_id, amount, session_date)
        else:  # reduce
            if not await self.reading_repo.get_book_progress(user_id, book_id):
                raise BusinessLogicError(f"No pages have been logged for '{book.title}' yet.")
            reduced = await self.reduce_reading_progress(user_id, book_id, amount, session_date)
            pages_reduced = reduced.get("pages_reduced", amount)

        return ReadingLogResult(
            action=action,
            book=book,
            pages=amount,
            pages_reduced=pages_reduced,
            progress=await self.reading_repo.get_book_progress(user_id, book_id),
        )

    async def undo_last_log(self, user_id: uuid_module.UUID) -> UndoResult:
        session = await self.reading_repo.delete_latest_session(user_id)
        if session is None:
            raise EntityNotFoundError("There's nothing to undo — no reading has been logged yet.")
        return UndoResult(
            session=session,
            book=await self.book_repo.get_by_id(session.book_id),
            progress=await self.reading_repo.get_book_progress(user_id, session.book_id),
        )

    async def _require_book(self, book_id: uuid_module.UUID) -> Book:
        book = await self.book_repo.get_by_id(book_id)
        if book is None:
            raise EntityNotFoundError("Book not found.")
        return book

    @staticmethod
    def _validate_pages(pages: int) -> None:
        try:
            PageCount(pages)
        except (TypeError, ValueError) as e:
            raise BusinessLogicError(str(e)) from e

    def _amount(
        self, book: Book, action: str, pages: int | None, percentage: float | None
    ) -> int:
        if pages is None and percentage is None:
            raise BusinessLogicError("How many pages? Give a page count or a percentage.")

        if pages is None:
            if not 0 <= percentage <= 100:
                raise BusinessLogicError("A percentage must be between 0 and 100.")
            if not book.page_count:
                raise BusinessLogicError(
                    f"The total page count for '{book.title}' is unknown, so a "
                    "percentage can't be converted. Use a page number instead."
                )
            pages = int((percentage / 100) * book.page_count)

        self._validate_pages(pages)
        if pages == 0 and action in ("add", "reduce"):
            raise BusinessLogicError("The number of pages must be greater than zero.")
        return pages
