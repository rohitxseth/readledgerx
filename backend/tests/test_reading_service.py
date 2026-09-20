"""
Tests for ReadingService — the business logic layer for reading progress.

ReadingService sits between routers and repositories. It should not know
about SQL or HTTP. All DB access goes through the fake repo.
"""

import uuid
import pytest

from app.services.reading_service import ReadingService
from tests.conftest import FakeReadingRepository, FakeBookRepository, make_book


def _make_service(reading_repo=None, book_repo=None):
    return ReadingService(
        reading_repo=reading_repo or FakeReadingRepository(),
        book_repo=book_repo or FakeBookRepository(),
    )


async def test_add_session_stores_pages():
    user_id = uuid.uuid4()
    book_id = uuid.uuid4()
    reading_repo = FakeReadingRepository()

    svc = _make_service(reading_repo=reading_repo)
    session = await svc.add_reading_session(user_id, book_id, pages_read=50)

    assert session.pages_read == 50
    assert len(reading_repo._sessions) == 1


async def test_get_book_progress_aggregates_sessions():
    user_id = uuid.uuid4()
    book_id = uuid.uuid4()
    reading_repo = FakeReadingRepository()

    svc = _make_service(reading_repo=reading_repo)
    await svc.add_reading_session(user_id, book_id, pages_read=30)
    await svc.add_reading_session(user_id, book_id, pages_read=20)

    progress = await svc.get_book_progress(user_id, book_id)
    assert progress is not None
    assert progress.pages_read == 50


async def test_get_book_progress_returns_none_when_no_sessions():
    svc = _make_service()
    progress = await svc.get_book_progress(uuid.uuid4(), uuid.uuid4())
    assert progress is None


async def test_get_all_progress_returns_all_books():
    user_id = uuid.uuid4()
    book_a = uuid.uuid4()
    book_b = uuid.uuid4()
    reading_repo = FakeReadingRepository()

    svc = _make_service(reading_repo=reading_repo)
    await svc.add_reading_session(user_id, book_a, pages_read=10)
    await svc.add_reading_session(user_id, book_b, pages_read=20)

    all_progress = await svc.get_all_progress(user_id)
    book_ids = {p.book_id for p in all_progress}
    assert book_ids == {book_a, book_b}


async def test_remove_book_tracking_clears_sessions():
    user_id = uuid.uuid4()
    book_id = uuid.uuid4()
    reading_repo = FakeReadingRepository()

    svc = _make_service(reading_repo=reading_repo)
    await svc.add_reading_session(user_id, book_id, pages_read=100)

    removed = await svc.remove_book_tracking(user_id, book_id)
    assert removed == 1
    assert reading_repo._sessions == []


async def test_sessions_for_different_users_are_isolated():
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    book_id = uuid.uuid4()
    reading_repo = FakeReadingRepository()

    svc = _make_service(reading_repo=reading_repo)
    await svc.add_reading_session(user_a, book_id, pages_read=100)
    await svc.add_reading_session(user_b, book_id, pages_read=50)

    progress_a = await svc.get_book_progress(user_a, book_id)
    progress_b = await svc.get_book_progress(user_b, book_id)

    assert progress_a.pages_read == 100
    assert progress_b.pages_read == 50
