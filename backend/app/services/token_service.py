from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError

from app.config.settings import settings


class TokenService:
    def __init__(
        self,
        secret_key: str = settings.jwt_secret_key,
        algorithm: str = settings.algorithm,
        default_expiry_minutes: int = 60 * 24 * 7,  # 7 days
    ):
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._default_expiry_minutes = default_expiry_minutes

    def create_token(self, data: dict, expires_delta: timedelta | None = None) -> str:
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (
            expires_delta or timedelta(minutes=self._default_expiry_minutes)
        )
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, self._secret_key, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict | None:
        try:
            return jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
        except JWTError:
            return None
