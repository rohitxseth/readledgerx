import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text as sa_text

from app.config.logging_config import setup_logging
from app.core.exceptions import (
    AuthenticationError,
    BusinessLogicError,
    DomainException,
    EntityNotFoundError,
    ExternalServiceError,
)
from app.database import async_engine
from app.events.event_bus import event_bus
from app.events.handlers import on_user_logged_in, on_user_registered
from app.events.user_events import UserLoggedInEvent, UserRegisteredEvent
from app.routers import (
    auth_router,
    books_router,
    chat_router,
    progress_router,
    reading_router,
)

setup_logging(level=logging.INFO)

logger = logging.getLogger(__name__)

event_bus.subscribe(UserRegisteredEvent, on_user_registered)
event_bus.subscribe(UserLoggedInEvent, on_user_logged_in)

app = FastAPI(title="ReadLedger API")

_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(EntityNotFoundError)
async def entity_not_found_handler(request: Request, exc: EntityNotFoundError):
    return JSONResponse(status_code=404, content={"detail": exc.message})


@app.exception_handler(AuthenticationError)
async def auth_error_handler(request: Request, exc: AuthenticationError):
    return JSONResponse(status_code=401, content={"detail": exc.message})


@app.exception_handler(BusinessLogicError)
async def business_logic_handler(request: Request, exc: BusinessLogicError):
    return JSONResponse(status_code=400, content={"detail": exc.message})


@app.exception_handler(DomainException)
async def domain_exception_handler(request: Request, exc: DomainException):
    return JSONResponse(status_code=400, content={"detail": exc.message})


@app.exception_handler(ExternalServiceError)
async def external_service_handler(request: Request, exc: ExternalServiceError):
    return JSONResponse(status_code=502, content={"detail": exc.message})


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(books_router)
app.include_router(reading_router)
app.include_router(progress_router)


@app.get("/health")
async def health():
    db_ok = False
    try:
        async with async_engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
            db_ok = True
    except Exception:
        logger.warning("Health check: database unreachable", exc_info=True)

    status = "healthy" if db_ok else "degraded"
    return {"status": status, "database": "connected" if db_ok else "unreachable"}
