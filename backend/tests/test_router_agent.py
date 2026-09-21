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

from app.chat import ui
from app.chat.router_agent import (
    RouterAgent,
    _correct_intent_typo,
    _is_recommendation_request,
)


class _RecordingLLM:
    """Stands in for the chat model and records whether anything touched it."""

    def __init__(self):
        self.used = False

    def bind_tools(self, *args, **kwargs):
        self.used = True
        raise RuntimeError("LLM must not be called for an intercepted request")


def _agent(llm="recording"):
    agent = RouterAgent(session={"id": "s1", "metadata": {}}, context={})
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
# Misspellings get the same reply as the correct spelling
#
# Regression: "recomment a book" missed the intercept, fell through to the LLM,
# and came back as plain text with no buttons — a different answer from
# "suggest a book" for the same request.
# ---------------------------------------------------------------------------

async def test_misspelled_request_gets_an_identical_response():
    typo_agent, correct_agent = _agent(), _agent()

    typo = await typo_agent.run(_text("recomment a book"), history=[])
    correct = await correct_agent.run(_text("recommend a book"), history=[])

    assert typo_agent.llm.used is False
    assert typo == correct


@pytest.mark.parametrize("message", [
    "recomment a book",
    "reccomend a book",
    "recomend something to read",
    "can you sugest something?",
    "suggets a novel",
    "any recomendations?",
    "reccommendations please",
    "give me a book sugestion",
])
async def test_common_misspellings_are_declined_without_the_llm(message):
    agent = _agent()
    result = await agent.run(_text(message), history=[])

    assert agent.llm.used is False
    assert _element_types(result) == ["text", "action_buttons"]


@pytest.mark.parametrize("message", [
    "biggest book on my shelf?",          # "biggest" is 2 edits from "suggest"
    "commend a book",                     # "commend" is 2 edits from "recommend"
    "books recommnded by Bill Gates",     # typo'd look-alike stays a search
])
def test_typo_folding_does_not_create_false_positives(message):
    assert _agent()._intercept(_text(message)) is None


@pytest.mark.parametrize("word, expected", [
    ("recomment", "recommend"),
    ("reccomend", "recommend"),
    ("recommnded", "recommended"),   # nearest form wins, not the first listed
    ("sugest", "suggest"),
    ("biggest", "biggest"),          # first letter differs — left alone
    ("digest", "digest"),
    ("read", "read"),                # too short to fold
])
def test_correct_intent_typo(word, expected):
    assert _correct_intent_typo(word) == expected
