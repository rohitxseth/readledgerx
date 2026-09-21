"""REST adapter for reading progress — same services as the chat agent."""

import datetime as dt

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import (
    get_book_service,
    get_current_user,
    get_reading_service,
)
from app.routers.books import BookReference
from app.schemas.models import (
    BookProgress,
    LogAction,
    ProgressFilter,
    ProgressSort,
    ReadingLogResult,
    UndoResult,
    User,
)
from app.services.book_service import BookService
from app.services.reading_service import ReadingService

router = APIRouter(prefix="/reading", tags=["reading"])
progress_router = APIRouter(prefix="/progress", tags=["reading"])


class LogReadingRequest(BookReference):
    action: LogAction = "add"
    pages: int | None = None
    percentage: float | None = None
    date: dt.date | None = None


@router.post("/log", response_model=ReadingLogResult)
async def log_reading(
    body: LogReadingRequest,
    current_user: User = Depends(get_current_user),
    book_service: BookService = Depends(get_book_service),
    reading_service: ReadingService = Depends(get_reading_service),
):
    book = await book_service.resolve(body.title, volume_id=body.google_volume_id)
    return await reading_service.log_reading(
        current_user.id,
        book.id,
        action=body.action,
        pages=body.pages,
        percentage=body.percentage,
        session_date=body.date,
    )


@router.delete("/last", response_model=UndoResult)
async def undo_last_log(
    current_user: User = Depends(get_current_user),
    reading_service: ReadingService = Depends(get_reading_service),
):
    return await reading_service.undo_last_log(current_user.id)


@progress_router.get("", response_model=list[BookProgress])
async def get_progress(
    filter_by: ProgressFilter | None = Query(None, alias="filter"),
    sort_by: ProgressSort | None = Query(None),
    limit: int | None = Query(None, description="At most this many books; 0 or omitted means all."),
    current_user: User = Depends(get_current_user),
    reading_service: ReadingService = Depends(get_reading_service),
):
    return await reading_service.get_all_progress(
        current_user.id, filter_by=filter_by, sort_by=sort_by, limit=limit
    )
