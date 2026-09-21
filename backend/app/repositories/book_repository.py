from uuid import UUID

from sqlalchemy import case, func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.mappers import BookMapper
from app.models import books
from app.schemas.models import Book


class BookRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def get_by_id(self, book_id: UUID) -> Book | None:
        stmt = select(books).where(books.c.id == book_id)
        row = (await self.conn.execute(stmt)).first()
        return BookMapper.from_db(dict(row._mapping)) if row else None

    async def get_by_title(self, title: str) -> Book | None:
        needle = title.lower().strip()
        safe = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        lowered = func.lower(books.c.title)

        stmt = (
            select(books)
            .where(lowered.like(f"%{safe}%", escape="\\"))
            .order_by(
                case(
                    (lowered == needle, 0),
                    (lowered.like(f"{safe}%", escape="\\"), 1),
                    else_=2,
                ),
                func.length(books.c.title),
                books.c.created_at,
            )
            .limit(1)
        )
        row = (await self.conn.execute(stmt)).first()
        return BookMapper.from_db(dict(row._mapping)) if row else None

    async def get_by_google_volume_id(self, google_volume_id: str) -> Book | None:
        stmt = select(books).where(books.c.google_volume_id == google_volume_id)
        row = (await self.conn.execute(stmt)).first()
        return BookMapper.from_db(dict(row._mapping)) if row else None

    async def create(self, book: Book) -> Book:
        # Google Books dates are "YYYY", "YYYY-MM" or "YYYY-MM-DD"; the table
        # stores only the year.
        published_year = None
        if book.published_date:
            try:
                published_year = int(book.published_date.split("-")[0])
            except ValueError:
                pass

        stmt = (
            insert(books)
            .values(
                id=book.id,
                google_volume_id=book.google_books_id,
                title=book.title,
                subtitle=book.subtitle,
                authors=book.authors,
                published_year=published_year,
                description=book.description,
                page_count=book.page_count,
                categories=book.categories,
                thumbnail_url=book.thumbnail_url,
                language=book.language,
            )
            .returning(books)
        )
        row = (await self.conn.execute(stmt)).first()
        return BookMapper.from_db(dict(row._mapping))
