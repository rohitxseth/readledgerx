"""
Router Agent — single LLM-powered agent that handles all chat interactions.

The agent:
  1. Converses with the user naturally to identify intent and collect entities
  2. Calls the appropriate workflow tool once all required data is gathered
  3. Handles greetings, help, and irrelevant questions gracefully
"""

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.chat.prompt import SYSTEM_PROMPT
from app.chat.session_manager import parse_metadata
from app.chat.tools import TOOL_DEFINITIONS, execute_tool
from app.chat import ui
from app.config.llm_config import get_langchain_llm

logger = logging.getLogger(__name__)

# Default suggestions when no tool provides them
_DEFAULT_SUGGESTIONS = [
    "Search for a book",
    "Show my progress",
    "Help",
]

# Contextual suggestion mapping by tool name
_TOOL_SUGGESTIONS = {
    "search_books": ["Track a book", "Search another", "Show my progress"],
    "start_tracking": ["Log pages", "Show progress", "Search books"],
    "log_reading": ["Log more pages", "Show progress", "Search books"],
    "show_progress": ["Log pages", "Search books", "Help"],
}

_HELP_PHRASES = frozenset({"help", "help me", "what can you do", "commands", "options"})

# Requests for a recommendation. The app can't recommend, and passing these to
# the LLM makes it invent a search query ("fiction", "bestsellers") and return
# irrelevant books. Patterns match the *request*, not the bare word, so topic
# searches like "books about recommendation systems" still reach the agent.
_RECOMMENDATION_RX = re.compile("|".join(f"(?:{p})" for p in (
    r"^(?:please\s+)?(?:recommend|suggest)\b",
    r"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:recommend|suggest)\b",
    r"\bwhat\s+(?:do|would)\s+you\s+(?:recommend|suggest)\b",
    r"^(?:any\s+|some\s+)?(?:book\s+|reading\s+)?(?:recommendations?|suggestions?|recs)\b",
    r"\b(?:any|some|a|your|book|reading)\s+(?:book\s+|reading\s+)?(?:recommendations?|suggestions?|recs)\b",
    r"\bwhat\s+(?:book\s+|books\s+)?(?:should|shall|could|can)\s+i\s+read\b",
    r"\bwhat\s+to\s+read\b",
    r"\b(?:something|anything)\s+(?:good\s+|new\s+|fun\s+|interesting\s+)?to\s+read\b",
    r"\bany\s+(?:good|great|decent)\s+(?:books?|novels?|reads?)\b",
)))

# Replies to the decline's "Search by …" buttons. Answered here rather than by
# the LLM, which reads search_by's title|author enum literally and can tell the
# user that genre search is unsupported — contradicting the decline.
_SEARCH_PROMPTS = {
    "author": ("Which author? Type it like **books by Ayn Rand**.",
               ["Books by Ayn Rand", "Books by Brandon Sanderson"]),
    "genre": ("Which genre? Type it like **sci-fi books** or **fantasy books**.",
              ["Sci-fi books", "Fantasy books"]),
    "topic": ("What topic? Type it like **books about stoicism**.",
              ["Books about stoicism", "Books about habits"]),
}
_DEFAULT_SEARCH_PROMPT = (
    "What would you like to search for? An author, a genre or a topic all work.",
    ui.SEARCH_EXAMPLES,
)


# The words the patterns above key on. Misspellings of these ("recomment",
# "reccomend", "sugest") are folded back before matching, so a typo gets the
# same fixed reply as the correct spelling instead of falling through to the
# LLM, which can only answer in plain text.
_INTENT_WORDS = (
    "recommend", "recommends", "recommended", "recommendation", "recommendations",
    "suggest", "suggests", "suggested", "suggestion", "suggestions",
)


def _edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance: an adjacent swap counts as one edit."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _correct_intent_typo(word: str) -> str:
    """Return the intent word *word* is a misspelling of, or *word* unchanged.

    Deliberately conservative. The first letter must match and short words get
    one edit, long words two — otherwise "biggest" is two edits from "suggest",
    and "biggest book on my shelf?" would be declined as a recommendation.
    """
    if word in _INTENT_WORDS or len(word) < 5:
        return word
    best, best_distance = word, None
    for target in _INTENT_WORDS:
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


