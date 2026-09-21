"""
Tests for RouterAgent's deterministic intercepts.

Some requests have a fixed answer and must never reach the LLM. The one that
matters most is a recommendation request: the app can't recommend, and the LLM
used to launder "suggest a book" into search_books("fiction") and return
magazines and library catalogues.
"""

import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessageChunk

from app.chat import router_agent, ui
from app.chat.router_agent import RouterAgent, _is_recommendation_request


class _RecordingLLM:
    """Stands in for the chat model and records whether anything touched it."""

    def __init__(self):
        self.used = False

    def bind_tools(self, *args, **kwargs):
        self.used = True
        raise RuntimeError("LLM must not be called for an intercepted request")


def _agent(llm="recording"):
    agent = RouterAgent(metadata={}, context={})
    agent.llm = _RecordingLLM() if llm == "recording" else llm
    return agent


def _text(message: str) -> dict:
    return {"message": message, "message_type": "text", "action_data": None}


def _click(action: str, payload: dict) -> dict:
    return {"message": "", "message_type": "action_click",
            "action_data": {"action": action, "payload": payload}}


def _element_types(result: dict) -> list[str]:
    return [el["type"] for el in result["response"]["elements"]]


# ---------------------------------------------------------------------------
# Recommendation requests are declined, without an LLM call
# ---------------------------------------------------------------------------

RECOMMENDATION_REQUESTS = [
    "suggest a book",
    "recommend something to read",
    "what should I read next?",
    "any good books?",
    "Can you recommend a fantasy novel?",
    "what do you recommend?",
    "any recommendations?",
    "give me a book recommendation",
    "I'm not sure what to read next",
    "I need something good to read",
    "Please recommend a book",
]


@pytest.mark.parametrize("message", RECOMMENDATION_REQUESTS)
async def test_recommendation_request_is_declined_without_the_llm(message):
    agent = _agent()
    result = await agent.run(_text(message), history=[])

    assert agent.llm.used is False
    assert _element_types(result) == ["text", "action_buttons"]
    assert "can't recommend" in result["response"]["elements"][0]["content"]


async def test_decline_offers_search_by_genre_author_and_topic():
    result = await _agent().run(_text("suggest a book"), history=[])
    buttons = result["response"]["elements"][1]["buttons"]

    assert [(b["label"], b["action"], b["payload"]) for b in buttons] == [
        ("Search by genre", "search_prompt", {"by": "genre"}),
        ("Search by author", "search_prompt", {"by": "author"}),
        ("Search by topic", "search_prompt", {"by": "topic"}),
    ]


async def test_decline_suggestions_are_runnable_searches():
    """Suggestion chips are sent as messages, so they must be real searches."""
    result = await _agent().run(_text("suggest a book"), history=[])

    assert result["suggestions"] == ui.SEARCH_EXAMPLES
    for chip in result["suggestions"]:
        assert not _is_recommendation_request(chip)


async def test_decline_does_not_need_an_llm_configured():
    """A fixed reply shouldn't fail just because no model credentials are set."""
    result = await _agent(llm=None).run(_text("recommend me a book"), history=[])
    assert "can't recommend" in result["response"]["elements"][0]["content"]


# ---------------------------------------------------------------------------
# Everything else still reaches the agent
# ---------------------------------------------------------------------------

REACHES_THE_AGENT = [
    # genuine searches — these must keep returning results
    "search sci-fi books",
    "books by Ayn Rand",
    "books about stoicism",
    "search science fiction",
    # look-alikes that mention the words but aren't asking for a pick
    "books about recommendation systems",
    "search for books recommended by Bill Gates",
    "track The Recommendation",
    "log 20 pages of Suggestion Box",
    "I'm looking for a book called Dune",
    # other intents, including last round's aggregate questions
    "I read 40 pages of Dune",
    "show my progress",
    "what is my most read book?",
    "what did I read most recently?",
    "which book am I closest to finishing?",
]


@pytest.mark.parametrize("message", REACHES_THE_AGENT)
def test_other_messages_are_not_intercepted(message):
    assert _agent()._intercept(_text(message)) is None


def test_other_action_clicks_are_not_intercepted():
    """A title containing "recommend" in a button payload must not trip it."""
    click = _click("log_reading", {"book_title": "The Recommendation"})
    assert _agent()._intercept(click) is None


# ---------------------------------------------------------------------------
# The decline's buttons answer deterministically
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("by, expected", [
    ("genre", "Which genre?"),
    ("author", "Which author?"),
    ("topic", "What topic?"),
])
async def test_search_prompt_button_asks_for_the_missing_input(by, expected):
    """Left to the LLM, "Search by genre" sometimes claimed genre search didn't exist."""
    agent = _agent()
    result = await agent.run(_click("search_prompt", {"by": by}), history=[])

    assert agent.llm.used is False
    assert _element_types(result) == ["text"]
    assert result["response"]["elements"][0]["content"].startswith(expected)
    assert result["suggestions"]  # chips give the user something to tap


