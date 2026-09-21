import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.exceptions import AuthenticationError, EntityNotFoundError
from app.database import get_db
from app.integrations.google_books import GoogleBooksClient
from app.repositories.book_repository import BookRepository
from app.repositories.reading_repository import ReadingRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.book_intelligence import BookIntelligenceService
from app.services.book_service import BookService
from app.services.password_hasher import BcryptPasswordHasher
from app.services.reading_service import ReadingService
from app.services.token_service import TokenService


def get_auth_service() -> AuthService:
    return AuthService(
        hasher=BcryptPasswordHasher(),
        token_service=TokenService(),
    )

security = HTTPBearer()


async def get_db_connection():
    async for conn in get_db():
        yield conn


def get_user_repository(conn: AsyncConnection = Depends(get_db_connection)) -> UserRepository:
    return UserRepository(conn)


def get_book_repository(conn: AsyncConnection = Depends(get_db_connection)) -> BookRepository:
    return BookRepository(conn)


def get_reading_repository(conn: AsyncConnection = Depends(get_db_connection)) -> ReadingRepository:
    return ReadingRepository(conn)


def get_book_service(conn: AsyncConnection = Depends(get_db_connection)) -> BookService:
    return BookService(
        repo=BookRepository(conn),
        search_client=GoogleBooksClient(),
        intelligence=BookIntelligenceService(),
    )


def get_reading_service(conn: AsyncConnection = Depends(get_db_connection)) -> ReadingService:
    return ReadingService(
        reading_repo=ReadingRepository(conn),
        book_repo=BookRepository(conn),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_repo: UserRepository = Depends(get_user_repository),
):
    from app.services.auth_service import decode_token
    token = credentials.credentials
    payload = decode_token(token)

    if not payload:
        raise AuthenticationError("Invalid authentication credentials")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise AuthenticationError("Invalid token payload")

    try:
        user_id = uuid.UUID(user_id_str) if isinstance(user_id_str, str) else user_id_str
    except (ValueError, AttributeError):
        raise AuthenticationError("Invalid user ID format") from None

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise EntityNotFoundError("User not found")

    return user
