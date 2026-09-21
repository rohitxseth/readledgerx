import logging
import uuid as _uuid
from contextlib import asynccontextmanager

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.chat.chat_service import process_message
from app.chat.session_manager import (
    get_conversation_history,
    get_user_sessions,
    load_session,
)
from app.core.dependencies import get_current_user
from app.database import async_engine, get_db
from app.repositories import UserRepository
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.models import User
from app.services.auth_service import decode_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/message", response_model=ChatResponse)
async def handle_message(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    conn: AsyncConnection = Depends(get_db),
):
    logger.info(
        "Message received from user %s: '%s'", current_user.email, request.message
    )

    result = await process_message(request, current_user, conn)

    logger.info("Response sent for session %s", result["session_id"])
    return ChatResponse(**result)


@router.websocket("/ws")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    user = None

    try:
        auth_data = await websocket.receive_json()
        if auth_data.get("type") != "auth" or not auth_data.get("token"):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Auth required. Send: {type: 'auth', token: '<JWT>'}.",
                }
            )
            await websocket.close(code=4001, reason="Auth required")
            return

        user = await _authenticate_ws(auth_data["token"])
        if not user:
            await websocket.send_json(
                {"type": "error", "message": "Invalid or expired token."}
            )
            await websocket.close(code=4003, reason="Auth failed")
            return

        await websocket.send_json(
            {"type": "auth_ok", "user_id": str(user.id), "email": user.email}
        )
        logger.info("WS Chat | Connected: %s", user.email)

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type != "message":
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )
                continue

            try:
                body = ChatRequest(
                    session_id=data.get("session_id"),
                    session_name=data.get("session_name"),
                    message=data.get("message"),
                    message_type=data.get("message_type", "text"),
                    action_data=data.get("action_data"),
                )
            except Exception as e:
                await websocket.send_json(
                    {"type": "error", "message": f"Invalid message format: {e}"}
                )
                continue

            try:
                async with _get_db_ctx() as conn:

                    async def send_fn(payload: dict):
                        await websocket.send_json(payload)

                    await process_message(body, user, conn, send_fn)

            except HTTPException as he:
                await websocket.send_json(
                    {"type": "error", "code": he.status_code, "message": he.detail}
                )
            except Exception as e:
                logger.error("WS Chat processing error: %s", e, exc_info=True)
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Something went wrong processing your message.",
                    }
                )

    except WebSocketDisconnect:
        logger.info(
            "WS Chat | Disconnected: %s",
            user.email if user else "unauthenticated",
        )
    except Exception as e:
        logger.error("WS Chat error: %s", e, exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    sessions = await get_user_sessions(str(current_user.id), limit=limit)
    return {"sessions": sessions}


@router.get("/history")
async def get_history(
    session_id: str = Query(..., description="Session ID"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    session = await load_session(session_id)
    if not session or str(session.get("user_id")) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    messages = await get_conversation_history(session_id, limit=limit)
    return {
        "session_id": session_id,
        "messages": messages,
        "total": len(messages),
    }


@asynccontextmanager
async def _get_db_ctx():
    async with async_engine.begin() as conn:
        yield conn


async def _authenticate_ws(token: str) -> User | None:
    payload = decode_token(token)
    if not payload:
        return None

    user_id_str = payload.get("sub")
    if not user_id_str:
        return None

    try:
        user_id = (
            _uuid.UUID(user_id_str) if isinstance(user_id_str, str) else user_id_str
        )
    except (ValueError, AttributeError):
        return None

    async with async_engine.begin() as conn:
        user_repo = UserRepository(conn)
        return await user_repo.get_by_id(user_id)
