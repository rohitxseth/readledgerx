import logging
import re
from datetime import datetime, timedelta, timezone
from app.chat import ui
from app.core.dependencies import get_book_service, get_reading_service
from app.core.exceptions import ReadingLimitError, ExternalServiceError

logger = logging.getLogger(__name__)

# Tool schemas — these get bound to the LLM via bind_tools()
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
                    "enum": ["add", "set", "reduce", "remove"],
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
                    "enum": ["completed", "in_progress", "not_started"],
                    "description": "Restrict to books in this state. Combine with sort_by for e.g. closest to finishing.",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["pages_read", "percent_complete", "last_read"],
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

TOOL_DEFINITIONS = [LOG_READING_DEF, SEARCH_BOOKS_DEF, SHOW_PROGRESS_DEF, START_TRACKING_DEF]


# Words with no searchable meaning on their own. A query made only of these is
# the model inventing a search for a request it can't serve — usually a
# recommendation — rather than a user naming something. Genres ("fiction",
# "sci-fi") are deliberately absent: they are real searches.
_NON_SPECIFIC_TERMS = frozenset({
    "recommend", "recommended", "recommendation", "recommendations", "recs",
    "suggest", "suggested", "suggestion", "suggestions",
    "good", "great", "best", "top", "popular", "trending", "famous", "interesting",
    "fun", "new", "next", "must-read", "must-reads",
    "bestseller", "bestsellers", "best-seller", "best-sellers",
    "book", "books", "novel", "novels", "read", "reads", "reading",
    "something", "anything", "stuff",
    "a", "an", "the", "some", "any", "to", "for", "of", "me", "my", "i", "you",
    "what", "should", "please",
})


def _is_non_specific_query(query: str) -> bool:
    """True when *query* names nothing: every word is filler."""
    return all(t in _NON_SPECIFIC_TERMS for t in re.findall(r"[\w'-]+", query.lower()))


# How many shown results to remember for the next turn.
_MAX_RECENT_RESULTS = 10
# Descriptions are the only unbounded field on a Book, so cap them rather than
# dropping them — a book first stored via a remembered result would otherwise
# land in the catalogue with no description at all.
_MAX_STORED_DESCRIPTION = 1000


def _compact_search_results(books: list) -> list[dict]:
    """Shrink search results for storage in session metadata."""
    compact = []
    for book in books[:_MAX_RECENT_RESULTS]:
        data = book.model_dump(mode="json")
        description = data.get("description")
        if description and len(description) > _MAX_STORED_DESCRIPTION:
            data["description"] = description[:_MAX_STORED_DESCRIPTION].rstrip() + "…"
        compact.append(data)
    return compact


def _recent_results(context: dict | None) -> list[dict]:
    """Book payloads shown to this user earlier in the conversation."""
    metadata = (context or {}).get("metadata") or {}
    if not isinstance(metadata, dict):
        return []
    results = metadata.get("recent_search_results")
    return results if isinstance(results, list) else []


def _preferred_volume_id(args: dict | None) -> str | None:
    """A volume id carried explicitly by a clicked action button."""
    action_data = (args or {}).get("action_data") or {}
    payload = action_data.get("payload") or {}
    return payload.get("google_books_id") or (args or {}).get("google_books_id")


def _book_ref(book) -> dict:
    """Button payload pinning a specific volume, so a click can't drift edition."""
    ref = {"book_title": book.title}
    if book.google_books_id:
        ref["google_books_id"] = book.google_books_id
    return ref


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    d = date_str.lower().strip()
    if d == "today":
        return datetime.now(timezone.utc)
    if d == "yesterday":
        return datetime.now(timezone.utc) - timedelta(days=1)
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return datetime.now(timezone.utc)


