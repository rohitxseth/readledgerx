import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.exceptions import (
    AuthenticationError,
    BusinessLogicError,
    DomainException,
    EntityNotFoundError,
    ExternalServiceError,
)
from app.database import async_engine
from app.routers import auth, books, chat, reading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="ReadLedger API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(EntityNotFoundError)
async def entity_not_found_handler(
    request: Request, exc: EntityNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": exc.message})


@app.exception_handler(AuthenticationError)
async def auth_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": exc.message})


@app.exception_handler(BusinessLogicError)
async def business_logic_handler(
    request: Request, exc: BusinessLogicError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": exc.message})


@app.exception_handler(DomainException)
async def domain_exception_handler(
    request: Request, exc: DomainException
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": exc.message})


@app.exception_handler(ExternalServiceError)
async def external_service_handler(
    request: Request, exc: ExternalServiceError
) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": exc.message})


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(books.router)
app.include_router(reading.router)
app.include_router(reading.progress_router)


@app.get("/health")
async def health():
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Health check: database unreachable", exc_info=True)
        return {"status": "degraded", "database": "unreachable"}
    return {"status": "healthy", "database": "connected"}
