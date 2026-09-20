from __future__ import annotations

from app.services.password_hasher import IPasswordHasher, BcryptPasswordHasher
from app.services.token_service import TokenService


class AuthService:
    def __init__(
        self,
        hasher: IPasswordHasher | None = None,
        token_service: TokenService | None = None,
    ):
        self._hasher = hasher or BcryptPasswordHasher()
        self._token_service = token_service or TokenService()

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, plain: str, hashed: str) -> bool:
        return self._hasher.verify(plain, hashed)

    def create_access_token(self, data: dict) -> str:
        return self._token_service.create_token(data)

    def decode_token(self, token: str) -> dict | None:
        return self._token_service.decode_token(token)


# Module-level shortcut for places that don't have the DI instance handy
# (e.g. WebSocket auth where we can't use FastAPI Depends).
_shared = AuthService()


def decode_token(token: str) -> dict | None:
    return _shared.decode_token(token)
