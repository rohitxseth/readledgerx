"""
Tests for domain mappers. These are pure functions — no async, no DB.

Mappers are the only place in the codebase that knows about column names.
If a DB column is ever renamed, these tests fail fast.
"""

import uuid
from datetime import UTC, datetime

from app.domain.mappers import (
    BookMapper,
    BookProgressMapper,
    ReadingSessionMapper,
    UserMapper,
)

# ---------------------------------------------------------------------------
# UserMapper
# ---------------------------------------------------------------------------

def test_user_mapper_from_db_basic():
    row = {
        "id": uuid.uuid4(),
        "email": "test@example.com",
        "password_hash": "hashed",
        "created_at": datetime.now(UTC),
    }
    user = UserMapper.from_db(row)
    assert user.email == "test@example.com"
    assert user.hashed_password == "hashed"


def test_user_mapper_handles_null_password():
    row = {
        "id": uuid.uuid4(),
        "email": "oauth@example.com",
        "password_hash": None,
        "created_at": datetime.now(UTC),
    }
    user = UserMapper.from_db(row)
    assert user.hashed_password is None


# ---------------------------------------------------------------------------
# BookMapper
# ---------------------------------------------------------------------------

def _book_row(**overrides):
    base = {
        "id": uuid.uuid4(),
        "title": "Dune",
        "subtitle": None,
        "authors": ["Frank Herbert"],
        "page_count": 412,
        "published_year": 1965,
        "description": "A sci-fi epic.",
        "thumbnail_url": None,
        "google_volume_id": "abc123",
        "categories": ["Science Fiction"],
        "language": "en",
        "created_at": datetime.now(UTC),
    }
    base.update(overrides)
    return base


def test_book_mapper_from_db():
    book = BookMapper.from_db(_book_row())
    assert book.title == "Dune"
    assert book.google_books_id == "abc123"
    assert book.authors == ["Frank Herbert"]


def test_book_mapper_published_year_becomes_string():
    book = BookMapper.from_db(_book_row(published_year=1965))
    # mapper converts int year to str for the domain model
    assert book.published_date == "1965"


def test_book_mapper_authors_coerced_from_string():
    """Postgres might return a single-element array that drivers give back as str."""
    book = BookMapper.from_db(_book_row(authors="Frank Herbert"))
    assert isinstance(book.authors, list)
    assert book.authors == ["Frank Herbert"]


def test_book_mapper_from_google_books():
    fake_api_response = {
        "id": "gbooksXYZ",
        "volumeInfo": {
            "title": "Sapiens",
            "authors": ["Yuval Noah Harari"],
            "pageCount": 443,
            "publishedDate": "2011",
            "description": "A history of humankind.",
            "imageLinks": {"thumbnail": "http://example.com/thumb.jpg"},
            "language": "en",
            "categories": ["History"],
        },
    }
    book = BookMapper.from_google_books(fake_api_response, uuid.uuid4())
    assert book.title == "Sapiens"
    assert book.google_books_id == "gbooksXYZ"
    assert book.page_count == 443


# ---------------------------------------------------------------------------
# BookProgressMapper
# ---------------------------------------------------------------------------

def test_progress_percentage_calculation():
    row = {
        "book_id": uuid.uuid4(),
        "title": "Atomic Habits",
        "authors": ["James Clear"],
        "total_pages": 200,
        "pages_read": 100,
        "last_read_date": datetime.now(UTC),
        "thumbnail_url": None,
    }
    progress = BookProgressMapper.from_db(row)
    assert progress.progress_percentage == 50.0


def test_progress_percentage_no_divide_by_zero():
    """total_pages=None should not blow up."""
    row = {
        "book_id": uuid.uuid4(),
        "title": "Unknown Pages Book",
        "authors": [],
        "total_pages": None,
        "pages_read": 50,
        "last_read_date": datetime.now(UTC),
        "thumbnail_url": None,
    }
    # Should not raise — mapper defaults total_pages to 1 when None
    progress = BookProgressMapper.from_db(row)
    assert progress.progress_percentage >= 0


# ---------------------------------------------------------------------------
# ReadingSessionMapper
# ---------------------------------------------------------------------------

def test_reading_session_mapper_from_db():
    row = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "book_id": uuid.uuid4(),
        "pages": 75,           # DB column name
        "read_on": datetime.now(UTC),  # DB column name
        "created_at": datetime.now(UTC),
    }
    session = ReadingSessionMapper.from_db(row)
    assert session.pages_read == 75