async def _resolve_book(title: str, conn, context: dict | None = None, args: dict | None = None):
    """Shared helper: resolve a book title or return an error response dict.

    Prefers a volume the user was actually shown — a clicked button's id first,
    then the most recent search results — before falling back to the full
    resolution pipeline, which may otherwise pick a different edition.

    Returns (book, None) on success, (None, error_dict) on failure."""
    if not title:
        return None, {
            "elements": [ui.text("Which book? Try: **I read 50 pages of Harry Potter**", style="warning")],
            "suggestions": ["Show my progress", "Help"],
            "metadata_updates": {},
        }

    recent = _recent_results(context)
    volume_id = _preferred_volume_id(args)
    if volume_id:
        # An id carried by a clicked button outranks anything matched by title.
        recent = [{"google_books_id": volume_id, "title": title}, *recent]

    try:
        book_service = get_book_service(conn)
        book = await book_service.resolve_book(title, recent_results=recent)
    except ExternalServiceError as e:
        return None, {
            "elements": [ui.text(f"Search failed: {e.message}", style="error")],
            "suggestions": ["Try again", "Help"],
            "metadata_updates": {},
        }
    if not book:
        return None, {
            "elements": [
                ui.text(f"I couldn't find a book matching **'{title}'**.", style="warning"),
                ui.action_buttons([ui.button("Search Books", "search_books", "primary", {"query": title})]),
            ],
            "suggestions": ["Search books", "Help"],
            "metadata_updates": {},
        }
    return book, None


async def execute_log_reading(args: dict, context: dict) -> dict:
    book_title = args.get("book_title", "")
    action = args.get("action", "add")
    pages = args.get("pages")
    percentage = args.get("percentage")
    date_str = args.get("date")
    conn = context.get("conn")
    user = context.get("user")

    book, err = await _resolve_book(book_title, conn, context, args)
    if err:
        return err

    reading_service = get_reading_service(conn)

    if action == "remove":
        await reading_service.remove_book_tracking(user.id, book.id)
        return {
            "elements": [
                ui.text(f"I've removed **'{book.title}'** from your tracking list.", style="success"),
                ui.action_buttons([
                    ui.button("Show Progress", "show_progress", "secondary"),
                    ui.button("Search Books", "search_books", "secondary"),
                ]),
            ],
            "suggestions": ["Show progress", "Search books"],
            "metadata_updates": {},
        }

    if not pages and percentage is None:
        return {
            "elements": [ui.text("How many pages? Try: **I read 50 pages** or **I'm at 25%**", style="warning")],
            "suggestions": ["Help"],
            "metadata_updates": {},
        }

    # convert percentage to page number if needed
    if percentage is not None and not pages:
        total_pages = book.page_count or 0
        if total_pages == 0:
            return {
                "elements": [ui.text(f"I don't have the total page count for **'{book.title}'**. Please use page numbers instead.", style="warning")],
                "suggestions": ["Help"],
                "metadata_updates": {},
            }
        pages = int((percentage / 100) * total_pages)

    session_date = _parse_date(date_str)

    try:
        if action == "add":
            await reading_service.add_reading_session(user.id, book.id, pages, session_date)
            message = f"Logged **{pages} pages** of **'{book.title}'**."
        elif action == "reduce":
            result = await reading_service.reduce_reading_progress(user.id, book.id, pages, session_date)
            pages_reduced = result.get("pages_reduced", pages)
            message = f"Reduced progress by **{pages_reduced} pages** for **'{book.title}'**."
        elif action == "set":
            await reading_service.set_reading_progress(user.id, book.id, pages, session_date)
            message = f"Set progress to **page {pages}** for **'{book.title}'**."
        else:
            return {"elements": [ui.text(f"Unknown action: {action}", style="error")], "suggestions": ["Help"], "metadata_updates": {}}
    except ReadingLimitError as e:
        return {"elements": [ui.text(e.message, style="warning")], "suggestions": ["Show progress", "Help"], "metadata_updates": {}}
    except ValueError as e:
        return {"elements": [ui.text(f"Couldn't update progress: {e}", style="error")], "suggestions": ["Show progress", "Help"], "metadata_updates": {}}

    progress = await reading_service.get_book_progress(user.id, book.id)
    elements = [ui.text(message, style="success")]
    if progress:
        elements.append(ui.book_progress_card(progress.model_dump(mode="json")))
    elements.append(ui.action_buttons([
        ui.button("Log More Pages", "log_reading", "primary", _book_ref(book)),
        ui.button("Show All Progress", "show_progress", "secondary"),
    ]))

    return {
        "elements": elements,
        "suggestions": ["Log more pages", "Show progress", "Search books"],
        "metadata_updates": {"last_book_title": book.title},
    }


