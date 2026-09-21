from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncConnection

from app.chat import ui
from app.chat.router_agent import RouterAgent
from app.chat.session_manager import (
    add_message,
    create_session,
    get_conversation_history,
    load_session,
    update_session,
)
from app.core.dependencies import get_llm
from app.schemas.chat import ChatRequest, MessageType
from app.schemas.models import User

SendFn = Callable[[dict], Awaitable[None]]


async def process_message(
    body: ChatRequest,
    user: User,
    conn: AsyncConnection,
    send_fn: SendFn | None = None,
) -> dict:
    session = await _resolve_session(conn, body, user)
    session_id = session["id"]
    metadata = session["metadata"] or {}

    user_input, user_content = _build_user_input(body)
    history = await get_conversation_history(conn, session_id, 30)
    await add_message(conn, session_id, "user", user_content, body.message_type.value)

    async def stream_callback(element: dict) -> None:
        if element.get("type") == "text_chunk":
            await send_fn(
                {"type": "text_chunk", "session_id": str(session_id), **element}
            )
        else:
            await send_fn(
                {"type": "element", "session_id": str(session_id), "element": element}
            )

    agent = RouterAgent(
        llm=get_llm(),
        metadata=metadata,
        context={
            "conn": conn,
            "user": user,
            "session_id": session_id,
            "metadata": metadata,
        },
        stream_callback=stream_callback if send_fn else None,
    )
    result = await agent.run(user_input=user_input, history=history)

    if result["session_updates"]:
        await update_session(conn, session_id, result["session_updates"])

    response = result["response"]
    message_id = await add_message(
        conn,
        session_id,
        "assistant",
        " | ".join(ui.summarize_elements(response["elements"]))[:1000],
        "assistant",
        ui_payload=response,
    )

    reply = {
        "session_id": str(session_id),
        "message_id": message_id,
        "response": response,
        "suggestions": result["suggestions"],
    }
    if send_fn:
        await send_fn({"type": "done", **reply})
    return reply


async def _resolve_session(
    conn: AsyncConnection, body: ChatRequest, user: User
) -> dict:
    if body.session_id:
        session = await load_session(conn, body.session_id)
        if session and session["user_id"] == user.id:
            return session
    return await create_session(conn, user.id, body.session_name)


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
