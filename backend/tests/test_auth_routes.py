"""
Registration and login over HTTP, with the repositories swapped for fakes.

Covers the fixes for emails being case-sensitive, over-long passwords
crashing bcrypt with a 500, and the registration audit row being lost.
"""

import httpx
import pytest

from app.core.dependencies import (
    get_audit_repository,
    get_auth_service,
    get_user_repository,
)
from app.main import app
from app.services.auth_service import AuthService
from tests.conftest import FakeAuditRepository, FakeUserRepository


class _PlainHasher:
    """Keeps these tests fast; bcrypt itself is covered in test_auth.py."""

    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"hashed:{plain}"


@pytest.fixture
def repos():
    users, audit = FakeUserRepository(), FakeAuditRepository()
    app.dependency_overrides = {
        get_user_repository: lambda: users,
        get_audit_repository: lambda: audit,
        get_auth_service: lambda: AuthService(hasher=_PlainHasher()),
    }
    yield users, audit
    app.dependency_overrides = {}


async def _post(path: str, **body) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body)


# ---------------------------------------------------------------------------
# Emails are case-insensitive
# ---------------------------------------------------------------------------


async def test_registration_stores_the_email_lowercased(repos):
    users, _ = repos
    r = await _post("/auth/register", email="Reader@Example.COM", password="pw")

    assert r.status_code == 201
    assert r.json()["user_email"] == "reader@example.com"
    assert list(users.users) == ["reader@example.com"]


async def test_login_ignores_email_case(repos):
    await _post("/auth/register", email="reader@example.com", password="pw")
    r = await _post("/auth/login", email="READER@Example.com", password="pw")
    assert r.status_code == 200


async def test_the_same_email_in_another_case_is_already_registered(repos):
    await _post("/auth/register", email="reader@example.com", password="pw")
    r = await _post("/auth/register", email="Reader@Example.com", password="pw")

    assert r.status_code == 400
    assert r.json()["detail"] == "Email already registered"


# ---------------------------------------------------------------------------
# bcrypt's limit is 72 bytes, not 72 characters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/auth/register", "/auth/login"])
async def test_a_password_over_72_bytes_is_a_422_not_a_500(repos, path):
    password = "é" * 37  # 37 characters, 74 bytes
    r = await _post(path, email="reader@example.com", password=password)

    assert r.status_code == 422
    assert "72 bytes" in r.json()["detail"][0]["msg"]


async def test_a_72_byte_password_works_with_real_bcrypt(repos):
    app.dependency_overrides[get_auth_service] = lambda: AuthService()
    password = "é" * 36  # exactly 72 bytes

    registered = await _post(
        "/auth/register", email="reader@example.com", password=password
    )
    logged_in = await _post(
        "/auth/login", email="reader@example.com", password=password
    )

    assert registered.status_code == 201
    assert logged_in.status_code == 200


# ---------------------------------------------------------------------------
# Audit rows are written in the request, not by a background handler
# ---------------------------------------------------------------------------


async def test_registration_and_login_are_audited(repos):
    users, audit = repos
    await _post("/auth/register", email="reader@example.com", password="pw")
    await _post("/auth/login", email="reader@example.com", password="pw")

    user_id = users.users["reader@example.com"].id
    assert audit.records == [
        (user_id, "user_registered", {"email": "reader@example.com"}),
        (user_id, "user_logged_in", {"email": "reader@example.com"}),
    ]


async def test_a_failed_audit_write_fails_the_registration(repos):
    """The audit row shares the registration's transaction, so its failure is
    the request's failure rather than something logged and forgotten."""

    class BrokenAudit:
        async def record(self, user_id, action, details):
            raise RuntimeError("audit_log unavailable")

    app.dependency_overrides[get_audit_repository] = BrokenAudit
    with pytest.raises(RuntimeError, match="audit_log unavailable"):
        await _post("/auth/register", email="reader@example.com", password="pw")
