from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ============================================================================
# Enums
# ============================================================================


class MessageType(StrEnum):
    TEXT = "text"
    ACTION_CLICK = "action_click"


# ============================================================================
# Chat Request Models
# ============================================================================


class ChatActionData(BaseModel):
    """Data sent when user clicks an action button."""

    action: str = Field(..., description="Action identifier")
    payload: dict[str, Any] = Field(default_factory=dict, description="Action payload")


class ChatRequest(BaseModel):
    """Incoming chat message from the frontend."""

    session_id: str | None = Field(
        None, description="Session ID, null for new session"
    )
    session_name: str | None = Field(None, description="Human-readable session name")
    message: str | None = Field(None, description="User message text")
    message_type: MessageType = Field(
        default=MessageType.TEXT, description="Type of message"
    )
    action_data: ChatActionData | None = Field(
        None, description="Clicked action data"
    )


# ============================================================================
# Chat Response Models
# ============================================================================


class ChatResponse(BaseModel):
    """Response from the chat endpoint."""

    session_id: str
    message_id: str
    response: dict[str, Any]
    suggestions: list[str] = []
