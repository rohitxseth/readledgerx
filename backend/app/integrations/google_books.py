import httpx
import uuid
from app.schemas.models import Book
from app.domain.mappers import BookMapper
from app.core.exceptions import ExternalServiceError
from app.config.settings import settings


class GoogleBooksClient:
    BASE_URL = "https://www.googleapis.com/books/v1/volumes"
    DEFAULT_PAGE_COUNT = 500

    async def search_books(
        self, query: str, search_by: str | None = None, max_results: int = 10
    ) -> list[Book]:
        if search_by == "author":
            search_query = f"inauthor:{query}"
        elif search_by == "title":
            search_query = f"intitle:{query}"
        else:
            search_query = query

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                params = {"q": search_query, "maxResults": max_results}
                if settings.google_books_api_key:
                    params["key"] = settings.google_books_api_key

                response = await client.get(
                    self.BASE_URL,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

                if data.get("totalItems", 0) == 0:
                    return []

                books = []
                for item in data.get("items", []):
                    volume_info = item.get("volumeInfo", {})
                    if volume_info.get("language") != "en":
                        continue

                    book = BookMapper.from_google_books(item, uuid.uuid4())
                    if book.page_count <= 0:
                        book.page_count = self.DEFAULT_PAGE_COUNT
                    books.append(book)

                return books

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise ExternalServiceError("Google Books", "Rate limit exceeded. Please try again later.")
            raise ExternalServiceError("Google Books", f"HTTP {e.response.status_code}")
        except httpx.TimeoutException:
            raise ExternalServiceError("Google Books", "Request timed out")
        except ExternalServiceError:
            raise  # don't double-wrap
        except Exception as e:
            raise ExternalServiceError("Google Books", str(e))
