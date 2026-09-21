import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError

from app.core.dependencies import get_auth_service, get_user_repository
from app.domain.value_objects import Email
from app.events.event_bus import event_bus
from app.events.user_events import UserLoggedInEvent, UserRegisteredEvent
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    # bcrypt rejects passwords longer than 72 bytes.
    password: str = Field(max_length=72)


class AuthResponse(BaseModel):
    token: str
    user_id: str
    user_email: str


@router.post(
    "/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    request: Credentials,
    user_repo: UserRepository = Depends(get_user_repository),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        Email(request.email)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address"
        ) from None

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

    token = auth_service.create_access_token({"sub": str(user.id)})
    await event_bus.publish(UserRegisteredEvent(user_id=str(user.id), email=user.email))
    return AuthResponse(token=token, user_id=str(user.id), user_email=user.email)


@router.post("/login", response_model=AuthResponse)
async def login(
    request: Credentials,
    user_repo: UserRepository = Depends(get_user_repository),
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
    token = auth_service.create_access_token({"sub": str(user.id)})
    await event_bus.publish(UserLoggedInEvent(user_id=str(user.id), email=user.email))
    return AuthResponse(token=token, user_id=str(user.id), user_email=user.email)
