from __future__ import annotations

import re


class PageCount:

    MAX = 100_000

    def __init__(self, value: int) -> None:
        if not isinstance(value, int):
            raise TypeError(f"PageCount must be an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"PageCount cannot be negative, got {value}")
        if value > self.MAX:
            raise ValueError(f"PageCount {value} exceeds maximum {self.MAX}")
        self._value = value

    @property
    def value(self) -> int:
        return self._value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PageCount):
            return self._value == other._value
        return NotImplemented

    def __repr__(self) -> str:
        return f"PageCount({self._value})"

    def __int__(self) -> int:
        return self._value


class Email:

    _PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"Email must be a str, got {type(value).__name__}")
        normalised = value.strip().lower()
        if not self._PATTERN.match(normalised):
            raise ValueError(f"Invalid email address: '{value}'")
        self._value = normalised

    @property
    def value(self) -> str:
        return self._value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Email):
            return self._value == other._value
        return NotImplemented

    def __repr__(self) -> str:
        return f"Email({self._value!r})"

    def __str__(self) -> str:
        return self._value
