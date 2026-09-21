from app.services.password_hasher import IPasswordHasher
from app.services.token_service import TokenService


class AuthService:
    def __init__(self, hasher: IPasswordHasher, token_service: TokenService):
        self._hasher = hasher
        self._token_service = token_service

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, plain: str, hashed: str) -> bool:
        return self._hasher.verify(plain, hashed)

    def create_access_token(self, data: dict) -> str:
        return self._token_service.create_token(data)

    def decode_token(self, token: str) -> dict | None:
        return self._token_service.decode_token(token)
