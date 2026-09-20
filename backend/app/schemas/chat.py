from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


# ============================================================================
# Enums
# ============================================================================


class MessageType(str, Enum):
    TEXT = "text"
    ACTION_CLICK = "action_click"


# ============================================================================
# Chat Request Models
# ============================================================================


class ChatActionData(BaseModel):
    """Data sent when user clicks an action button."""

    action: str = Field(..., description="Action identifier")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Action payload")


class ChatRequest(BaseModel):
    """Incoming chat message from the frontend."""

    session_id: Optional[str] = Field(
        None, description="Session ID, null for new session"
    )
    session_name: Optional[str] = Field(None, description="Human-readable session name")
    message: Optional[str] = Field(None, description="User message text")
    message_type: MessageType = Field(
        default=MessageType.TEXT, description="Type of message"
    )
    action_data: Optional[ChatActionData] = Field(
        None, description="Clicked action data"
    )


# ============================================================================
# Chat Response Models
# ============================================================================


class ChatResponse(BaseModel):
    """Response from the chat endpoint."""

    session_id: str
    message_id: str
    response: Dict[str, Any]
    suggestions: List[str] = []
