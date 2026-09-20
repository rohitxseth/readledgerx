from dataclasses import dataclass


@dataclass(frozen=True)
class UserRegisteredEvent:
    user_id: str
    email: str


@dataclass(frozen=True)
class UserLoggedInEvent:
    user_id: str
    email: str
