"""REST adapter for the book catalogue.

A second adapter over the same services the chat agent uses. Each route
parses its request, calls one service operation, and returns the result —
every rule lives in the service, so the two adapters can't disagree.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import AliasChoices, BaseModel, Field, model_validator

from app.core.dependencies import (
    get_book_service,
    get_current_user,
    get_reading_service,
)
from app.schemas.models import Book, TrackingResult, User
from app.services.book_service import BookService
from app.services.reading_service import ReadingService

router = APIRouter(prefix="/books", tags=["books"])


class BookReference(BaseModel):
    """A book, by title or by exact catalogue volume id (which wins if both)."""

    title: str | None = None
    # Accept the name the search results use, too, so a client can post back
    # exactly what it received.
    google_volume_id: str | None = Field(
        None, validation_alias=AliasChoices("google_volume_id", "google_books_id")
    )

    @model_validator(mode="after")
    def _names_a_book(self) -> "BookReference":
        if not (self.title or self.google_volume_id):
            raise ValueError("Give a title or a google_volume_id.")
        return self


class TrackRequest(BookReference):
    pages: int = 0


@router.get(
    "/search",
    response_model=list[Book],
    dependencies=[Depends(get_current_user)],
)
async def search_books(
    q: str = Query(..., description="An author, title, genre or topic."),
    search_by: str | None = Query(None, description="'title' or 'author' to narrow the search."),
    book_service: BookService = Depends(get_book_service),
):
    return await book_service.search(q, search_by=search_by)


@router.post("/track", response_model=TrackingResult)
async def track_book(
    body: TrackRequest,
    current_user: User = Depends(get_current_user),
    book_service: BookService = Depends(get_book_service),
    reading_service: ReadingService = Depends(get_reading_service),
):
    book = await book_service.resolve(body.title, volume_id=body.google_volume_id)
    return await reading_service.start_tracking(current_user.id, book.id, pages=body.pages)
