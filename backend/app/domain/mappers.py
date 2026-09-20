from __future__ import annotations

from app.schemas.models import User, Book, ReadingSession, BookProgress


class UserMapper:
    @staticmethod
    def from_db(row: dict) -> User:
        return User(
            id=row["id"],
            email=row["email"],
            username=row.get("username"),
            created_at=row["created_at"],
            hashed_password=row.get("hashed_password") or row.get("password_hash"),
        )


class BookMapper:
    @staticmethod
    def from_db(row: dict) -> Book:
        authors = row.get("authors", [])
        if isinstance(authors, str):
            authors = [authors]

        categories = row.get("categories", [])
        if isinstance(categories, str):
            categories = [categories]

        pub_date = row.get("published_date") or row.get("published_year")
        if pub_date is not None:
            pub_date = str(pub_date)

        return Book(
            id=row["id"],
            title=row["title"],
            authors=authors or [],
            page_count=row.get("page_count", 0),
            published_date=pub_date,
            description=row.get("description"),
            thumbnail_url=row.get("thumbnail_url"),
            google_books_id=row.get("google_books_id") or row.get("google_volume_id"),
            subtitle=row.get("subtitle"),
            categories=categories or [],
            language=row.get("language"),
            created_at=row.get("created_at"),
        )

    @staticmethod
    def from_google_books(data: dict, fallback_id) -> Book:
        from uuid import UUID
        volume_info = data.get("volumeInfo", {})
        pub_date = volume_info.get("publishedDate")
        if pub_date is not None:
            pub_date = str(pub_date)

        return Book(
            id=fallback_id,
            title=volume_info.get("title", "Unknown"),
            authors=volume_info.get("authors", []),
            page_count=volume_info.get("pageCount", 0),
            published_date=pub_date,
            description=volume_info.get("description"),
            thumbnail_url=volume_info.get("imageLinks", {}).get("thumbnail"),
            google_books_id=data.get("id"),
            subtitle=volume_info.get("subtitle"),
            categories=volume_info.get("categories", []),
            language=volume_info.get("language"),
        )


class ReadingSessionMapper:
    @staticmethod
    def from_db(row: dict) -> ReadingSession:
        return ReadingSession(
            id=row["id"],
            user_id=row["user_id"],
            book_id=row["book_id"],
            pages_read=row.get("pages_read") or row.get("pages", 0),
            session_date=row.get("session_date") or row.get("read_on"),
            created_at=row["created_at"],
        )


class BookProgressMapper:
    @staticmethod
    def from_db(row: dict) -> BookProgress:
        authors = row.get("authors", [])
        if isinstance(authors, str):
            authors = [authors]

        pages_read = row.get("pages_read") or 0
        total_pages = row.get("total_pages") or 1
        progress_percentage = round((pages_read / total_pages) * 100, 2)

        return BookProgress(
            book_id=row["book_id"],
            title=row["title"],
            authors=authors or [],
            total_pages=row["total_pages"],
            pages_read=pages_read,
            progress_percentage=progress_percentage,
            last_read_date=row["last_read_date"],
            thumbnail_url=row.get("thumbnail_url"),
        )
