from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy import select, insert, func
from app.models import books
from app.schemas.models import Book
from app.domain.mappers import BookMapper
import uuid as uuid_module


class BookRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def get_by_id(self, book_id: uuid_module.UUID) -> Book | None:
        stmt = select(books).where(books.c.id == book_id)
        result = await self.conn.execute(stmt)
        row = result.first()
        return BookMapper.from_db(dict(row._mapping)) if row else None

    async def get_by_title(self, title: str) -> Book | None:
        # escape any LIKE-special chars so user input is matched literally
        safe = title.lower().replace("%", "\\%").replace("_", "\\_")
        stmt = select(books).where(func.lower(books.c.title).like(f"%{safe}%"))
        result = await self.conn.execute(stmt)
        row = result.first()
        return BookMapper.from_db(dict(row._mapping)) if row else None

    async def get_by_google_volume_id(self, google_volume_id: str) -> Book | None:
        stmt = select(books).where(books.c.google_volume_id == google_volume_id)
        result = await self.conn.execute(stmt)
        row = result.first()
        return BookMapper.from_db(dict(row._mapping)) if row else None

    async def create(self, book: Book) -> Book:
        published_year = None
        if book.published_date:
            try:
                year_str = book.published_date.split("-")[0]
                published_year = int(year_str)
            except (ValueError, IndexError):
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
        result = await self.conn.execute(stmt)
        row = result.first()
        return BookMapper.from_db(dict(row._mapping))
