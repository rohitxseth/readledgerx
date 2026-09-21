import logging
import warnings

from pydantic import BaseModel, Field

from app.config.llm_config import get_langchain_llm
from app.schemas.models import Book

# LangChain's structured output trips a spurious pydantic serializer warning
# on every call.
warnings.filterwarnings(
    "ignore",
    message=".*Expected `none` - serialized value may not be as expected.*",
    category=UserWarning,
    module="pydantic.main",
)

logger = logging.getLogger(__name__)

_NORMALIZE_PROMPT = (
    "You are an expert librarian assistant. The user will provide a fuzzy or ambiguous query for a book. "
    "Your task is to normalize it into a formal search query (title and author if possible). "
    "If the query is clearly not about a book (e.g., 'hello', 'what is the weather'), mark it as invalid."
)

_SELECT_PROMPT = (
    "You are an expert librarian assistant. The user searched for a book with a specific query. "
    "We found multiple potential matches on Google Books. Your task is to select the index of the "
    "book that best matches the user's intent based on the titles, authors, descriptions, and page counts. "
    "If absolutely none of the options are even close to what the user meant, return -1."
)


class NormalizedQuery(BaseModel):
    normalized_query: str = Field(
        description="The formal, normalized book title and author extracted from the query. "
        "E.g., 'harry potter 1' -> 'Harry Potter and the Sorcerer\\'s Stone'. "
        "If the query is already formal, leave it as is."
    )
    is_valid_book_query: bool = Field(
        description="True if the user's query seems to be requesting a book, False if it's completely unrelated."
    )


class BestMatchSelection(BaseModel):
    selected_index: int = Field(
        description="The 0-based index of the best matching book from the provided list. "
        "Return -1 if none of the results match the user's intended book."
    )


class BookIntelligenceService:
    def __init__(self):
        self.llm = get_langchain_llm()

    async def normalize_query(self, raw_query: str) -> NormalizedQuery | None:
        if not self.llm:
            return None
        try:
            return await self.llm.with_structured_output(NormalizedQuery).ainvoke(
                [
                    ("system", _NORMALIZE_PROMPT),
                    ("user", f"Normalize this book query: '{raw_query}'"),
                ]
            )
        except Exception:
            logger.exception("Query normalization failed; using the raw query")
            return None

    async def select_best_match(
        self, raw_query: str, results: list[Book]
    ) -> Book | None:
        if not self.llm or len(results) == 1:
            return results[0]

        candidates = []
        for i, book in enumerate(results):
            authors = ", ".join(book.authors) if book.authors else "Unknown Author"
            description = book.description or "None"
            if len(description) > 300:
                description = description[:300] + "..."
            candidates.append(
                f"[{i}] Title: {book.title}\n"
                f"    Author(s): {authors}\n"
                f"    Pages: {book.page_count}\n"
                f"    Desc: {description}"
            )
        candidate_list = "\n\n".join(candidates)

        try:
            response = await self.llm.with_structured_output(
                BestMatchSelection
            ).ainvoke(
                [
                    ("system", _SELECT_PROMPT),
                    (
                        "user",
                        f"User query: '{raw_query}'\n\nSearch Results:\n{candidate_list}",
                    ),
                ]
            )
            index = response.selected_index
        except Exception:
            logger.exception("Best-match selection failed; using the first result")
            return results[0]

        return results[index] if 0 <= index < len(results) else None
