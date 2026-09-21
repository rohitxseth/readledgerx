import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncConnection

from app.chat import ui
from app.chat.router_agent import RouterAgent
from app.chat.session_manager import (
    add_message,
    create_session,
    get_conversation_history,
    load_session,
    parse_metadata,
    update_session,
)
from app.core.exceptions import DomainException
from app.schemas.chat import ChatRequest, MessageType
from app.schemas.models import User

logger = logging.getLogger(__name__)


async def process_message(
    body: ChatRequest,
    user: User,
    conn: AsyncConnection,
    send_fn=None,
) -> dict:
    session = await _resolve_session(body, user)
    session_id = str(session["id"])
    logger.info(
        "chat: session=%s user=%s type=%s",
        session_id,
        user.email,
        body.message_type.value,
    )

    user_input, user_content = _build_user_input(body)
    await add_message(
        session_id=session_id,
        role="user",
        content=user_content,
        message_type=body.message_type.value,
    )

    history = await get_conversation_history(session_id, 30)

    tool_context = {
        "conn": conn,
        "user": user,
        "session_id": session_id,
        "metadata": parse_metadata(session.get("metadata")),
    }

    async def stream_callback(element: dict):
        if element.get("type") == "text_chunk":
            await send_fn({"type": "text_chunk", "session_id": session_id, **element})
        else:
            await send_fn(
                {"type": "element", "session_id": session_id, "element": element}
            )

    agent = RouterAgent(
        session=session,
        context=tool_context,
        stream_callback=stream_callback if send_fn else None,
    )
    result = await agent.run(
        user_input=user_input,
        history=history,
    )

    session_updates = result.get("session_updates", {})
    if session_updates:
        await update_session(session_id, session_updates)

    response_payload = result.get("response", {})
    assistant_msg_id = await add_message(
        session_id=session_id,
        role="assistant",
        content=_extract_text(response_payload),
        message_type="assistant",
        ui_payload=response_payload,
    )

    response_dict = {
        "session_id": session_id,
        "message_id": assistant_msg_id or str(uuid.uuid4()),
        "response": response_payload,
        "suggestions": result.get("suggestions", []),
    }

    if send_fn:
        await send_fn({"type": "done", **response_dict})
        logger.info("chat: completed session=%s", session_id)

    return response_dict


async def _resolve_session(body: ChatRequest, user: User) -> dict:
    session = None

    if body.session_id:
        session = await load_session(body.session_id)
        if not (session and str(session.get("user_id")) == str(user.id)):
            session = None

    if not session:
        session = await create_session(str(user.id), body.session_name)

    if not session or not session.get("id"):
        raise DomainException("Failed to create session")
    return session


def _build_user_input(body: ChatRequest) -> tuple[dict, str]:
    if body.message_type == MessageType.ACTION_CLICK and body.action_data:
        user_content = f"[Action: {body.action_data.action}]"
    else:
        user_content = body.message or ""

    user_input = {
        "message": body.message or "",
        "message_type": body.message_type.value,
        "action_data": body.action_data.model_dump() if body.action_data else None,
    }
    return user_input, user_content


def _extract_text(response: dict) -> str:
    if not response:
        return ""
    elements = response.get("elements", [])
    if not elements:
        return (response.get("content") or "")[:1000]
    return " | ".join(ui.summarize_elements(elements))[:1000]
