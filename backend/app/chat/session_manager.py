"""Session manager — chat session CRUD backed by SQLAlchemy Core.

Manages conversation sessions and message persistence for the chat system.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, insert, update, desc

from app.database import async_engine
from app.models import chat_sessions, chat_messages

logger = logging.getLogger(__name__)

_ALLOWED_SESSION_COLUMNS = frozenset({"metadata", "message_count", "is_active", "name"})


async def create_session(user_id: str, session_name: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    if not session_name:
        session_name = f"Chat — {now.strftime('%Y-%m-%d %H:%M')}"

    try:
        async with async_engine.begin() as conn:
            stmt = (
                insert(chat_sessions)
                .values(
                    user_id=user_id,
                    name=session_name,
                    metadata="{}",
                    message_count=0,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                .returning(chat_sessions)
            )
            result = await conn.execute(stmt)
            row = result.first()
            if row:
                session = dict(row._mapping)
                logger.info("session: created %s for user=%s", session["id"], user_id)
                return session
            return {}
    except Exception as e:
        logger.error("Error creating session: %s", e, exc_info=True)
        return {}


async def load_session(session_id: str) -> dict:
    try:
        async with async_engine.begin() as conn:
            stmt = (
                select(chat_sessions)
                .where(chat_sessions.c.id == session_id)
                .where(chat_sessions.c.is_active == True)
            )
            result = await conn.execute(stmt)
            row = result.first()
            return dict(row._mapping) if row else {}
    except Exception as e:
        logger.error("Error loading session: %s", e, exc_info=True)
        return {}


async def update_session(session_id: str, updates: dict) -> bool:
    try:
        values = {"updated_at": datetime.now(timezone.utc)}
        for key, value in updates.items():
            if key not in _ALLOWED_SESSION_COLUMNS:
                logger.warning("Skipping unknown column in session update: %s", key)
                continue
            values[key] = value

        stmt = (
            update(chat_sessions)
            .where(chat_sessions.c.id == session_id)
            .values(**values)
        )
        async with async_engine.begin() as conn:
            await conn.execute(stmt)
        return True
    except Exception as e:
        logger.error("Error updating session: %s", e, exc_info=True)
        return False


async def get_user_sessions(user_id: str, limit: int = 50) -> list:
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
                .where(chat_sessions.c.is_active == True)
                .order_by(desc(chat_sessions.c.updated_at))
                .limit(limit)
            )
            result = await conn.execute(stmt)
            return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.error("Error getting user sessions: %s", e, exc_info=True)
        return []


async def add_message(
    session_id: str,
    role: str,
    content: str | None = None,
    message_type: str = "text",
    ui_payload: dict | None = None,
) -> str:
    try:
        ui_json = json.dumps(ui_payload) if ui_payload else None
        now = datetime.now(timezone.utc)

        async with async_engine.begin() as conn:
            stmt = (
                insert(chat_messages)
                .values(
                    session_id=session_id,
                    role=role,
                    content=content,
                    message_type=message_type,
                    ui_payload=ui_json,
                    created_at=now,
                )
                .returning(chat_messages.c.id)
            )
            result = await conn.execute(stmt)
            row = result.first()
            message_id = str(row[0]) if row else ""

            if message_id:
                # bump the message counter on the parent session
                await conn.execute(
                    update(chat_sessions)
                    .where(chat_sessions.c.id == session_id)
                    .values(
                        message_count=chat_sessions.c.message_count + 1,
                        updated_at=now,
                    )
                )
                logger.info(
                    "session: added %s message %s to session %s",
                    role, message_id, session_id,
                )
            return message_id

    except Exception as e:
        logger.error("Error adding message: %s", e, exc_info=True)
        return ""


async def get_conversation_history(session_id: str, limit: int = 50) -> list:
    try:
        async with async_engine.begin() as conn:
            stmt = (
                select(chat_messages)
                .where(chat_messages.c.session_id == session_id)
                .order_by(chat_messages.c.created_at)
                .limit(limit)
            )
            result = await conn.execute(stmt)
            rows = []
            for row in result:
                data = dict(row._mapping)
                if data.get("ui_payload") and isinstance(data["ui_payload"], str):
                    try:
                        data["ui_payload"] = json.loads(data["ui_payload"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                rows.append(data)
            return rows
    except Exception as e:
        logger.error("Error getting conversation history: %s", e, exc_info=True)
        return []
