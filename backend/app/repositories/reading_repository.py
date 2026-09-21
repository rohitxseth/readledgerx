from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import Select, delete, desc, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.mappers import BookProgressMapper, ReadingSessionMapper
from app.models import books, reading_sessions
from app.schemas.models import BookProgress, ReadingSession


def _progress_query(user_id: UUID) -> Select:
    return (
        select(
            books.c.id.label("book_id"),
            books.c.title,
            books.c.authors,
            books.c.page_count.label("total_pages"),
            books.c.thumbnail_url,
            func.sum(reading_sessions.c.pages).label("pages_read"),
            func.max(reading_sessions.c.read_on).label("last_read_date"),
            func.max(reading_sessions.c.created_at).label("last_session_at"),
        )
        .select_from(
            reading_sessions.join(books, reading_sessions.c.book_id == books.c.id)
        )
        .where(reading_sessions.c.user_id == user_id)
        .group_by(
            books.c.id,
            books.c.title,
            books.c.authors,
            books.c.page_count,
            books.c.thumbnail_url,
        )
    )


class ReadingRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def create_session(
        self,
        user_id: UUID,
        book_id: UUID,
        pages_read: int,
        session_date: date | None = None,
    ) -> ReadingSession:
        session_date = session_date or datetime.now(UTC)
        if isinstance(session_date, datetime):
            session_date = session_date.date()

        stmt = (
            insert(reading_sessions)
            .values(
                user_id=user_id, book_id=book_id, pages=pages_read, read_on=session_date
            )
            .returning(reading_sessions)
        )
        row = (await self.conn.execute(stmt)).first()
        return ReadingSessionMapper.from_db(dict(row._mapping))

    async def get_book_progress(
        self, user_id: UUID, book_id: UUID
    ) -> BookProgress | None:
        stmt = _progress_query(user_id).where(reading_sessions.c.book_id == book_id)
        row = (await self.conn.execute(stmt)).first()
        return BookProgressMapper.from_db(dict(row._mapping)) if row else None

    async def get_all_progress(self, user_id: UUID) -> list[BookProgress]:
        stmt = _progress_query(user_id).order_by(
            desc("last_read_date"), desc("last_session_at")
        )
        result = await self.conn.execute(stmt)
        return [BookProgressMapper.from_db(dict(row._mapping)) for row in result]

    async def reduce_reading_progress(
        self, user_id: UUID, book_id: UUID, pages_to_reduce: int
    ) -> dict:
        if pages_to_reduce < 0:
            raise ValueError("Pages to reduce must be positive")
        if pages_to_reduce == 0:
            return {"pages_reduced": 0, "sessions_deleted": 0}

        stmt = (
            select(reading_sessions)
            .where(
                reading_sessions.c.user_id == user_id,
                reading_sessions.c.book_id == book_id,
            )
            .order_by(
                desc(reading_sessions.c.read_on), desc(reading_sessions.c.created_at)
            )
        )
        sessions = list(await self.conn.execute(stmt))
        if not sessions:
            raise ValueError("No reading sessions found for this book")

        # Take pages off the newest sessions first: delete each one that is
        # used up entirely, and trim the one the reduction ends inside.
        remaining = pages_to_reduce
        to_delete = []
        for session in sessions:
            if session.pages > remaining:
                await self.conn.execute(
                    update(reading_sessions)
                    .where(reading_sessions.c.id == session.id)
                    .values(pages=session.pages - remaining)
                )
                remaining = 0
                break
            to_delete.append(session.id)
            remaining -= session.pages
            if remaining == 0:
                break

        if to_delete:
            await self.conn.execute(
                delete(reading_sessions).where(reading_sessions.c.id.in_(to_delete))
            )

        return {
            "pages_reduced": pages_to_reduce - remaining,
            "sessions_deleted": len(to_delete),
        }

    async def set_reading_progress(
        self,
        user_id: UUID,
        book_id: UUID,
        target_pages: int,
        session_date: date | None = None,
    ) -> None:
        if target_pages < 0:
            raise ValueError("Target pages cannot be negative")

        progress = await self.get_book_progress(user_id, book_id)
        difference = target_pages - (progress.pages_read if progress else 0)

        if difference > 0:
            await self.create_session(user_id, book_id, difference, session_date)
        elif difference < 0:
            await self.reduce_reading_progress(user_id, book_id, -difference)

    async def remove_book_tracking(self, user_id: UUID, book_id: UUID) -> int:
        stmt = delete(reading_sessions).where(
            reading_sessions.c.user_id == user_id,
            reading_sessions.c.book_id == book_id,
        )
        return (await self.conn.execute(stmt)).rowcount

    async def delete_latest_session(self, user_id: UUID) -> ReadingSession | None:
        latest = (
            select(reading_sessions.c.id)
            .where(reading_sessions.c.user_id == user_id)
            .order_by(desc(reading_sessions.c.created_at), desc(reading_sessions.c.id))
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            delete(reading_sessions)
            .where(reading_sessions.c.id == latest)
            .returning(reading_sessions)
        )
        row = (await self.conn.execute(stmt)).first()
        return ReadingSessionMapper.from_db(dict(row._mapping)) if row else None
