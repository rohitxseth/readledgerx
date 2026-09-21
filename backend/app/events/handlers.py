import json
from datetime import UTC, datetime

from sqlalchemy import text

from app.database import async_engine
from app.events.user_events import UserLoggedInEvent, UserRegisteredEvent


async def on_user_registered(event: UserRegisteredEvent) -> None:
    await _write_audit_log("user_registered", event.user_id, {"email": event.email})


async def on_user_logged_in(event: UserLoggedInEvent) -> None:
    await _write_audit_log("user_logged_in", event.user_id, {"email": event.email})


async def _write_audit_log(action: str, user_id: str, details: dict) -> None:
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_log (user_id, action, details, created_at) "
                "VALUES (:user_id, :action, :details, :ts)"
            ),
            {
                "user_id": user_id,
                "action": action,
                "details": json.dumps(details),
                "ts": datetime.now(UTC),
            },
        )
