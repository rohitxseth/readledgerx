from uuid import UUID

from app.schemas.models import Book, BookProgress, ReadingSession, User


def _as_list(value: list[str] | str | None) -> list[str]:
    if isinstance(value, str):
        return [value]
    return value or []


class UserMapper:
    @staticmethod
    def from_db(row: dict) -> User:
        return User(
            id=row["id"],
            email=row["email"],
            created_at=row["created_at"],
            hashed_password=row["password_hash"],
        )


class BookMapper:
    @staticmethod
    def from_db(row: dict) -> Book:
        published_year = row["published_year"]
        return Book(
            id=row["id"],
            title=row["title"],
            authors=_as_list(row["authors"]),
            page_count=row["page_count"],
            published_date=str(published_year) if published_year is not None else None,
            description=row["description"],
            thumbnail_url=row["thumbnail_url"],
            google_books_id=row["google_volume_id"],
            subtitle=row["subtitle"],
            categories=_as_list(row["categories"]),
            language=row["language"],
            created_at=row["created_at"],
        )

    @staticmethod
    def from_google_books(data: dict, fallback_id: UUID) -> Book:
        info = data.get("volumeInfo", {})
        published_date = info.get("publishedDate")
        return Book(
            id=fallback_id,
            title=info.get("title", "Unknown"),
            authors=info.get("authors", []),
            page_count=info.get("pageCount", 0),
            published_date=str(published_date) if published_date is not None else None,
            description=info.get("description"),
            thumbnail_url=info.get("imageLinks", {}).get("thumbnail"),
            google_books_id=data.get("id"),
            subtitle=info.get("subtitle"),
            categories=info.get("categories", []),
            language=info.get("language"),
        )


class ReadingSessionMapper:
    @staticmethod
    def from_db(row: dict) -> ReadingSession:
        return ReadingSession(
            id=row["id"],
            user_id=row["user_id"],
            book_id=row["book_id"],
            pages_read=row["pages"],
            session_date=row["read_on"],
            created_at=row["created_at"],
        )


class BookProgressMapper:
    @staticmethod
    def from_db(row: dict) -> BookProgress:
        pages_read = row["pages_read"]
        # page_count is nullable; a book with no known length shows as 1 page
        # rather than dividing by zero.
        total_pages = row["total_pages"] or 1
        return BookProgress(
            book_id=row["book_id"],
            title=row["title"],
            authors=_as_list(row["authors"]),
            total_pages=total_pages,
            pages_read=pages_read,
            progress_percentage=round(pages_read / total_pages * 100, 2),
            last_read_date=row["last_read_date"],
            last_session_at=row.get("last_session_at"),
            thumbnail_url=row["thumbnail_url"],
        )