async def execute_search_books(args: dict, context: dict) -> dict:
    query = args.get("query", "")
    search_by = args.get("search_by")
    conn = context.get("conn")

    if not query:
        return {"elements": [ui.text("Please provide a search term.", style="warning")], "suggestions": ["Help"], "metadata_updates": {}}

    # Backstop for recommendation requests the router's intercept didn't catch.
    # Searching Google Books for "recommended" returns medical guidelines.
    if _is_non_specific_query(query):
        logger.info("search_books: declined non-specific query %r", query)
        return {
            "elements": ui.recommendation_decline(),
            "suggestions": ui.SEARCH_EXAMPLES,
            "metadata_updates": {},
        }

    book_service = get_book_service(conn)
    books = await book_service.search_client.search_books(query, search_by)

    if not books:
        return {"elements": [ui.text(f"No books found matching '{query}'. Try a different search term.", style="info")], "suggestions": ["Search for another book", "Help"], "metadata_updates": {}}

    header = f"Books by **{query}**:" if search_by == "author" else f"Books matching **'{query}'**:"
    elements = [ui.text(header)]
    elements.append(ui.book_list([book.model_dump(mode="json") for book in books]))
    elements.append(ui.text("Say **track <book title>** to start tracking any of these books."))

    # Remember exactly which volumes were shown, so tracking one of them by title
    # resolves to the same edition instead of re-running the pipeline.
    return {
        "elements": elements,
        "suggestions": ["Track a book", "Search another", "Show my progress"],
        "metadata_updates": {"recent_search_results": _compact_search_results(books)},
    }


# Headers for ranked results, keyed by (sort_by, is_single_result).
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


async def execute_show_progress(args: dict, context: dict) -> dict:
    book_title = args.get("book_title")
    filter_type = args.get("filter")
    sort_by = args.get("sort_by")
    limit = args.get("limit")
    conn = context.get("conn")
    user = context.get("user")
    reading_service = get_reading_service(conn)

    # single-book progress
    if book_title:
        book, err = await _resolve_book(book_title, conn, context, args)
        if err:
            return err

        progress = await reading_service.get_book_progress(user.id, book.id)
        if not progress:
            return {
                "elements": [
                    ui.text(f"You haven't started reading **'{book_title}'** yet.", style="info"),
                    ui.action_buttons([ui.button("Start Tracking", "start_tracking", "primary", _book_ref(book))]),
                ],
                "suggestions": ["Start tracking", "Show all progress"],
                "metadata_updates": {},
            }

        elements = ui.single_book_progress(f"Your progress on **'{book.title}'**:", progress.model_dump(mode="json"))
        elements.append(ui.action_buttons([
            ui.button("Log Pages", "log_reading", "primary", _book_ref(book)),
            ui.button("Show All Progress", "show_progress", "secondary"),
        ]))
        return {
            "elements": elements,
            "suggestions": ["Log pages", "Show all progress", "Search books"],
            "metadata_updates": {"last_book_title": book.title},
        }

    # all-books progress (with optional filter handled by service layer now)
    all_progress = await reading_service.get_all_progress(
        user.id, filter_by=filter_type, sort_by=sort_by, limit=limit
    )

    if not all_progress and filter_type:
        labels = {"completed": "completed", "in_progress": "currently reading", "not_started": "not started"}
        return {
            "elements": [
                ui.text(f"No books matching filter: **{labels.get(filter_type, filter_type)}**.", style="info"),
                ui.action_buttons([
                    ui.button("Show All Progress", "show_progress", "secondary"),
                    ui.button("Search Books", "search_books", "secondary"),
                ]),
            ],
            "suggestions": ["Show all progress", "Search books"],
            "metadata_updates": {},
        }

    if not all_progress:
        return {
            "elements": [
                ui.text("You haven't tracked any reading yet!", style="info"),
                ui.action_buttons([ui.button("Search for a Book", "search_books", "primary")]),
            ],
            "suggestions": ["Search books", "Help"],
            "metadata_updates": {},
        }

    single = len(all_progress) == 1 and limit == 1
    if sort_by:
        header = _RANKED_HEADERS.get(
            (sort_by, single), _FILTER_HEADERS.get(filter_type, "Your reading progress:")
        )
    else:
        header = _FILTER_HEADERS.get(filter_type, "Your reading progress:")

    if single:
        # One ranked answer reads better as a card than as a one-item list.
        elements = ui.single_book_progress(header, all_progress[0].model_dump(mode="json"))
    else:
        elements = [ui.text(header)]
        elements.append(ui.book_list([p.model_dump(mode="json") for p in all_progress]))
    elements.append(ui.action_buttons([
        ui.button("Completed Books", "show_progress", "secondary", {"filter": "completed"}),
        ui.button("In Progress", "show_progress", "secondary", {"filter": "in_progress"}),
        ui.button("Search Books", "search_books", "secondary"),
    ]))
    return {"elements": elements, "suggestions": ["Log pages", "Search books", "Help"], "metadata_updates": {}}


