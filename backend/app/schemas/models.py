from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class User(BaseModel):
    id: UUID
    email: str
    created_at: datetime
    hashed_password: str | None = None


class Book(BaseModel):
    id: UUID
    title: str
    authors: list[str] = Field(default_factory=list)
    page_count: int = 0
    published_date: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    google_books_id: str | None = None
    subtitle: str | None = None
    categories: list[str] = Field(default_factory=list)
    language: str | None = None
    created_at: datetime | None = None


class ReadingSession(BaseModel):
    id: UUID
    user_id: UUID
    book_id: UUID
    pages_read: int
    session_date: datetime
    created_at: datetime


class BookProgress(BaseModel):
    book_id: UUID
    title: str
    authors: list[str]
    total_pages: int
    pages_read: int
    progress_percentage: float
    last_read_date: datetime
    # read_on is a DATE, so it can't order two books read the same day.
    # created_at carries the sub-day ordering needed to break that tie.
    last_session_at: datetime | None = None
    thumbnail_url: str | None = None


LogAction = Literal["add", "set", "reduce", "remove"]
ProgressFilter = Literal["completed", "in_progress", "not_started"]
ProgressSort = Literal["pages_read", "percent_complete", "last_read"]


# The outcomes below are returned by ReadingService and serialised as-is by the
# REST API, so the chat agent and REST clients get the same result for the
# same operation.


class TrackingResult(BaseModel):
    book: Book
    progress: BookProgress
    created: bool  # False when the book was already tracked
    pages_logged: int = 0


class ReadingLogResult(BaseModel):
    action: LogAction
    book: Book
    pages: int  # after converting a percentage to pages
    pages_reduced: int | None = None  # can be less than asked for
    sessions_removed: int | None = None
    progress: BookProgress | None = None  # None once the book is untracked


class UndoResult(BaseModel):
    session: ReadingSession
    book: Book | None = None
    progress: BookProgress | None = None  # None if it was the book's only entry