async def test_search_prompt_with_unknown_scope_falls_back_to_a_generic_prompt():
    result = await _agent().run(_click("search_prompt", {"by": "mood"}), history=[])
    assert "What would you like to search for?" in result["response"]["elements"][0]["content"]


# ---------------------------------------------------------------------------
# Regression: help moved into the same intercept
# ---------------------------------------------------------------------------

async def test_help_is_still_intercepted():
    agent = _agent()
    result = await agent.run(_text("help"), history=[])

    assert agent.llm.used is False
    assert _element_types(result) == ["help_card"]


# ---------------------------------------------------------------------------
# Contract: the decline only uses element types the frontend can draw
# ---------------------------------------------------------------------------

def test_decline_uses_only_element_types_the_renderer_handles():
    """BduiRenderer returns null for unknown types, so a typo renders nothing."""
    renderer = (
        Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "components" / "BduiRenderer.jsx"
    )
    if not renderer.exists():
        pytest.skip("frontend not present in this checkout")

    handled = set(re.findall(r'case "(\w+)"', renderer.read_text()))
    emitted = {el["type"] for el in ui.recommendation_decline()}
    assert emitted <= handled


# ---------------------------------------------------------------------------
# Look-alikes that mention the words without asking for a pick
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "biggest book on my shelf?",
    "commend a book",
    "books recommnded by Bill Gates",
    "find books recommended by my book club",
    "show my suggestions list",
])
def test_look_alikes_are_not_intercepted(message):
    assert _agent()._intercept(_text(message)) is None


# ---------------------------------------------------------------------------
# LLM retries never duplicate text the client has already seen
# ---------------------------------------------------------------------------

class _ScriptedLLM:
    """Each call to astream plays the next attempt; exceptions are raised in place."""

    def __init__(self, *attempts):
        self.attempts = list(attempts)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def astream(self, messages):
        self.calls += 1
        for item in self.attempts.pop(0):
            if isinstance(item, Exception):
                raise item
            yield item


def _streaming_agent(llm, events):
    async def record(element):
        events.append(element)

    agent = RouterAgent(metadata={}, context={}, stream_callback=record)
    agent.llm = llm
    return agent


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    monkeypatch.setattr(router_agent, "_LLM_RETRY_DELAY_S", 0)


async def test_no_retry_once_text_has_streamed_to_the_client():
    llm = _ScriptedLLM(
        [AIMessageChunk(content="Half an ans"), RuntimeError("connection dropped")],
        [AIMessageChunk(content="A second, different answer")],
    )
    events = []
    result = await _streaming_agent(llm, events).run(_text("hi"), history=[])

    assert llm.calls == 1
    assert [e["content"] for e in events] == ["Half an ans"]
    assert result["response"]["elements"][0]["style"] == "error"


async def test_a_failure_before_any_text_is_retried():
    llm = _ScriptedLLM([RuntimeError("timeout")], [AIMessageChunk(content="Recovered")])
    events = []
    result = await _streaming_agent(llm, events).run(_text("hi"), history=[])

    assert llm.calls == 2
    assert result["response"]["elements"][0]["content"] == "Recovered"


async def test_without_a_stream_a_partial_answer_is_retried():
    """Over REST nothing reaches the client until the turn ends, so retrying is safe."""
    llm = _ScriptedLLM(
        [AIMessageChunk(content="Half"), RuntimeError("connection dropped")],
        [AIMessageChunk(content="Whole answer")],
    )
    agent = _agent(llm=llm)
    result = await agent.run(_text("hi"), history=[])

    assert llm.calls == 2
    assert result["response"]["elements"][0]["content"] == "Whole answer"


async def test_a_tool_failure_propagates_without_rerunning_the_llm(monkeypatch):
    """Retrying here would re-run tools that may already have written."""
    call = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "undo_last_log", "args": "{}", "id": "c1", "index": 0}],
    )
    llm = _ScriptedLLM([call], [call])

    async def failing_tool(name, args, context):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(router_agent, "execute_tool", failing_tool)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await _agent(llm=llm).run(_text("undo that"), history=[])
    assert llm.calls == 1


# ---------------------------------------------------------------------------
# History sent to the LLM summarises each element once
# ---------------------------------------------------------------------------

def test_assistant_history_does_not_repeat_element_summaries():
    response = ui.composite([
        ui.text("Logged **40 pages** of **'Dune'**."),
        ui.book_progress_card({"title": "Dune", "progress_percentage": 9.71}),
        ui.action_buttons([ui.button("Log More Pages", "log_reading")]),
    ])
    stored = {
        "role": "assistant",
        # what chat_service stores as the assistant message's content
        "content": " | ".join(ui.summarize_elements(response["elements"])),
        "ui_payload": response,
    }

    messages = _agent()._build_messages([stored], _text("and now?"))
    replayed = messages[1].content

    assert replayed == stored["content"]
    assert replayed.count("[Actions: Log More Pages]") == 1
    assert replayed.count("[Progress: Dune") == 1
