from typing import Protocol, runtime_checkable

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


@runtime_checkable
class IPasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, plain: str, hashed: str) -> bool: ...


class BcryptPasswordHasher:
    def hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def verify(self, plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(plain.encode(), hashed.encode())


class Argon2PasswordHasher:
    def hash(self, password: str) -> str:
        return PasswordHasher().hash(password)

    def verify(self, plain: str, hashed: str) -> bool:
        try:
            return PasswordHasher().verify(hashed, plain)
        except VerifyMismatchError:
            return False