async def execute_start_tracking(args: dict, context: dict) -> dict:
    book_title = args.get("book_title", "")
    # The model sometimes routes "I read 300 pages of X" here when X isn't
    # tracked yet. Honour the pages instead of silently starting from zero.
    pages = args.get("pages") or 0
    conn = context.get("conn")
    user = context.get("user")

    book, err = await _resolve_book(book_title, conn, context, args)
    if err:
        return err

    reading_service = get_reading_service(conn)
    existing_progress = await reading_service.get_book_progress(user.id, book.id)

    if existing_progress:
        if pages > 0:
            # Already tracked and pages were given — that's a log, not a start.
            return await execute_log_reading({**args, "action": "add"}, context)
        return {
            "elements": ui.single_book_progress(f"You're already tracking **'{book.title}'**!", existing_progress.model_dump(mode="json")),
            "suggestions": ["Log pages", "Show all progress", "Search books"],
            "metadata_updates": {"last_book_title": book.title},
        }

    try:
        await reading_service.add_reading_session(user.id, book.id, pages, None)
    except ReadingLimitError as e:
        return {"elements": [ui.text(e.message, style="warning")], "suggestions": ["Show progress", "Help"], "metadata_updates": {}}

    progress = await reading_service.get_book_progress(user.id, book.id)
    if pages > 0:
        opening = f"Added **'{book.title}'** to your reading list and logged **{pages} pages**."
    else:
        opening = f"Great! I've added **'{book.title}'** to your reading list. Start logging your pages whenever you're ready!"
    elements = [ui.text(opening, style="success")]
    if progress:
        elements.append(ui.book_progress_card(progress.model_dump(mode="json")))
    elements.append(ui.action_buttons([
        ui.button("Log Pages", "log_reading", "primary", _book_ref(book)),
        ui.button("Show All Progress", "show_progress", "secondary"),
    ]))
    return {
        "elements": elements,
        "suggestions": ["Log pages", "Show progress", "Search books"],
        "metadata_updates": {"last_book_title": book.title},
    }


_TOOL_DISPATCH = {
    "log_reading": execute_log_reading,
    "search_books": execute_search_books,
    "show_progress": execute_show_progress,
    "start_tracking": execute_start_tracking,
}


async def execute_tool(tool_name: str, args: dict, context: dict) -> dict:
    handler = _TOOL_DISPATCH.get(tool_name)
    if not handler:
        logger.warning("Unknown tool requested: %s", tool_name)
        return {
            "elements": [ui.text(f"Unknown tool: {tool_name}", style="error")],
            "suggestions": ["Help"],
            "metadata_updates": {},
        }
    logger.info("Executing tool: %s", tool_name)
    return await handler(args, context)
