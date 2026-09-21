"""
Tests for ReadingService — the business logic layer for reading progress.

ReadingService sits between routers and repositories. It should not know
about SQL or HTTP. All DB access goes through the fake repo.
"""

import uuid
from datetime import datetime, timedelta, timezone

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


# ---------------------------------------------------------------------------
# Ranking and limiting
#
# Regression cover for "what is my most read book?" returning the whole list:
# the agent had no way to rank, so it fell back to an unsorted show_progress.
# ---------------------------------------------------------------------------

async def test_sort_by_pages_read_ranks_highest_first():
    user = uuid.uuid4()
    small, big, mid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repo = FakeReadingRepository()

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(user, small, pages_read=50)
    await svc.add_reading_session(user, big, pages_read=200)
    await svc.add_reading_session(user, mid, pages_read=120)

    ranked = await svc.get_all_progress(user, sort_by="pages_read")
    assert [p.pages_read for p in ranked] == [200, 120, 50]


async def test_limit_returns_only_the_top_result():
    """"What is my most read book?" is sort_by + limit=1."""
    user = uuid.uuid4()
    small, big = uuid.uuid4(), uuid.uuid4()
    repo = FakeReadingRepository()

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(user, small, pages_read=50)
    await svc.add_reading_session(user, big, pages_read=200)

    top = await svc.get_all_progress(user, sort_by="pages_read", limit=1)
    assert len(top) == 1
    assert top[0].book_id == big


async def test_percent_complete_ranks_differently_from_pages_read():
    """The two rankings must genuinely differ, or sort_by is decorative."""
    user = uuid.uuid4()
    short_book, long_book = uuid.uuid4(), uuid.uuid4()
    repo = FakeReadingRepository(page_counts={short_book: 100, long_book: 1000})

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(user, short_book, pages_read=90)   # 90%
    await svc.add_reading_session(user, long_book, pages_read=300)   # 30%

    by_pages = await svc.get_all_progress(user, sort_by="pages_read", limit=1)
    by_percent = await svc.get_all_progress(user, sort_by="percent_complete", limit=1)

    assert by_pages[0].book_id == long_book
    assert by_percent[0].book_id == short_book


async def test_sort_by_last_read_ranks_most_recent_first():
    """"What did I read most recently?"."""
    user = uuid.uuid4()
    stale, fresh = uuid.uuid4(), uuid.uuid4()
    repo = FakeReadingRepository()

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(
        user, stale, pages_read=10,
        session_date=datetime.now(timezone.utc) - timedelta(days=10),
    )
    await svc.add_reading_session(
        user, fresh, pages_read=10,
        session_date=datetime.now(timezone.utc),
    )

    top = await svc.get_all_progress(user, sort_by="last_read", limit=1)
    assert top[0].book_id == fresh


async def test_closest_to_finishing_excludes_completed_books():
    """"Which book am I closest to finishing?" = filter + sort + limit."""
    user = uuid.uuid4()
    done, nearly, early = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repo = FakeReadingRepository(
        page_counts={done: 100, nearly: 100, early: 100}
    )

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(user, done, pages_read=100)    # 100%
    await svc.add_reading_session(user, nearly, pages_read=80)   # 80%
    await svc.add_reading_session(user, early, pages_read=10)    # 10%

    top = await svc.get_all_progress(
        user, filter_by="in_progress", sort_by="percent_complete", limit=1
    )
    assert len(top) == 1
    assert top[0].book_id == nearly


async def test_unknown_sort_by_is_ignored_not_fatal():
    """The LLM fills these in; an unexpected value must not raise."""
    user = uuid.uuid4()
    repo = FakeReadingRepository()

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(user, uuid.uuid4(), pages_read=10)
    await svc.add_reading_session(user, uuid.uuid4(), pages_read=20)

    assert len(await svc.get_all_progress(user, sort_by="bogus_field")) == 2


async def test_non_positive_limit_returns_everything():
    """limit=0 should not silently blank the user's shelf."""
    user = uuid.uuid4()
    repo = FakeReadingRepository()

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(user, uuid.uuid4(), pages_read=10)
    await svc.add_reading_session(user, uuid.uuid4(), pages_read=20)

    assert len(await svc.get_all_progress(user, limit=0)) == 2
    assert len(await svc.get_all_progress(user, limit=None)) == 2


async def test_default_call_is_unchanged_by_the_new_parameters():
    user = uuid.uuid4()
    repo = FakeReadingRepository()

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(user, uuid.uuid4(), pages_read=10)

    assert len(await svc.get_all_progress(user)) == 1


async def test_last_read_breaks_same_day_ties_by_session_time():
    """read_on is a DATE, so two books read today tie on it.

    Ordering must fall through to the newest session timestamp, otherwise
    "what did I read most recently?" returns an arbitrary book whenever the
    user logged more than one book on the same day.
    """
    user = uuid.uuid4()
    earlier, later = uuid.uuid4(), uuid.uuid4()
    repo = FakeReadingRepository()
    same_day = datetime.now(timezone.utc)

    svc = _make_service(reading_repo=repo)
    await svc.add_reading_session(user, earlier, pages_read=10, session_date=same_day)
    await svc.add_reading_session(user, later, pages_read=10, session_date=same_day)

    ranked = await svc.get_all_progress(user, sort_by="last_read")

    # Same calendar day, so the date alone cannot separate them.
    assert ranked[0].last_read_date == ranked[1].last_read_date
    assert ranked[0].book_id == later


async def test_last_read_still_prefers_a_newer_day_over_a_later_session():
    """A book read yesterday must not outrank one read today."""
    user = uuid.uuid4()
    yesterday_book, today_book = uuid.uuid4(), uuid.uuid4()
    repo = FakeReadingRepository()

    svc = _make_service(reading_repo=repo)
    # Logged second, but read on an older date.
    await svc.add_reading_session(
        user, today_book, pages_read=10, session_date=datetime.now(timezone.utc)
    )
    await svc.add_reading_session(
        user, yesterday_book, pages_read=10,
        session_date=datetime.now(timezone.utc) - timedelta(days=1),
    )

    top = await svc.get_all_progress(user, sort_by="last_read", limit=1)
    assert top[0].book_id == today_book
