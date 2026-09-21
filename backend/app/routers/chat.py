import logging
from contextlib import suppress
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.chat import ui
from app.chat.chat_service import process_message
from app.chat.session_manager import (
    get_conversation_history,
    get_user_sessions,
    load_session,
)
from app.core.dependencies import (
    authenticate,
    get_current_user,
    get_user_repository,
)
from app.core.exceptions import DomainException
from app.database import async_engine, get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/message", response_model=ChatResponse)
async def handle_message(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    conn: AsyncConnection = Depends(get_db),
):
    return ChatResponse(**await process_message(request, current_user, conn))


@router.websocket("/ws")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    user = None

    try:
        auth_data = await websocket.receive_json()
        if auth_data.get("type") != "auth" or not auth_data.get("token"):
            await websocket.send_json(
                ui.error_frame("Auth required. Send: {type: 'auth', token: '<JWT>'}.")
            )
            await websocket.close(code=4001, reason="Auth required")
            return

        user = await _authenticate_ws(auth_data["token"])
        if not user:
            await websocket.send_json(ui.error_frame("Invalid or expired token."))
            await websocket.close(code=4003, reason="Auth failed")
            return

        await websocket.send_json(
            {"type": "auth_ok", "user_id": str(user.id), "email": user.email}
        )
        logger.info("WebSocket connected: %s", user.email)

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type != "message":
                await websocket.send_json(
                    ui.error_frame(f"Unknown message type: {msg_type}")
                )
                continue

            try:
                body = ChatRequest.model_validate(data)
            except ValidationError as e:
                await websocket.send_json(
                    ui.error_frame(f"Invalid message format: {e}")
                )
                continue

            try:
                async with async_engine.begin() as conn:
                    await process_message(body, user, conn, websocket.send_json)
            except WebSocketDisconnect:
                raise
            except Exception:
                logger.exception("Chat turn failed")
                await websocket.send_json(
                    ui.error_frame("Something went wrong processing your message.")
                )

    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected: %s", user.email if user else "unauthenticated"
        )
    except Exception:
        logger.exception("WebSocket error")
        with suppress(Exception):
            await websocket.close(code=1011, reason="Internal error")


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    conn: AsyncConnection = Depends(get_db),
):
    sessions = await get_user_sessions(conn, current_user.id, limit=limit)
    return {"sessions": sessions}


@router.get("/history")
async def get_history(
    session_id: UUID = Query(...),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    conn: AsyncConnection = Depends(get_db),
):
    session = await load_session(conn, session_id)
    if not session or session["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    messages = await get_conversation_history(conn, session_id, limit=limit)
    return {"session_id": session_id, "messages": messages, "total": len(messages)}


async def _authenticate_ws(token: str) -> User | None:
    async with async_engine.begin() as conn:
        try:
            return await authenticate(token, get_user_repository(conn))
        except DomainException:
            return None
