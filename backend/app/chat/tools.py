import logging
import re
from datetime import UTC, datetime, timedelta
from typing import get_args

from app.chat import ui
from app.core.dependencies import get_book_service, get_reading_service
from app.core.exceptions import (
    BookResolutionError,
    DomainException,
    ExternalServiceError,
)
from app.schemas.models import Book, LogAction, ProgressFilter, ProgressSort

logger = logging.getLogger(__name__)

LOG_READING_DEF = {
    "type": "function",
    "function": {
        "name": "log_reading",
        "description": "Log reading progress for a tracked book. Default action is 'add' (log pages read).",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Title of the book."},
                "action": {
                    "type": "string",
                    "enum": list(get_args(LogAction)),
                },
                "pages": {"type": "integer"},
                "percentage": {"type": "number"},
                "date": {"type": "string"},
            },
            "required": ["book_title"],
        },
    },
}

SEARCH_BOOKS_DEF = {
    "type": "function",
    "function": {
        "name": "search_books",
        "description": (
            "Search for a specific author, title, genre or topic the user named. "
            "Not for recommendations: when the user asks what to read or for a "
            "suggestion, do not invent a query such as 'fiction', 'bestsellers' "
            "or 'recommended' — recommendations are not supported."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "search_by": {"type": "string", "enum": ["title", "author"]},
            },
            "required": ["query"],
        },
    },
}

SHOW_PROGRESS_DEF = {
    "type": "function",
    "function": {
        "name": "show_progress",
        "description": (
            "Show reading progress, for one book or across all tracked books. "
            "Also answers ranking and superlative questions — use sort_by with "
            "limit=1 for questions like 'what is my most read book?' "
            "(sort_by=pages_read), 'what did I read most recently?' "
            "(sort_by=last_read), or 'which book am I closest to finishing?' "
            "(sort_by=percent_complete, filter=in_progress). Do not ask the user "
            "to pick a book first; call this directly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {
                    "type": "string",
                    "description": "Only for a specific book. Omit for questions about all books.",
                },
                "filter": {
                    "type": "string",
                    "enum": list(get_args(ProgressFilter)),
                    "description": "Restrict to books in this state. Combine with sort_by for e.g. closest to finishing.",
                },
                "sort_by": {
                    "type": "string",
                    "enum": list(get_args(ProgressSort)),
                    "description": "Rank results highest-first by this measure.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Return at most this many books. Use 1 for superlative questions.",
                },
            },
        },
    },
}

START_TRACKING_DEF = {
    "type": "function",
    "function": {
        "name": "start_tracking",
        "description": (
            "Start tracking a book the user has not logged before. If the user "
            "mentions pages they have already read, prefer log_reading — it "
            "starts tracking automatically. If you do call this with pages, they "
            "will be logged rather than discarded."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string"},
                "pages": {
                    "type": "integer",
                    "description": "Pages already read, if the user mentioned a number.",
                },
            },
            "required": ["book_title"],
        },
    },
}

