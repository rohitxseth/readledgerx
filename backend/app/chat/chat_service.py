import uuid
from collections.abc import Awaitable, Callable

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

SendFn = Callable[[dict], Awaitable[None]]


async def process_message(
    body: ChatRequest,
    user: User,
    conn: AsyncConnection,
    send_fn: SendFn | None = None,
) -> dict:
    session = await _resolve_session(body, user)
    session_id = str(session["id"])

    user_input, user_content = _build_user_input(body)
    await add_message(
        session_id=session_id,
        role="user",
        content=user_content,
        message_type=body.message_type.value,
    )
    history = await get_conversation_history(session_id, 30)

    async def stream_callback(element: dict) -> None:
        if element.get("type") == "text_chunk":
            await send_fn({"type": "text_chunk", "session_id": session_id, **element})
        else:
            await send_fn(
                {"type": "element", "session_id": session_id, "element": element}
            )

    agent = RouterAgent(
        session=session,
        context={
            "conn": conn,
            "user": user,
            "session_id": session_id,
            "metadata": parse_metadata(session.get("metadata")),
        },
        stream_callback=stream_callback if send_fn else None,
    )
    result = await agent.run(user_input=user_input, history=history)

    if result["session_updates"]:
        await update_session(session_id, result["session_updates"])

    response = result["response"]
    message_id = await add_message(
        session_id=session_id,
        role="assistant",
        content=" | ".join(ui.summarize_elements(response["elements"]))[:1000],
        message_type="assistant",
        ui_payload=response,
    )

    reply = {
        "session_id": session_id,
        "message_id": message_id or str(uuid.uuid4()),
        "response": response,
        "suggestions": result["suggestions"],
    }
    if send_fn:
        await send_fn({"type": "done", **reply})
    return reply


async def _resolve_session(body: ChatRequest, user: User) -> dict:
    if body.session_id:
        session = await load_session(body.session_id)
        if session and str(session["user_id"]) == str(user.id):
            return session

    session = await create_session(str(user.id), body.session_name)
    if not session:
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
