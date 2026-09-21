from __future__ import annotations

import uuid as uuid_module
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.schemas.models import Book, BookProgress, ReadingSession, User


@runtime_checkable
class IUserRepository(Protocol):
    async def get_by_id(self, user_id: uuid_module.UUID) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def create(self, email: str, hashed_password: str) -> User: ...
    async def update_last_login(self, user_id: uuid_module.UUID) -> None: ...


@runtime_checkable
class IBookRepository(Protocol):
    async def get_by_id(self, book_id: uuid_module.UUID) -> Book | None: ...
    async def get_by_title(self, title: str) -> Book | None: ...
    async def get_by_google_volume_id(self, google_volume_id: str) -> Book | None: ...
    async def create(self, book: Book) -> Book: ...


@runtime_checkable
class IReadingRepository(Protocol):
    async def create_session(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        pages_read: int,
        session_date: datetime | None = None,
    ) -> ReadingSession: ...

    async def get_book_progress(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> BookProgress | None: ...

    async def get_all_progress(
        self, user_id: uuid_module.UUID
    ) -> list[BookProgress]: ...

    async def reduce_reading_progress(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        pages_to_reduce: int,
        session_date: datetime | None = None,
    ) -> dict: ...

    async def set_reading_progress(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        target_pages: int,
        session_date: datetime | None = None,
    ) -> dict: ...

    async def remove_book_tracking(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> int: ...

    async def delete_latest_session(
        self, user_id: uuid_module.UUID
    ) -> ReadingSession | None: ...
