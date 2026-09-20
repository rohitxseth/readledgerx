import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as sa_text

from app.routers import auth_router, chat_router
from app.config.logging_config import setup_logging
from app.config.settings import settings
from app.core.exceptions import (
    DomainException, EntityNotFoundError, AuthenticationError,
    BusinessLogicError, ExternalServiceError,
)
from app.database import async_engine
from app.events.event_bus import event_bus
from app.events.user_events import UserRegisteredEvent, UserLoggedInEvent
from app.events.handlers import on_user_registered, on_user_logged_in

setup_logging(level=logging.INFO)

logger = logging.getLogger(__name__)

event_bus.subscribe(UserRegisteredEvent, on_user_registered)
event_bus.subscribe(UserLoggedInEvent, on_user_logged_in)

app = FastAPI(title="ReadLedger API")

# In production, pin this to actual frontend origins instead of "*".
# allow_credentials=True with allow_origins=["*"] is rejected by browsers anyway.
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


@app.get("/health")
async def health():
    """Checks that the API is up and the DB is reachable."""
    db_ok = False
    try:
        async with async_engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
            db_ok = True
    except Exception:
        logger.warning("Health check: database unreachable", exc_info=True)

    status = "healthy" if db_ok else "degraded"
    return {"status": status, "database": "connected" if db_ok else "unreachable"}
