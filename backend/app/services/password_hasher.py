from typing import Protocol, runtime_checkable

import bcrypt


@runtime_checkable
class IPasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, plain: str, hashed: str) -> bool: ...


class BcryptPasswordHasher:
    def hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def verify(self, plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
