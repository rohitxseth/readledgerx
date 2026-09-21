import json
import logging
from datetime import UTC, datetime

from sqlalchemy import desc, insert, select, update

from app.database import async_engine
from app.models import chat_messages, chat_sessions

logger = logging.getLogger(__name__)

# Every function here logs and swallows database errors, returning an empty
# value instead, so a chat turn degrades rather than failing outright. That
# includes a malformed session id from the client, which load_session treats
# as "no such session".


def parse_metadata(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def create_session(user_id: str, session_name: str | None = None) -> dict:
    now = datetime.now(UTC)
    try:
        async with async_engine.begin() as conn:
            stmt = (
                insert(chat_sessions)
                .values(
                    user_id=user_id,
                    name=session_name or f"Chat — {now.strftime('%Y-%m-%d %H:%M')}",
                    metadata="{}",
                    message_count=0,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                .returning(chat_sessions)
            )
            row = (await conn.execute(stmt)).first()
            return dict(row._mapping) if row else {}
    except Exception:
        logger.exception("Failed to create chat session")
        return {}


async def load_session(session_id: str) -> dict:
    try:
        async with async_engine.begin() as conn:
            stmt = (
                select(chat_sessions)
                .where(chat_sessions.c.id == session_id)
                .where(chat_sessions.c.is_active.is_(True))
            )
            row = (await conn.execute(stmt)).first()
            return dict(row._mapping) if row else {}
    except Exception:
        logger.exception("Failed to load chat session")
        return {}


async def update_session(session_id: str, updates: dict) -> None:
    try:
        stmt = (
            update(chat_sessions)
            .where(chat_sessions.c.id == session_id)
            .values(updated_at=datetime.now(UTC), **updates)
        )
        async with async_engine.begin() as conn:
            await conn.execute(stmt)
    except Exception:
        logger.exception("Failed to update chat session")


async def get_user_sessions(user_id: str, limit: int = 50) -> list[dict]:
    try:
        async with async_engine.begin() as conn:
            stmt = (
                select(
                    chat_sessions.c.id,
                    chat_sessions.c.name,
                    chat_sessions.c.message_count,
                    chat_sessions.c.created_at,
                    chat_sessions.c.updated_at,
                )
                .where(chat_sessions.c.user_id == user_id)
                .where(chat_sessions.c.is_active.is_(True))
                .order_by(desc(chat_sessions.c.updated_at))
                .limit(limit)
            )
            result = await conn.execute(stmt)
            return [dict(row._mapping) for row in result]
    except Exception:
        logger.exception("Failed to list chat sessions")
        return []


async def add_message(
    session_id: str,
    role: str,
    content: str | None = None,
    message_type: str = "text",
    ui_payload: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    try:
        async with async_engine.begin() as conn:
            stmt = (
                insert(chat_messages)
                .values(
                    session_id=session_id,
                    role=role,
                    content=content,
                    message_type=message_type,
                    ui_payload=json.dumps(ui_payload) if ui_payload else None,
                    created_at=now,
                )
                .returning(chat_messages.c.id)
            )
            row = (await conn.execute(stmt)).first()
            if not row:
                return ""

            await conn.execute(
                update(chat_sessions)
                .where(chat_sessions.c.id == session_id)
                .values(message_count=chat_sessions.c.message_count + 1, updated_at=now)
            )
            return str(row[0])
    except Exception:
        logger.exception("Failed to save chat message")
        return ""


async def get_conversation_history(session_id: str, limit: int = 50) -> list[dict]:
    try:
        async with async_engine.begin() as conn:
            stmt = (
                select(chat_messages)
                .where(chat_messages.c.session_id == session_id)
                .order_by(chat_messages.c.created_at)
                .limit(limit)
            )
            result = await conn.execute(stmt)
            messages = [dict(row._mapping) for row in result]
    except Exception:
        logger.exception("Failed to load chat history")
        return []

    # ui_payload is written with json.dumps, so it can come back as a string.
    for message in messages:
        if isinstance(message["ui_payload"], str):
            try:
                message["ui_payload"] = json.loads(message["ui_payload"])
            except json.JSONDecodeError:
                pass
    return messages
