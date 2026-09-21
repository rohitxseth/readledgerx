from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import List, Literal, Optional


class User(BaseModel):
    id: UUID
    email: str
    username: Optional[str] = None
    created_at: datetime
    hashed_password: Optional[str] = None


class Book(BaseModel):
    id: UUID
    title: str
    authors: List[str] = Field(default_factory=list)
    page_count: int = 0
    published_date: Optional[str] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    google_books_id: Optional[str] = None
    subtitle: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    language: Optional[str] = None
    created_at: Optional[datetime] = None


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
    authors: List[str]
    total_pages: int
    pages_read: int
    progress_percentage: float
    last_read_date: datetime
    # read_on is a DATE, so it can't order two books read the same day.
    # created_at carries the sub-day ordering needed to break that tie.
    last_session_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Outcomes of reading operations
#
# Returned by ReadingService and serialised as-is by the REST API, so both the
# chat agent and REST clients receive the same result for the same operation.
# ---------------------------------------------------------------------------

LogAction = Literal["add", "set", "reduce", "remove"]
ProgressFilter = Literal["completed", "in_progress", "not_started"]
ProgressSort = Literal["pages_read", "percent_complete", "last_read"]


class TrackingResult(BaseModel):
    book: Book
    progress: BookProgress
    created: bool                  # False when the book was already tracked
    pages_logged: int = 0


class ReadingLogResult(BaseModel):
    action: LogAction
    book: Book
    pages: int                     # amount applied, after any % conversion
    pages_reduced: Optional[int] = None     # reduce: can be less than asked
    sessions_removed: Optional[int] = None  # remove
    progress: Optional[BookProgress] = None  # None once a book is untracked


class UndoResult(BaseModel):
    session: ReadingSession        # the entry that was removed
    book: Optional[Book] = None
    progress: Optional[BookProgress] = None  # None if it was the book's only entry
