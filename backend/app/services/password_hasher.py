from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IPasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, plain: str, hashed: str) -> bool: ...


class BcryptPasswordHasher:
    """Default hasher. Good enough for most use cases, fast-ish."""

    def hash(self, password: str) -> str:
        import bcrypt
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def verify(self, plain: str, hashed: str) -> bool:
        import bcrypt
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


class Argon2PasswordHasher:
    """Memory-hard hasher. Better resistance to GPU/ASIC brute-forcing
    compared to bcrypt. Use for higher-security requirements."""

    def hash(self, password: str) -> str:
        from argon2 import PasswordHasher
        return PasswordHasher().hash(password)

    def verify(self, plain: str, hashed: str) -> bool:
        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError
        try:
            return PasswordHasher().verify(hashed, plain)
        except VerifyMismatchError:
            return False