UNDO_LAST_LOG_DEF = {
    "type": "function",
    "function": {
        "name": "undo_last_log",
        "description": (
            "Undo the user's most recent reading entry, whichever book it was for. "
            "Use for 'undo that', 'undo my last log', 'I didn't mean to log that'. "
            "Takes no arguments — the backend knows which entry was last, so do "
            "not work out an amount and call log_reading with reduce instead. "
            "Always call it for an undo request, even if the conversation suggests "
            "nothing is left: entries can be logged in other chats or through the "
            "API, and only the backend knows."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOL_DEFINITIONS = [
    LOG_READING_DEF,
    SEARCH_BOOKS_DEF,
    SHOW_PROGRESS_DEF,
    START_TRACKING_DEF,
    UNDO_LAST_LOG_DEF,
]

_NON_SPECIFIC_TERMS = frozenset(
    {
        "recommend",
        "recommended",
        "recommendation",
        "recommendations",
        "recs",
        "suggest",
        "suggested",
        "suggestion",
        "suggestions",
        "good",
        "great",
        "best",
        "top",
        "popular",
        "trending",
        "famous",
        "interesting",
        "fun",
        "new",
        "next",
        "must-read",
        "must-reads",
        "bestseller",
        "bestsellers",
        "best-seller",
        "best-sellers",
        "book",
        "books",
        "novel",
        "novels",
        "read",
        "reads",
        "reading",
        "something",
        "anything",
        "stuff",
        "a",
        "an",
        "the",
        "some",
        "any",
        "to",
        "for",
        "of",
        "me",
        "my",
        "i",
        "you",
        "what",
        "should",
        "please",
    }
)


def _is_non_specific_query(query: str) -> bool:
    words = re.findall(r"[\w'-]+", (query or "").lower())
    return bool(words) and all(w in _NON_SPECIFIC_TERMS for w in words)


_MAX_RECENT_RESULTS = 10
_MAX_STORED_DESCRIPTION = 1000

_RANKED_HEADERS = {
    ("pages_read", True): "Your most read book:",
    ("pages_read", False): "Your books, most read first:",
    ("percent_complete", True): "The book you're closest to finishing:",
    ("percent_complete", False): "Your books, closest to finishing first:",
    ("last_read", True): "What you read most recently:",
    ("last_read", False): "Your books, most recently read first:",
}

_FILTER_HEADERS = {
    "completed": "Books you've **completed**:",
    "in_progress": "Books you're **currently reading**:",
    "not_started": "Books you've tracked but **not started**:",
}

_FILTER_LABELS = {
    "completed": "completed",
    "in_progress": "currently reading",
    "not_started": "not started",
}


def _reply(
    elements: list[dict], suggestions: list[str], metadata_updates: dict | None = None
) -> dict:
    return {
        "elements": elements,
        "suggestions": suggestions,
        "metadata_updates": metadata_updates or {},
    }


def _compact_search_results(books: list[Book]) -> list[dict]:
    compact = []
    for book in books[:_MAX_RECENT_RESULTS]:
        data = book.model_dump(mode="json")
        description = data.get("description")
        if description and len(description) > _MAX_STORED_DESCRIPTION:
            data["description"] = description[:_MAX_STORED_DESCRIPTION].rstrip() + "…"
        compact.append(data)
    return compact


def _recent_results(context: dict | None) -> list[dict]:
    metadata = (context or {}).get("metadata") or {}
    if not isinstance(metadata, dict):
        return []
    results = metadata.get("recent_search_results")
    return results if isinstance(results, list) else []


def _preferred_volume_id(args: dict | None) -> str | None:
    action_data = (args or {}).get("action_data") or {}
    payload = action_data.get("payload") or {}
    return payload.get("google_books_id") or (args or {}).get("google_books_id")


def _book_ref(book: Book) -> dict:
    ref = {"book_title": book.title}
    if book.google_books_id:
        ref["google_books_id"] = book.google_books_id
    return ref


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    normalized = date_str.lower().strip()
    if normalized == "today":
        return datetime.now(UTC)
    if normalized == "yesterday":
        return datetime.now(UTC) - timedelta(days=1)
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return datetime.now(UTC)


async def _resolve_book(
    title: str, context: dict, args: dict
) -> tuple[Book | None, dict | None]:
    volume_id = _preferred_volume_id(args)
    if not title and not volume_id:
        return None, _reply(
            [
                ui.text(
                    "Which book? Try: **I read 50 pages of Harry Potter**",
                    style="warning",
                )
            ],
            ["Show my progress", "Help"],
        )

    try:
        book = await get_book_service(context["conn"]).resolve(
            title, volume_id=volume_id, recent_results=_recent_results(context)
        )
    except ExternalServiceError as e:
        return None, _reply(
            [ui.text(f"Search failed: {e.message}", style="error")],
            ["Try again", "Help"],
        )
    except BookResolutionError:
        return None, _reply(
            [
                ui.text(
                    f"I couldn't find a book matching **'{title}'**.", style="warning"
                ),
                ui.action_buttons(
                    [
                        ui.button(
                            "Search Books", "search_books", "primary", {"query": title}
                        )
                    ]
                ),
            ],
            ["Search books", "Help"],
        )
    return book, None


async def execute_log_reading(args: dict, context: dict) -> dict:
    book, error = await _resolve_book(args.get("book_title", ""), context, args)
    if error:
        return error

    try:
        result = await get_reading_service(context["conn"]).log_reading(
            context["user"].id,
            book.id,
            action=args.get("action", "add"),
            pages=args.get("pages"),
            percentage=args.get("percentage"),
            session_date=_parse_date(args.get("date")),
        )
    except DomainException as e:
        return _reply([ui.text(e.message, style="warning")], ["Show progress", "Help"])

    if result.action == "remove":
        return _reply(
            [
                ui.text(
                    f"I've removed **'{book.title}'** from your tracking list.",
                    style="success",
                ),
                ui.action_buttons(
                    [
                        ui.button("Show Progress", "show_progress", "secondary"),
                        ui.button("Search Books", "search_books", "secondary"),
                    ]
                ),
            ],
            ["Show progress", "Search books"],
        )

    message = {
        "add": f"Logged **{result.pages} pages** of **'{book.title}'**.",
        "reduce": f"Reduced progress by **{result.pages_reduced} pages** for **'{book.title}'**.",
        "set": f"Set progress to **page {result.pages}** for **'{book.title}'**.",
    }[result.action]

    elements = [ui.text(message, style="success")]
    if result.progress:
        elements.append(ui.book_progress_card(result.progress.model_dump(mode="json")))
    elements.append(
        ui.action_buttons(
            [
                ui.button("Log More Pages", "log_reading", "primary", _book_ref(book)),
                ui.button("Show All Progress", "show_progress", "secondary"),
            ]
        )
    )
    return _reply(
        elements,
        ["Log more pages", "Show progress", "Search books"],
        {"last_book_title": book.title},
    )


async def execute_search_books(args: dict, context: dict) -> dict:
    query = args.get("query", "")
    search_by = args.get("search_by")

    # Backstop for the router's recommendation intercept: the LLM sometimes
    # turns "suggest a book" into a search for "recommended" or "bestsellers".
    if _is_non_specific_query(query):
        return _reply(ui.recommendation_decline(), ui.SEARCH_EXAMPLES)

    try:
        books = await get_book_service(context["conn"]).search(
            query, search_by=search_by
        )
    except ExternalServiceError as e:
        return _reply(
            [ui.text(f"Search failed: {e.message}", style="error")],
            ["Try again", "Help"],
        )
    except DomainException as e:
        return _reply([ui.text(e.message, style="warning")], ["Help"])

    if not books:
        return _reply(
            [
                ui.text(
                    f"No books found matching '{query}'. Try a different search term.",
                    style="info",
                )
            ],
            ["Search for another book", "Help"],
        )

    header = (
        f"Books by **{query}**:"
        if search_by == "author"
        else f"Books matching **'{query}'**:"
    )
    return _reply(
        [
            ui.text(header),
            ui.book_list([book.model_dump(mode="json") for book in books]),
            ui.text("Say **track <book title>** to start tracking any of these books."),
        ],
        ["Track a book", "Search another", "Show my progress"],
        {"recent_search_results": _compact_search_results(books)},
    )


async def execute_show_progress(args: dict, context: dict) -> dict:
    book_title = args.get("book_title")
    filter_by = args.get("filter")
    sort_by = args.get("sort_by")
    limit = args.get("limit")
    user = context["user"]
    reading_service = get_reading_service(context["conn"])

    if book_title:
        book, error = await _resolve_book(book_title, context, args)
        if error:
            return error

        progress = await reading_service.get_book_progress(user.id, book.id)
        if not progress:
            return _reply(
                [
                    ui.text(
                        f"You haven't started reading **'{book_title}'** yet.",
                        style="info",
                    ),
                    ui.action_buttons(
                        [
                            ui.button(
                                "Start Tracking",
                                "start_tracking",
                                "primary",
                                _book_ref(book),
                            )
                        ]
                    ),
                ],
                ["Start tracking", "Show all progress"],
            )

        elements = ui.single_book_progress(
            f"Your progress on **'{book.title}'**:", progress.model_dump(mode="json")
        )
        elements.append(
            ui.action_buttons(
                [
                    ui.button("Log Pages", "log_reading", "primary", _book_ref(book)),
                    ui.button("Show All Progress", "show_progress", "secondary"),
                ]
            )
        )
        return _reply(
            elements,
            ["Log pages", "Show all progress", "Search books"],
            {"last_book_title": book.title},
        )

    all_progress = await reading_service.get_all_progress(
        user.id, filter_by=filter_by, sort_by=sort_by, limit=limit
    )

    if not all_progress and filter_by:
        return _reply(
            [
                ui.text(
                    f"No books matching filter: **{_FILTER_LABELS.get(filter_by, filter_by)}**.",
                    style="info",
                ),
                ui.action_buttons(
                    [
                        ui.button("Show All Progress", "show_progress", "secondary"),
                        ui.button("Search Books", "search_books", "secondary"),
                    ]
                ),
            ],
            ["Show all progress", "Search books"],
        )

    if not all_progress:
        return _reply(
            [
                ui.text("You haven't tracked any reading yet!", style="info"),
                ui.action_buttons(
                    [ui.button("Search for a Book", "search_books", "primary")]
                ),
            ],
            ["Search books", "Help"],
        )

    single = len(all_progress) == 1 and limit == 1
    header = _RANKED_HEADERS.get((sort_by, single)) or _FILTER_HEADERS.get(
        filter_by, "Your reading progress:"
    )

    if single:
        elements = ui.single_book_progress(
            header, all_progress[0].model_dump(mode="json")
        )
    else:
        elements = [
            ui.text(header),
            ui.book_list([p.model_dump(mode="json") for p in all_progress]),
        ]
    elements.append(
        ui.action_buttons(
            [
                ui.button(
                    "Completed Books",
                    "show_progress",
                    "secondary",
                    {"filter": "completed"},
                ),
                ui.button(
                    "In Progress",
                    "show_progress",
                    "secondary",
                    {"filter": "in_progress"},
                ),
                ui.button("Search Books", "search_books", "secondary"),
            ]
        )
    )
    return _reply(elements, ["Log pages", "Search books", "Help"])


async def execute_start_tracking(args: dict, context: dict) -> dict:
    book, error = await _resolve_book(args.get("book_title", ""), context, args)
    if error:
        return error

    try:
        result = await get_reading_service(context["conn"]).start_tracking(
            context["user"].id, book.id, pages=args.get("pages") or 0
        )
    except DomainException as e:
        return _reply([ui.text(e.message, style="warning")], ["Show progress", "Help"])

    progress = result.progress.model_dump(mode="json")
    if not result.created and not result.pages_logged:
        return _reply(
            ui.single_book_progress(
                f"You're already tracking **'{book.title}'**!", progress
            ),
            ["Log pages", "Show all progress", "Search books"],
            {"last_book_title": book.title},
        )

    if result.created and result.pages_logged:
        opening = (
            f"Added **'{book.title}'** to your reading list and logged "
            f"**{result.pages_logged} pages**."
        )
    elif result.created:
        opening = (
            f"Great! I've added **'{book.title}'** to your reading list. "
            "Start logging your pages whenever you're ready!"
        )
    else:
        opening = f"Logged **{result.pages_logged} pages** of **'{book.title}'**."

    return _reply(
        [
            ui.text(opening, style="success"),
            ui.book_progress_card(progress),
            ui.action_buttons(
                [
                    ui.button("Log Pages", "log_reading", "primary", _book_ref(book)),
                    ui.button("Show All Progress", "show_progress", "secondary"),
                ]
            ),
        ],
        ["Log pages", "Show progress", "Search books"],
        {"last_book_title": book.title},
    )


async def execute_undo_last_log(args: dict, context: dict) -> dict:
    try:
        result = await get_reading_service(context["conn"]).undo_last_log(
            context["user"].id
        )
    except DomainException as e:
        return _reply([ui.text(e.message, style="info")], ["Show my progress", "Help"])

    title = result.book.title if result.book else "that book"
    pages = result.session.pages_read
    if pages:
        message = f"Undid your last entry: **{pages} pages** of **'{title}'**."
        if result.progress is None:
            message += (
                f" That was its only entry, so **'{title}'** is no longer tracked."
            )
    else:
        message = f"Undid tracking **'{title}'**."

    elements = [ui.text(message, style="success")]
    if result.progress:
        elements.append(ui.book_progress_card(result.progress.model_dump(mode="json")))
    elements.append(
        ui.action_buttons(
            [ui.button("Show All Progress", "show_progress", "secondary")]
        )
    )
    return _reply(elements, ["Show progress", "Log pages", "Search books"])


_TOOL_DISPATCH = {
    "log_reading": execute_log_reading,
    "search_books": execute_search_books,
    "show_progress": execute_show_progress,
    "start_tracking": execute_start_tracking,
    "undo_last_log": execute_undo_last_log,
}


async def execute_tool(tool_name: str, args: dict, context: dict) -> dict:
    handler = _TOOL_DISPATCH.get(tool_name)
    if not handler:
        logger.warning("Unknown tool requested: %s", tool_name)
        return _reply([ui.text(f"Unknown tool: {tool_name}", style="error")], ["Help"])
    return await handler(args, context)
