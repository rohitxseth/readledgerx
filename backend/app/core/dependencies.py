from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config.llm_config import get_langchain_llm
from app.core.exceptions import AuthenticationError, EntityNotFoundError
from app.database import get_db
from app.integrations.google_books import GoogleBooksClient
from app.interfaces.repository_interfaces import IUserRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.book_repository import BookRepository
from app.repositories.reading_repository import ReadingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.models import User
from app.services.auth_service import AuthService
from app.services.book_intelligence import BookIntelligenceService
from app.services.book_service import BookService
from app.services.password_hasher import BcryptPasswordHasher
from app.services.reading_service import ReadingService
from app.services.token_service import TokenService

security = HTTPBearer()


def get_auth_service() -> AuthService:
    return AuthService(hasher=BcryptPasswordHasher(), token_service=TokenService())


def get_user_repository(conn: AsyncConnection = Depends(get_db)) -> UserRepository:
    return UserRepository(conn)


def get_audit_repository(conn: AsyncConnection = Depends(get_db)) -> AuditRepository:
    return AuditRepository(conn)


def get_book_service(conn: AsyncConnection = Depends(get_db)) -> BookService:
    return BookService(
        repo=BookRepository(conn),
        search_client=GoogleBooksClient(),
        intelligence=BookIntelligenceService(get_langchain_llm()),
    )


def get_reading_service(conn: AsyncConnection = Depends(get_db)) -> ReadingService:
    return ReadingService(
        reading_repo=ReadingRepository(conn),
        book_repo=BookRepository(conn),
    )


async def authenticate(token: str, user_repo: IUserRepository) -> User:
    payload = get_auth_service().decode_token(token)
    if not payload:
        raise AuthenticationError("Invalid authentication credentials")

    subject = payload.get("sub")
    if not subject:
        raise AuthenticationError("Invalid token payload")

    try:
        user_id = UUID(subject)
    except ValueError:
        raise AuthenticationError("Invalid user ID format") from None

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise EntityNotFoundError("User not found")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_repo: UserRepository = Depends(get_user_repository),
) -> User:
    return await authenticate(credentials.credentials, user_repo)
