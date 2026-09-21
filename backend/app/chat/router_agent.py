import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.chat import ui
from app.chat.prompt import SYSTEM_PROMPT
from app.chat.session_manager import parse_metadata
from app.chat.tools import TOOL_DEFINITIONS, execute_tool
from app.config.llm_config import get_langchain_llm

logger = logging.getLogger(__name__)

_LLM_MAX_RETRIES = 2
_LLM_RETRY_DELAY_S = 1.0
_MAX_HISTORY_TURNS = 20

_DEFAULT_SUGGESTIONS = ["Search for a book", "Show my progress", "Help"]
_ERROR_SUGGESTIONS = ["Try again", "Help"]

_HELP_PHRASES = frozenset({"help", "help me", "what can you do", "commands", "options"})

_RECOMMENDATION_RX = re.compile(
    "|".join(
        f"(?:{p})"
        for p in (
            r"^(?:please\s+)?(?:recommend|suggest)\b",
            r"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:recommend|suggest)\b",
            r"\bwhat\s+(?:do|would)\s+you\s+(?:recommend|suggest)\b",
            r"^(?:any\s+|some\s+)?(?:book\s+|reading\s+)?(?:recommendations?|suggestions?|recs)\b",
            r"\b(?:any|some|a|your|book|reading)\s+(?:book\s+|reading\s+)?(?:recommendations?|suggestions?|recs)\b",
            r"\bwhat\s+(?:book\s+|books\s+)?(?:should|shall|could|can)\s+i\s+read\b",
            r"\bwhat\s+to\s+read\b",
            r"\b(?:something|anything)\s+(?:good\s+|new\s+|fun\s+|interesting\s+)?to\s+read\b",
            r"\bany\s+(?:good|great|decent)\s+(?:books?|novels?|reads?)\b",
        )
    )
)

_INTENT_WORDS = (
    "recommend",
    "recommends",
    "recommended",
    "recommendation",
    "recommendations",
    "suggest",
    "suggests",
    "suggested",
    "suggestion",
    "suggestions",
)

_SEARCH_PROMPTS = {
    "author": (
        "Which author? Type it like **books by Ayn Rand**.",
        ["Books by Ayn Rand", "Books by Brandon Sanderson"],
    ),
    "genre": (
        "Which genre? Type it like **sci-fi books** or **fantasy books**.",
        ["Sci-fi books", "Fantasy books"],
    ),
    "topic": (
        "What topic? Type it like **books about stoicism**.",
        ["Books about stoicism", "Books about habits"],
    ),
}
_DEFAULT_SEARCH_PROMPT = (
    "What would you like to search for? An author, a genre or a topic all work.",
    ui.SEARCH_EXAMPLES,
)


def _edit_distance(a: str, b: str) -> int:
    # Optimal string alignment distance: an adjacent swap ("suggets") is one edit.
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(
                prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1])
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _correct_intent_typo(word: str) -> str:
    if word in _INTENT_WORDS or len(word) < 5:
        return word
    best, best_distance = word, None
    for target in _INTENT_WORDS:
        # Requiring the same first letter stops real words like "commend" (two
        # edits from "recommend") from being folded into an intent word.
        limit = 1 if len(target) <= 7 else 2
        if word[0] != target[0] or abs(len(word) - len(target)) > limit:
            continue
        distance = _edit_distance(word, target)
        if distance <= limit and (best_distance is None or distance < best_distance):
            best, best_distance = target, distance
    return best


def _is_recommendation_request(message: str) -> bool:
    normalized = re.sub(
        r"[a-z]+",
        lambda m: _correct_intent_typo(m.group(0)),
        (message or "").strip().lower(),
    )
    return bool(_RECOMMENDATION_RX.search(normalized))


def _result(
    elements: list[dict], suggestions: list[str], session_updates: dict | None = None
) -> dict:
    return {
        "response": ui.composite(elements),
        "session_updates": session_updates or {},
        "suggestions": suggestions,
    }


