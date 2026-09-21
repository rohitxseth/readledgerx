import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.exc import IntegrityError

from app.core.dependencies import (
    get_audit_repository,
    get_auth_service,
    get_user_repository,
)
from app.interfaces.repository_interfaces import IAuditRepository, IUserRepository
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_BCRYPT_MAX_BYTES = 72


class Credentials(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str) -> str:
        return email.lower()

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, password: str) -> str:
        # bcrypt rejects longer input; the limit is bytes, not characters.
        if len(password.encode()) > _BCRYPT_MAX_BYTES:
            raise ValueError(
                "Password is too long. Use at most 72 bytes; accented letters "
                "and emoji take more than one byte each."
            )
        return password


class AuthResponse(BaseModel):
    token: str
    user_id: str
    user_email: str


@router.post(
    "/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    request: Credentials,
    user_repo: IUserRepository = Depends(get_user_repository),
    audit: IAuditRepository = Depends(get_audit_repository),
    auth_service: AuthService = Depends(get_auth_service),
):
    if await user_repo.get_by_email(request.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    try:
        user = await user_repo.create(
            request.email, auth_service.hash_password(request.password)
        )
    except IntegrityError:
        # Lost a race with a concurrent registration for the same email.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        ) from None

    # Shares the request's connection with user_repo, so the audit row commits
    # together with the new user or not at all.
    await audit.record(user.id, "user_registered", {"email": user.email})
    token = auth_service.create_access_token({"sub": str(user.id)})
    return AuthResponse(token=token, user_id=str(user.id), user_email=user.email)


@router.post("/login", response_model=AuthResponse)
async def login(
    request: Credentials,
    user_repo: IUserRepository = Depends(get_user_repository),
    audit: IAuditRepository = Depends(get_audit_repository),
    auth_service: AuthService = Depends(get_auth_service),
):
    user = await user_repo.get_by_email(request.email)
    if not (
        user
        and user.hashed_password
        and auth_service.verify_password(request.password, user.hashed_password)
    ):
        logger.warning("Failed login for %s", request.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    await user_repo.update_last_login(user.id)
    await audit.record(user.id, "user_logged_in", {"email": user.email})
    token = auth_service.create_access_token({"sub": str(user.id)})
    return AuthResponse(token=token, user_id=str(user.id), user_email=user.email)
