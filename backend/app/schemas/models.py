from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import Optional, List


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