_LLM_MAX_RETRIES = 2
_LLM_RETRY_DELAY_S = 1.0
_MAX_HISTORY_TURNS = 20


class RouterAgent:
    """Encapsulates a single run of the LLM-powered chat agent."""

    def __init__(
        self,
        session: dict,
        context: dict,
        stream_callback: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.session = session
        self.context = context
        self.stream_callback = stream_callback
        self.session_id = session.get("id", "")
        self.metadata = parse_metadata(session.get("metadata"))
        self.llm = get_langchain_llm()

    async def run(self, user_input: dict, history: list[dict]) -> dict:
        """Run one agent turn and return response, updates, and suggestions."""
        logger.info("agent.run: session=%s", self.session_id)

        # Fixed replies come first: they cost nothing, can't drift, and work
        # even when no LLM is configured.
        intercepted = self._intercept(user_input)
        if intercepted is not None:
            return intercepted

        if self.llm is None:
            return self._error_result("AI service is not configured. Please set up Azure OpenAI or OpenAI credentials.")

        messages = self._build_messages(history, user_input)

        for attempt in range(1, _LLM_MAX_RETRIES + 1):
            try:
                llm_with_tools = self.llm.bind_tools(TOOL_DEFINITIONS)
                full_response = None
                
                async for chunk in llm_with_tools.astream(messages):
                    if full_response is None:
                        full_response = chunk
                    else:
                        full_response = full_response + chunk

                    if chunk.content and self.stream_callback:
                        await self.stream_callback({
                            "type": "text_chunk",
                            "content": chunk.content,
                            "style": "default",
                        })

                if full_response and full_response.tool_calls:
                    logger.info("agent.run: LLM requested %d tool call(s)", len(full_response.tool_calls))
                    return await self._handle_tool_calls(
                        tool_calls=full_response.tool_calls,
                        user_input=user_input,
                        llm_text=full_response.content or "",
                    )

                text_content = (full_response.content or "") if full_response else ""
                logger.info("agent.run: text response (%d chars)", len(text_content))
                return {
                    "response": ui.composite([ui.text(text_content)]),
                    "session_updates": {},
                    "suggestions": self._infer_suggestions_from_text(text_content),
                }

            except Exception as exc:
                if attempt < _LLM_MAX_RETRIES:
                    logger.warning("agent.run: LLM failed attempt %d: %s", attempt, exc)
                    await asyncio.sleep(_LLM_RETRY_DELAY_S * attempt)
                else:
                    logger.error("agent.run: LLM failed completely: %s", exc, exc_info=True)

        return self._error_result("I'm having trouble processing your request. Please try again.")

    def _intercept(self, user_input: dict) -> Optional[dict]:
        """Answer requests that have a fixed reply, without calling the LLM."""
        if user_input.get("message_type") == "action_click":
            action_data = user_input.get("action_data") or {}
            if action_data.get("action") != "search_prompt":
                return None
            by = (action_data.get("payload") or {}).get("by")
            prompt, suggestions = _SEARCH_PROMPTS.get(by, _DEFAULT_SEARCH_PROMPT)
            logger.info("agent.run: search prompt intercept (by=%s)", by)
            return self._fixed_result([ui.text(prompt)], suggestions)

        message = (user_input.get("message") or "").strip().lower()
        if message in _HELP_PHRASES:
            logger.info("agent.run: help intercept")
            return self._fixed_result([ui.help_card()], ["Search books", "Show my progress"])
        if _is_recommendation_request(message):
            logger.info("agent.run: recommendation intercept")
            return self._fixed_result(ui.recommendation_decline(), ui.SEARCH_EXAMPLES)
        return None

    @staticmethod
    def _fixed_result(elements: list[dict], suggestions: list[str]) -> dict:
        return {
            "response": ui.composite(elements),
            "session_updates": {},
            "suggestions": suggestions,
        }

    async def _handle_tool_calls(self, tool_calls: list[dict], user_input: dict, llm_text: str = "") -> dict:
        all_elements: list[dict] = []
        if llm_text:
            all_elements.append(ui.text(llm_text))
            
        session_updates: dict = {}
        suggestions: list[str] = []

        _action_data = user_input.get("action_data") or {} if user_input.get("message_type") == "action_click" else {}

        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]

            if _action_data:
                tool_args = {**tool_args, "action_data": _action_data}

            if self.stream_callback:
                await self.stream_callback(ui.progress(f"Running {tool_name.replace('_', ' ')}…"))

            try:
                logger.info("tool execution started [%s]", tool_name)
                result = await execute_tool(tool_name, tool_args, self.context)
            except Exception as exc:
                logger.error("tool execution failed [%s]: %s", tool_name, exc, exc_info=True)
                result = {
                    "elements": [ui.text(f"Sorry, that operation failed: {exc}", style="error")],
                    "suggestions": ["Try again", "Help"],
                    "metadata_updates": {},
                }

            elements = result.get("elements", [])
            meta_updates = result.get("metadata_updates", {})
            if meta_updates:
                self.metadata.update(meta_updates)
                # Store the dict itself: the column is JSONB, so json.dumps here
                # would persist a JSON *string* scalar rather than an object,
                # leaving it unqueryable by JSONB operators.
                session_updates["metadata"] = self.metadata
                
            if result.get("suggestions"):
                suggestions = result.get("suggestions", [])

            all_elements.extend(elements)

            if self.stream_callback:
                for el in elements:
                    await self.stream_callback(el)

        if not suggestions:
            suggestions = self._suggestions_for_tools([tc["name"] for tc in tool_calls])

        return {
            "response": ui.composite(all_elements) if all_elements else ui.text_response("Done."),
            "session_updates": session_updates,
            "suggestions": suggestions,
        }

    def _build_messages(self, history: list[dict], user_input: dict) -> list:
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for msg in history[-_MAX_HISTORY_TURNS:]:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                enriched = self._enrich_assistant_content(content, msg.get("ui_payload"))
                messages.append(AIMessage(content=enriched))

        current_text = self._format_user_input(user_input)
        if current_text:
            messages.append(HumanMessage(content=current_text))
        return messages

    def _enrich_assistant_content(self, text: str, ui_payload) -> str:
        if not ui_payload:
            return text
        payload = ui_payload if isinstance(ui_payload, dict) else {}
        elements = payload.get("elements", [])
        if not elements:
            return text
        parts = [text] if text else []
        parts.extend(ui.summarize_elements(elements, include_text=False))
        return " | ".join(parts) if parts else text

    def _format_user_input(self, user_input: dict) -> str:
        message_type = user_input.get("message_type", "text")
        message = user_input.get("message", "") or ""
        if message_type == "action_click":
            action_data = user_input.get("action_data") or {}
            action = action_data.get("action", "")
            payload = action_data.get("payload", {})
            parts = [f"[Action: {action}]"]
            if payload:
                parts.append(f"Payload: {json.dumps(payload)}")
            if message:
                parts.append(message)
            return " ".join(parts)
        return message

    def _suggestions_for_tools(self, tool_names: list[str]) -> list[str]:
        seen = set()
        suggestions = []
        for name in tool_names:
            for s in _TOOL_SUGGESTIONS.get(name, []):
                if s not in seen:
                    seen.add(s)
                    suggestions.append(s)
        return suggestions[:4] if suggestions else _DEFAULT_SUGGESTIONS

    def _infer_suggestions_from_text(self, text_content: str) -> list[str]:
        lower = text_content.lower()
        if any(w in lower for w in ["book", "read", "track", "search"]):
            return ["Search books", "Show my progress", "Help"]
        if any(w in lower for w in ["hello", "hi", "hey", "help", "what can"]):
            return ["Search for a book", "Show my progress", "Help"]
        return _DEFAULT_SUGGESTIONS

    def _error_result(self, message: str) -> dict:
        return {
            "response": ui.error_response(message),
            "session_updates": {},
            "suggestions": ["Try again", "Help"],
        }
