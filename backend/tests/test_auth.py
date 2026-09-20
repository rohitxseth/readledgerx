"""
Tests for AuthService, BcryptPasswordHasher, Argon2PasswordHasher, and TokenService.

These are all pure unit tests — no DB, no HTTP.
"""

import time
import pytest

from app.services.auth_service import AuthService
from app.services.password_hasher import BcryptPasswordHasher, Argon2PasswordHasher, IPasswordHasher
from app.services.token_service import TokenService


# ---------------------------------------------------------------------------
# IPasswordHasher protocol conformance
# ---------------------------------------------------------------------------

def test_bcrypt_satisfies_protocol():
    assert isinstance(BcryptPasswordHasher(), IPasswordHasher)


def test_argon2_satisfies_protocol():
    assert isinstance(Argon2PasswordHasher(), IPasswordHasher)


# ---------------------------------------------------------------------------
# BcryptPasswordHasher
# ---------------------------------------------------------------------------

def test_bcrypt_hash_is_not_plaintext():
    h = BcryptPasswordHasher()
    hashed = h.hash("hunter2")
    assert hashed != "hunter2"
    assert hashed.startswith("$2b$")


def test_bcrypt_verify_correct_password():
    h = BcryptPasswordHasher()
    hashed = h.hash("correct-horse-battery")
    assert h.verify("correct-horse-battery", hashed) is True


def test_bcrypt_verify_wrong_password():
    h = BcryptPasswordHasher()
    hashed = h.hash("correct-horse-battery")
    assert h.verify("wrong-guess", hashed) is False


def test_bcrypt_two_hashes_of_same_password_differ():
    # bcrypt salts every hash — same plaintext produces different ciphertext
    h = BcryptPasswordHasher()
    assert h.hash("password") != h.hash("password")


# ---------------------------------------------------------------------------
# Argon2PasswordHasher
# ---------------------------------------------------------------------------

def test_argon2_hash_and_verify():
    h = Argon2PasswordHasher()
    hashed = h.hash("s3cr3t")
    assert h.verify("s3cr3t", hashed) is True


def test_argon2_verify_wrong_password():
    h = Argon2PasswordHasher()
    hashed = h.hash("s3cr3t")
    assert h.verify("not-the-password", hashed) is False


# ---------------------------------------------------------------------------
# TokenService
# ---------------------------------------------------------------------------

def test_token_round_trip():
    svc = TokenService(secret_key="test-secret", algorithm="HS256")
    token = svc.create_token({"sub": "user-123"})
    payload = svc.decode_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"


def test_expired_token_returns_none():
    from datetime import timedelta
    svc = TokenService(secret_key="test-secret", algorithm="HS256", default_expiry_minutes=0)
    # create a token that expires in 0 minutes (already expired)
    token = svc.create_token({"sub": "user-123"}, expires_delta=timedelta(seconds=-1))
    assert svc.decode_token(token) is None


def test_tampered_token_returns_none():
    svc = TokenService(secret_key="test-secret", algorithm="HS256")
    token = svc.create_token({"sub": "user-123"})
    tampered = token[:-4] + "XXXX"
    assert svc.decode_token(tampered) is None


def test_wrong_secret_returns_none():
    svc_a = TokenService(secret_key="secret-a", algorithm="HS256")
    svc_b = TokenService(secret_key="secret-b", algorithm="HS256")
    token = svc_a.create_token({"sub": "user-123"})
    assert svc_b.decode_token(token) is None


# ---------------------------------------------------------------------------
# AuthService — wires hasher + token service
# ---------------------------------------------------------------------------

def test_auth_service_uses_injected_hasher():
    """AuthService delegates hashing to whatever IPasswordHasher is injected."""

    class UpperCaseHasher:
        """Trivial fake — just uppercases the password."""
        def hash(self, password: str) -> str:
            return password.upper()
        def verify(self, plain: str, hashed: str) -> bool:
            return plain.upper() == hashed

    svc = AuthService(hasher=UpperCaseHasher())
    assert svc.hash_password("hello") == "HELLO"
    assert svc.verify_password("hello", "HELLO") is True
    assert svc.verify_password("wrong", "HELLO") is False


def test_auth_service_create_and_decode_token():
    token_svc = TokenService(secret_key="unit-test-key", algorithm="HS256")
    auth = AuthService(token_service=token_svc)

    token = auth.create_access_token({"sub": "abc"})
    payload = auth.decode_token(token)
    assert payload["sub"] == "abc"


def test_auth_service_decode_token_uses_own_token_service():
    """decode_token must use the injected token_service, not a hidden singleton."""
    svc_a = TokenService(secret_key="key-a", algorithm="HS256")
    svc_b = TokenService(secret_key="key-b", algorithm="HS256")

    auth_a = AuthService(token_service=svc_a)
    auth_b = AuthService(token_service=svc_b)

    token_from_a = auth_a.create_access_token({"sub": "user"})

    # auth_b can't decode a token signed with key-a
    assert auth_b.decode_token(token_from_a) is None
    # but auth_a can
    assert auth_a.decode_token(token_from_a) is not None
