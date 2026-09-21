from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import audit_log


class AuditRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def record(self, user_id: UUID, action: str, details: dict) -> None:
        await self.conn.execute(
            insert(audit_log).values(user_id=user_id, action=action, details=details)
        )
