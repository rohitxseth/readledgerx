"""Chat UI helpers — dict builders for Backend-Driven UI elements.

All functions return plain dicts. The frontend's BduiRenderer
switches on element["type"] and renders the appropriate widget.
"""


def text(content: str, style: str = "default") -> dict:
    """Markdown text block. style: default | success | warning | error | info."""
    return {"type": "text", "content": content, "style": style}


def action_buttons(buttons: list, layout: str = "horizontal") -> dict:
    return {"type": "action_buttons", "layout": layout, "buttons": buttons}


def button(label: str, action: str, variant: str = "primary", payload: dict = None) -> dict:
    return {
        "label": label,
        "action": action,
        "variant": variant,
        "payload": payload or {},
    }


def progress(message: str, percent: int = None) -> dict:
    return {"type": "progress", "message": message, "percent": percent}


def book_card(book: dict) -> dict:
    return {"type": "book_card", "data": book}


def book_progress_card(progress_data: dict) -> dict:
    return {"type": "book_progress", "data": progress_data}


def book_list(books: list) -> dict:
    return {"type": "book_list", "books": books}


# Composite helpers

def composite(elements: list) -> dict:
    """Bundle multiple UI elements into one response."""
    return {"type": "composite", "elements": elements}


def text_response(content: str, style: str = "default") -> dict:
    return composite([text(content, style)])


def error_response(message: str) -> dict:
    return composite([text(message, style="error")])


def help_card() -> dict:
    """Grid card showing available bot features."""
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


def single_book_progress(message: str, progress_data: dict) -> list:
    elements = [text(message)]
    if progress_data:
        elements.append(book_progress_card(progress_data))
    return elements


def summarize_elements(elements: list, include_text: bool = True) -> list[str]:
    """Build a plain-text summary from BDUI elements (for DB storage / LLM context)."""
    parts: list[str] = []
    for el in elements:
        t = el.get("type", "")
        if t == "text":
            if include_text:
                parts.append(el.get("content", ""))
        elif t == "action_buttons":
            labels = [b.get("label", "") for b in el.get("buttons", [])]
            if labels:
                parts.append(f"[Actions: {', '.join(labels)}]")
        elif t == "progress":
            parts.append(f"[Progress: {el.get('message', '')}]")
        elif t == "book_card":
            data = el.get("data", {})
            parts.append(f"[Book: {data.get('title', 'Unknown')}]")
        elif t == "book_progress":
            data = el.get("data", {})
            parts.append(
                f"[Progress: {data.get('title', 'Unknown')} — "
                f"{data.get('progress_percentage', 0)}%]"
            )
    return parts
