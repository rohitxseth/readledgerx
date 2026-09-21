from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import chat_messages, chat_sessions


async def create_session(
    conn: AsyncConnection, user_id: UUID, name: str | None = None
) -> dict:
    now = datetime.now(UTC)
    stmt = (
        insert(chat_sessions)
        .values(
            user_id=user_id,
            name=name or f"Chat — {now:%Y-%m-%d %H:%M}",
            metadata={},
            message_count=0,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        .returning(chat_sessions)
    )
    return dict((await conn.execute(stmt)).one()._mapping)


async def load_session(conn: AsyncConnection, session_id: UUID) -> dict | None:
    stmt = select(chat_sessions).where(
        chat_sessions.c.id == session_id, chat_sessions.c.is_active.is_(True)
    )
    row = (await conn.execute(stmt)).first()
    return dict(row._mapping) if row else None


async def update_session(
    conn: AsyncConnection, session_id: UUID, updates: dict
) -> None:
    await conn.execute(
        update(chat_sessions)
        .where(chat_sessions.c.id == session_id)
        .values(updated_at=datetime.now(UTC), **updates)
    )


async def get_user_sessions(
    conn: AsyncConnection, user_id: UUID, limit: int = 50
) -> list[dict]:
    stmt = (
        select(
            chat_sessions.c.id,
            chat_sessions.c.name,
            chat_sessions.c.message_count,
            chat_sessions.c.created_at,
            chat_sessions.c.updated_at,
        )
        .where(chat_sessions.c.user_id == user_id, chat_sessions.c.is_active.is_(True))
        .order_by(desc(chat_sessions.c.updated_at))
        .limit(limit)
    )
    return [dict(row._mapping) for row in await conn.execute(stmt)]


async def add_message(
    conn: AsyncConnection,
    session_id: UUID,
    role: str,
    content: str | None = None,
    message_type: str = "text",
    ui_payload: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    message_id = (
        await conn.execute(
            insert(chat_messages)
            .values(
                session_id=session_id,
                role=role,
                content=content,
                message_type=message_type,
                ui_payload=ui_payload,
                created_at=now,
            )
            .returning(chat_messages.c.id)
        )
    ).scalar_one()
    await conn.execute(
        update(chat_sessions)
        .where(chat_sessions.c.id == session_id)
        .values(message_count=chat_sessions.c.message_count + 1, updated_at=now)
    )
    return str(message_id)


async def get_conversation_history(
    conn: AsyncConnection, session_id: UUID, limit: int = 50
) -> list[dict]:
    stmt = (
        select(chat_messages)
        .where(chat_messages.c.session_id == session_id)
        .order_by(desc(chat_messages.c.created_at))
        .limit(limit)
    )
    messages = [dict(row._mapping) for row in await conn.execute(stmt)]
    messages.reverse()
    return messages
