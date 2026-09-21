from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy import select, insert, func, desc, delete, update
from app.models import reading_sessions, books
from app.schemas.models import ReadingSession, BookProgress
from app.domain.mappers import ReadingSessionMapper, BookProgressMapper
from app.domain.value_objects import PageCount
from datetime import datetime, timezone
import uuid as uuid_module


class ReadingRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def create_session(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        pages_read: int,
        session_date: datetime | None = None,
    ) -> ReadingSession:
        # validate through value object — fails fast on negatives or absurd values
        PageCount(pages_read)

        if session_date is None:
            session_date = datetime.now(timezone.utc)

        read_on_date = (
            session_date.date() if isinstance(session_date, datetime) else session_date
        )

        stmt = (
            insert(reading_sessions)
            .values(
                user_id=user_id,
                book_id=book_id,
                pages=pages_read,
                read_on=read_on_date,
            )
            .returning(reading_sessions)
        )
        result = await self.conn.execute(stmt)
        row = result.first()
        return ReadingSessionMapper.from_db(dict(row._mapping))

    async def get_book_progress(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> BookProgress | None:
        stmt = (
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
            .where(reading_sessions.c.book_id == book_id)
            .group_by(
                books.c.id,
                books.c.title,
                books.c.authors,
                books.c.page_count,
                books.c.thumbnail_url,
            )
        )

        result = await self.conn.execute(stmt)
        row = result.first()
        if not row:
            return None

        return BookProgressMapper.from_db(dict(row._mapping))

    async def get_all_progress(self, user_id: uuid_module.UUID) -> list[BookProgress]:
        stmt = (
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
            .order_by(desc("last_read_date"), desc("last_session_at"))
        )

        result = await self.conn.execute(stmt)
        return [BookProgressMapper.from_db(dict(row._mapping)) for row in result]

    async def reduce_reading_progress(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        pages_to_reduce: int,
        session_date: datetime | None = None,
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
        result = await self.conn.execute(stmt)
        sessions = list(result)

        if not sessions:
            raise ValueError("No reading sessions found for this book")

        pages_reduced = 0
        sessions_to_delete = []
        remaining_pages_needed = pages_to_reduce

        for session_row in sessions:
            session_pages = session_row.pages

            if session_pages <= remaining_pages_needed:
                sessions_to_delete.append(session_row.id)
                pages_reduced += session_pages
                remaining_pages_needed -= session_pages

                if remaining_pages_needed == 0:
                    break
            else:
                new_pages = session_pages - remaining_pages_needed
                update_stmt = (
                    update(reading_sessions)
                    .where(reading_sessions.c.id == session_row.id)
                    .values(pages=new_pages)
                )
                await self.conn.execute(update_stmt)
                pages_reduced += remaining_pages_needed
                remaining_pages_needed = 0
                break

        if sessions_to_delete:
            delete_stmt = delete(reading_sessions).where(
                reading_sessions.c.id.in_(sessions_to_delete)
            )
            await self.conn.execute(delete_stmt)

        return {
            "pages_reduced": pages_reduced,
            "sessions_deleted": len(sessions_to_delete),
        }

    async def set_reading_progress(
        self,
        user_id: uuid_module.UUID,
        book_id: uuid_module.UUID,
        target_pages: int,
        session_date: datetime | None = None,
    ) -> dict:
        if target_pages < 0:
            raise ValueError("Target pages cannot be negative")

        current_progress = await self.get_book_progress(user_id, book_id)
        current_pages = current_progress.pages_read if current_progress else 0
        pages_diff = target_pages - current_pages

        if pages_diff == 0:
            return {"action": "none", "pages": target_pages}

        if session_date is None:
            session_date = datetime.now(timezone.utc)

        read_on_date = (
            session_date.date() if isinstance(session_date, datetime) else session_date
        )

        if pages_diff > 0:
            stmt = (
                insert(reading_sessions)
                .values(
                    user_id=user_id,
                    book_id=book_id,
                    pages=pages_diff,
                    read_on=read_on_date,
                )
                .returning(reading_sessions)
            )
            result = await self.conn.execute(stmt)
            row = result.first()
            return {
                "action": "added",
                "pages": pages_diff,
                "session": ReadingSessionMapper.from_db(dict(row._mapping)),
            }
        else:
            result = await self.reduce_reading_progress(
                user_id, book_id, abs(pages_diff), session_date
            )
            return {"action": "reduced", **result}

    async def remove_book_tracking(
        self, user_id: uuid_module.UUID, book_id: uuid_module.UUID
    ) -> int:
        stmt = delete(reading_sessions).where(
            reading_sessions.c.user_id == user_id,
            reading_sessions.c.book_id == book_id,
        )
        result = await self.conn.execute(stmt)
        return result.rowcount
