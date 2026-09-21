import logging
from datetime import UTC, datetime

from sqlalchemy import text as sa_text

from app.database import async_engine
from app.events.user_events import UserLoggedInEvent, UserRegisteredEvent

logger = logging.getLogger(__name__)


async def on_user_registered(event: UserRegisteredEvent) -> None:
    logger.info("New user registered: %s (id=%s)", event.email, event.user_id)
    await _write_audit_log("user_registered", event.user_id, {"email": event.email})


async def on_user_logged_in(event: UserLoggedInEvent) -> None:
    logger.info("User logged in: %s (id=%s)", event.email, event.user_id)
    await _write_audit_log("user_logged_in", event.user_id, {"email": event.email})


async def _write_audit_log(action: str, user_id: str, details: dict) -> None:
    """Persist an audit entry. Best-effort — failures are logged, not raised."""
    try:
        import json
        async with async_engine.begin() as conn:
            await conn.execute(
                sa_text(
                    """INSERT INTO audit_log (user_id, action, details, created_at)
                       VALUES (:user_id, :action, :details, :ts)"""
                ),
                {
                    "user_id": user_id,
                    "action": action,
                    "details": json.dumps(details),
                    "ts": datetime.now(UTC),
                },
            )
    except Exception:
        # audit is non-critical — don't blow up the request
        logger.warning("Failed to write audit log for %s", action, exc_info=True)
