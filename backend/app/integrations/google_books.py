from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import httpx

from app.config.settings import settings
from app.core.exceptions import ExternalServiceError
from app.domain.mappers import BookMapper
from app.schemas.models import Book

_SEARCH_PREFIXES = {"author": "inauthor:", "title": "intitle:"}


@contextmanager
def _as_external_service_error() -> Iterator[None]:
    try:
        yield
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise ExternalServiceError(
                "Google Books", "Rate limit exceeded. Please try again later."
            ) from e
        raise ExternalServiceError(
            "Google Books", f"HTTP {e.response.status_code}"
        ) from e
    except httpx.TimeoutException as e:
        raise ExternalServiceError("Google Books", "Request timed out") from e
    except Exception as e:
        raise ExternalServiceError("Google Books", str(e)) from e


class GoogleBooksClient:
    BASE_URL = "https://www.googleapis.com/books/v1/volumes"
    # Some volumes have no pageCount, and progress needs a nonzero total.
    DEFAULT_PAGE_COUNT = 500

    async def search_books(
        self, query: str, search_by: str | None = None, max_results: int = 10
    ) -> list[Book]:
        params = {
            "q": _SEARCH_PREFIXES.get(search_by, "") + query,
            "maxResults": max_results,
        }
        with _as_external_service_error():
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    self.BASE_URL, params=self._with_key(params)
                )
                response.raise_for_status()
                items = response.json().get("items", [])
                return [
                    self._to_book(item)
                    for item in items
                    if item.get("volumeInfo", {}).get("language") == "en"
                ]

    async def get_volume(self, volume_id: str) -> Book | None:
        # No language filter: the caller already chose this exact volume.
        with _as_external_service_error():
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/{volume_id}", params=self._with_key({})
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return self._to_book(response.json())

    @staticmethod
    def _with_key(params: dict) -> dict:
        if settings.google_books_api_key:
            return {**params, "key": settings.google_books_api_key}
        return params

    def _to_book(self, item: dict) -> Book:
        # One normalisation for both paths, so a volume gets the same page count
        # whether it arrived via search or via a direct lookup.
        book = BookMapper.from_google_books(item, uuid4())
        if book.page_count <= 0:
            book.page_count = self.DEFAULT_PAGE_COUNT
        return book
