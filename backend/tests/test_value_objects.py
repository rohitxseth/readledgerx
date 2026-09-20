"""
Tests for PageCount and Email value objects.

Value objects enforce domain invariants at construction time — these tests
verify the happy path and every meaningful edge case that should fail fast.
"""

import pytest
from app.domain.value_objects import PageCount, Email


# ---------------------------------------------------------------------------
# PageCount
# ---------------------------------------------------------------------------

def test_page_count_valid():
    p = PageCount(100)
    assert p.value == 100
    assert int(p) == 100


def test_page_count_zero_is_allowed():
    p = PageCount(0)
    assert p.value == 0


def test_page_count_negative_raises():
    with pytest.raises(ValueError, match="negative"):
        PageCount(-1)


def test_page_count_too_large_raises():
    with pytest.raises(ValueError, match="exceeds maximum"):
        PageCount(PageCount.MAX + 1)


def test_page_count_wrong_type_raises():
    with pytest.raises(TypeError):
        PageCount("100")  # type: ignore


def test_page_count_equality():
    assert PageCount(50) == PageCount(50)
    assert PageCount(50) != PageCount(51)


def test_page_count_repr():
    assert repr(PageCount(42)) == "PageCount(42)"


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def test_email_valid():
    e = Email("User@Example.COM")
    assert e.value == "user@example.com"  # normalised to lowercase


def test_email_strips_whitespace():
    e = Email("  hello@world.org  ")
    assert e.value == "hello@world.org"


def test_email_no_at_sign_raises():
    with pytest.raises(ValueError):
        Email("notanemail")


def test_email_no_domain_raises():
    with pytest.raises(ValueError):
        Email("user@")


def test_email_empty_raises():
    with pytest.raises(ValueError):
        Email("")


def test_email_wrong_type_raises():
    with pytest.raises(TypeError):
        Email(123)  # type: ignore


def test_email_equality():
    assert Email("a@b.com") == Email("A@B.COM")
    assert Email("a@b.com") != Email("c@d.com")


def test_email_str():
    e = Email("rohit@example.in")
    assert str(e) == "rohit@example.in"