class RouterAgent:
    def __init__(
        self,
        session: dict,
        context: dict,
        stream_callback: Callable[[dict], Awaitable[None]] | None = None,
    ):
        self.context = context
        self.stream_callback = stream_callback
        self.metadata = parse_metadata(session.get("metadata"))
        self.llm = get_langchain_llm()

    async def run(self, user_input: dict, history: list[dict]) -> dict:
        intercepted = self._intercept(user_input)
        if intercepted is not None:
            return intercepted

        if self.llm is None:
            return self._error_result(
                "AI service is not configured. Please set up Azure OpenAI or OpenAI credentials."
            )

        messages = self._build_messages(history, user_input)
        llm_with_tools = self.llm.bind_tools(TOOL_DEFINITIONS)

        # Single pass: tool results go straight back to the user rather than
        # to a second LLM call, which bounds latency and cost per message.
        for attempt in range(1, _LLM_MAX_RETRIES + 1):
            try:
                response = None
                async for chunk in llm_with_tools.astream(messages):
                    response = chunk if response is None else response + chunk
                    if chunk.content and self.stream_callback:
                        await self.stream_callback(
                            {
                                "type": "text_chunk",
                                "content": chunk.content,
                                "style": "default",
                            }
                        )

                if response and response.tool_calls:
                    return await self._handle_tool_calls(
                        response.tool_calls, user_input, response.content or ""
                    )

                text = (response.content or "") if response else ""
                return _result([ui.text(text)], self._infer_suggestions_from_text(text))

            except Exception as exc:
                if attempt < _LLM_MAX_RETRIES:
                    logger.warning("LLM call failed (attempt %d): %s", attempt, exc)
                    await asyncio.sleep(_LLM_RETRY_DELAY_S * attempt)
                else:
                    logger.exception("LLM call failed; giving up")

        return self._error_result(
            "I'm having trouble processing your request. Please try again."
        )

    def _intercept(self, user_input: dict) -> dict | None:
        """Answer requests whose reply is fixed without calling the LLM."""
        if user_input.get("message_type") == "action_click":
            action_data = user_input.get("action_data") or {}
            if action_data.get("action") != "search_prompt":
                return None
            by = (action_data.get("payload") or {}).get("by")
            prompt, suggestions = _SEARCH_PROMPTS.get(by, _DEFAULT_SEARCH_PROMPT)
            return _result([ui.text(prompt)], suggestions)

        message = (user_input.get("message") or "").strip().lower()
        if message in _HELP_PHRASES:
            return _result([ui.help_card()], ["Search books", "Show my progress"])
        if _is_recommendation_request(message):
            return _result(ui.recommendation_decline(), ui.SEARCH_EXAMPLES)
        return None

    async def _handle_tool_calls(
        self, tool_calls: list[dict], user_input: dict, llm_text: str
    ) -> dict:
        elements = [ui.text(llm_text)] if llm_text else []
        session_updates = {}
        suggestions = []

        action_data = (
            user_input.get("action_data") or {}
            if user_input.get("message_type") == "action_click"
            else {}
        )

        for call in tool_calls:
            name, args = call["name"], call["args"]
            if action_data:
                args = {**args, "action_data": action_data}

            if self.stream_callback:
                await self.stream_callback(
                    ui.progress(f"Running {name.replace('_', ' ')}…")
                )

            try:
                result = await execute_tool(name, args, self.context)
            except Exception as exc:
                logger.exception("Tool %s failed", name)
                result = {
                    "elements": [
                        ui.text(f"Sorry, that operation failed: {exc}", style="error")
                    ],
                    "suggestions": _ERROR_SUGGESTIONS,
                    "metadata_updates": {},
                }

            if result["metadata_updates"]:
                self.metadata.update(result["metadata_updates"])
                session_updates["metadata"] = self.metadata
            suggestions = result["suggestions"]
            elements.extend(result["elements"])

            if self.stream_callback:
                for element in result["elements"]:
                    await self.stream_callback(element)

        return _result(elements, suggestions, session_updates)

    def _build_messages(
        self, history: list[dict], user_input: dict
    ) -> list[BaseMessage]:
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for msg in history[-_MAX_HISTORY_TURNS:]:
            content = msg.get("content") or ""
            if msg.get("role") == "user":
                messages.append(HumanMessage(content=content))
            elif msg.get("role") == "assistant":
                messages.append(
                    AIMessage(
                        content=self._enrich_assistant_content(
                            content, msg.get("ui_payload")
                        )
                    )
                )

        current = self._format_user_input(user_input)
        if current:
            messages.append(HumanMessage(content=current))
        return messages

    @staticmethod
    def _enrich_assistant_content(text: str, ui_payload: dict | str | None) -> str:
        elements = ui_payload.get("elements") if isinstance(ui_payload, dict) else None
        if not elements:
            return text
        parts = [text] if text else []
        parts.extend(ui.summarize_elements(elements, include_text=False))
        return " | ".join(parts)

    @staticmethod
    def _format_user_input(user_input: dict) -> str:
        message = user_input.get("message") or ""
        if user_input.get("message_type") != "action_click":
            return message

        action_data = user_input.get("action_data") or {}
        parts = [f"[Action: {action_data.get('action', '')}]"]
        payload = action_data.get("payload", {})
        if payload:
            parts.append(f"Payload: {json.dumps(payload)}")
        if message:
            parts.append(message)
        return " ".join(parts)

    @staticmethod
    def _infer_suggestions_from_text(text: str) -> list[str]:
        if any(word in text.lower() for word in ("book", "read", "track", "search")):
            return ["Search books", "Show my progress", "Help"]
        return _DEFAULT_SUGGESTIONS

    @staticmethod
    def _error_result(message: str) -> dict:
        return _result([ui.text(message, style="error")], _ERROR_SUGGESTIONS)
