SEARCH_EXAMPLES = ["Sci-fi books", "Books by Ayn Rand", "Books about stoicism"]


def text(content: str, style: str = "default") -> dict:
    return {"type": "text", "content": content, "style": style}


def action_buttons(buttons: list[dict], layout: str = "horizontal") -> dict:
    return {"type": "action_buttons", "layout": layout, "buttons": buttons}


def button(
    label: str, action: str, variant: str = "primary", payload: dict | None = None
) -> dict:
    return {
        "label": label,
        "action": action,
        "variant": variant,
        "payload": payload or {},
    }


def progress(message: str, percent: int | None = None) -> dict:
    return {"type": "progress", "message": message, "percent": percent}


def book_progress_card(progress_data: dict) -> dict:
    return {"type": "book_progress", "data": progress_data}


def book_list(books: list[dict]) -> dict:
    return {"type": "book_list", "books": books}


def composite(elements: list[dict]) -> dict:
    return {"type": "composite", "elements": elements}


def help_card() -> dict:
    return {
        "type": "help_card",
        "title": "Here's how I can assist you:",
        "features": [
            {
                "icon": "book-open",
                "title": "Search for books",
                "description": "Find books by title, author, or keyword.",
                "example": '"Search for books by Brandon Sanderson"',
            },
            {
                "icon": "bookmark",
                "title": "Start tracking a book",
                "description": "Add a book to your reading list and track progress.",
                "example": '"Start tracking The Hobbit"',
            },
            {
                "icon": "pen-tool",
                "title": "Log your reading",
                "description": "Record pages you've read or update an existing book.",
                "example": '"Log 20 pages for Dune"',
            },
            {
                "icon": "trending-up",
                "title": "View your reading progress",
                "description": "See stats and progress for books you're reading.",
                "example": '"Show my progress"',
            },
        ],
    }


def recommendation_decline() -> list[dict]:
    return [
        text(
            "I can't recommend books yet — that isn't supported. "
            "Here's what I can do instead:\n\n"
            "- **Search by author** — *books by Ayn Rand*\n"
            "- **Search by genre** — *sci-fi books*\n"
            "- **Search by topic** — *books about stoicism*\n"
            "- **Track a book you already have in mind** — *start tracking Dune*",
            style="info",
        ),
        action_buttons(
            [
                button(
                    "Search by genre", "search_prompt", "secondary", {"by": "genre"}
                ),
                button(
                    "Search by author", "search_prompt", "secondary", {"by": "author"}
                ),
                button(
                    "Search by topic", "search_prompt", "secondary", {"by": "topic"}
                ),
            ]
        ),
    ]


def single_book_progress(message: str, progress_data: dict) -> list[dict]:
    return [text(message), book_progress_card(progress_data)]


def summarize_elements(elements: list[dict], include_text: bool = True) -> list[str]:
    parts = []
    for element in elements:
        kind = element.get("type", "")
        if kind == "text":
            if include_text:
                parts.append(element.get("content", ""))
        elif kind == "action_buttons":
            labels = [b.get("label", "") for b in element.get("buttons", [])]
            if labels:
                parts.append(f"[Actions: {', '.join(labels)}]")
        elif kind == "progress":
            parts.append(f"[Progress: {element.get('message', '')}]")
        elif kind == "book_progress":
            data = element.get("data", {})
            parts.append(
                f"[Progress: {data.get('title', 'Unknown')} — "
                f"{data.get('progress_percentage', 0)}%]"
            )
    return parts
