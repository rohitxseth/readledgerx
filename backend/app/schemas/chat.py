from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MessageType(StrEnum):
    TEXT = "text"
    ACTION_CLICK = "action_click"


class ChatActionData(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    session_id: UUID | None = Field(None, description="Null to start a new session.")
    session_name: str | None = None
    message: str | None = None
    message_type: MessageType = MessageType.TEXT
    action_data: ChatActionData | None = None


class ChatResponse(BaseModel):
    session_id: str
    message_id: str
    response: dict[str, Any]
    suggestions: list[str] = []
