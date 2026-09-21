from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.mappers import UserMapper
from app.models import users
from app.schemas.models import User


class UserRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def get_by_id(self, user_id: UUID) -> User | None:
        stmt = select(users).where(users.c.id == user_id)
        row = (await self.conn.execute(stmt)).first()
        return UserMapper.from_db(dict(row._mapping)) if row else None

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(users).where(users.c.email == email)
        row = (await self.conn.execute(stmt)).first()
        return UserMapper.from_db(dict(row._mapping)) if row else None

    async def create(self, email: str, hashed_password: str) -> User:
        stmt = (
            insert(users)
            .values(email=email, password_hash=hashed_password)
            .returning(users)
        )
        row = (await self.conn.execute(stmt)).first()
        return UserMapper.from_db(dict(row._mapping))

    async def update_last_login(self, user_id: UUID) -> None:
        stmt = (
            update(users)
            .where(users.c.id == user_id)
            .values(last_login_at=datetime.now(UTC))
        )
        await self.conn.execute(stmt)
