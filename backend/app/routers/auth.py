import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError

from app.core.dependencies import get_auth_service, get_user_repository
from app.domain.value_objects import Email
from app.events.event_bus import event_bus
from app.events.user_events import UserLoggedInEvent, UserRegisteredEvent
from app.repositories import UserRepository
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)


class AuthResponse(BaseModel):
    token: str
    user_id: str
    user_email: str


@router.post(
    "/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    request: RegisterRequest,
    user_repo: UserRepository = Depends(get_user_repository),
    auth_service: AuthService = Depends(get_auth_service),
):
    # validate email format at domain level (beyond pydantic's EmailStr)
    try:
        validated_email = Email(request.email)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email address",
        ) from None

    logger.info(f"Registration attempt for: {validated_email}")

    existing_user = await user_repo.get_by_email(request.email)
    if existing_user:
        logger.warning(f"Registration failed - email already exists: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    hashed = auth_service.hash_password(request.password)

    try:
        user = await user_repo.create(request.email, hashed)
        logger.info(f"User registered successfully: {user.email}")
    except IntegrityError:
        logger.error(f"Registration failed - integrity error: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        ) from None

    token = auth_service.create_access_token({"sub": str(user.id)})
    await event_bus.publish(UserRegisteredEvent(user_id=str(user.id), email=user.email))
    return AuthResponse(token=token, user_id=str(user.id), user_email=user.email)
@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    user_repo: UserRepository = Depends(get_user_repository),
    auth_service: AuthService = Depends(get_auth_service),
):
    logger.info(f"Login attempt for: {request.email}")

    user = await user_repo.get_by_email(request.email)
    if not user:
        logger.warning(f"Login failed - user not found: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.hashed_password or not auth_service.verify_password(
        request.password, user.hashed_password
    ):
        logger.warning(f"Login failed - invalid password: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    await user_repo.update_last_login(user.id)
    logger.info(f"Login successful: {user.email}")
    token = auth_service.create_access_token({"sub": str(user.id)})
    await event_bus.publish(UserLoggedInEvent(user_id=str(user.id), email=user.email))
    return AuthResponse(token=token, user_id=str(user.id), user_email=user.email)
