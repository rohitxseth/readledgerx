from __future__ import annotations

import uuid as uuid_module
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.schemas.models import Book, BookProgress, ReadingSession, User


@runtime_checkable
class IUserRepository(Protocol):
    """Contract for user persistence operations."""

    async def get_by_id(self, user_id: uuid_module.UUID) -> User | None:
        """Retrieve a user by their primary key."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Retrieve a user by their email address."""
        ...

    async def create(self, email: str, hashed_password: str) -> User:
        """Persist a new user and return the created entity."""
        ...

    async def update_last_login(self, user_id: uuid_module.UUID) -> None:
        """Record the timestamp of a user's most recent login."""
        ...


@runtime_checkable
class IBookRepository(Protocol):
    """Contract for book persistence operations."""

    async def get_by_id(self, book_id: uuid_module.UUID) -> Book | None:
        """Retrieve a book by its internal UUID."""
        ...

    async def get_by_title(self, title: str) -> Book | None:
        """Search for a book by title (case-insensitive partial match)."""
        ...

    async def get_by_google_volume_id(self, google_volume_id: str) -> Book | None:
        """Retrieve a book using the Google Books volume identifier."""
        ...

    async def create(self, book: Book) -> Book:
        """Persist a new book record and return the created entity."""
        ...


@runtime_checkable
class IReadingRepository(Protocol):
    """Contract for reading-session persistence operations."""

    async def create_session(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        pages_read: int,
        session_date: datetime | None = None,
    ) -> ReadingSession:
        """Record a new reading session."""
        ...

    async def get_book_progress(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> BookProgress | None:
        """Aggregate reading progress for a specific book."""
        ...

    async def get_all_progress(
        self, user_id: uuid_module.UUID
    ) -> list[BookProgress]:
        """Aggregate reading progress for all books the user has tracked."""
        ...

    async def reduce_reading_progress(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        pages_to_reduce: int,
        session_date: datetime | None = None,
    ) -> dict:
        """Reduce total pages read by deleting/trimming the newest sessions."""
        ...

    async def set_reading_progress(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        target_pages: int,
        session_date: datetime | None = None,
    ) -> dict:
        """Set absolute reading progress, adding or removing sessions as needed."""
        ...

    async def remove_book_tracking(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> int:
        """Delete all sessions for a book, effectively stopping tracking."""
        ...

    async def delete_latest_session(
        self, user_id: uuid_module.UUID
    ) -> ReadingSession | None:
        """Delete the user's most recently logged session and return it.

        "Most recent" is by when it was logged (created_at), not by read_on,
        so undoing a backdated entry removes that entry. None if there is none.
        """
        ...
