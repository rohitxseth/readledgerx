import logging
import warnings

from pydantic import BaseModel, Field

from app.config.llm_config import get_langchain_llm
from app.schemas.models import Book

warnings.filterwarnings(
    "ignore", 
    message=".*Expected `none` - serialized value may not be as expected.*", 
    category=UserWarning,
    module="pydantic.main"
)

logger = logging.getLogger(__name__)

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
        """
        Uses an LLM to correct, normalize, or formalize a fuzzy book query.
        """
        if not self.llm:
            logger.warning("LLM not configured. Falling back to raw query.")
            return None
            
        system_prompt = (
            "You are an expert librarian assistant. The user will provide a fuzzy or ambiguous query for a book. "
            "Your task is to normalize it into a formal search query (title and author if possible). "
            "If the query is clearly not about a book (e.g., 'hello', 'what is the weather'), mark it as invalid."
        )
        
        try:
            structured_llm = self.llm.with_structured_output(NormalizedQuery)
            messages = [
                ("system", system_prompt),
                ("user", f"Normalize this book query: '{raw_query}'")
            ]
            # using ainvoke for async LangChain execution
            response = await structured_llm.ainvoke(messages)
            return response
        except Exception as e:
            logger.error(f"Failed to normalize query with LLM: {e}")
            return None

    async def select_best_match(self, raw_query: str, results: list[Book]) -> Book | None:
        """
        Given a user query and a list of potentially matching Google Books results,
        uses an LLM to select the most relevant one.
        """
        if not results:
            return None
            
        if not self.llm:
            logger.warning("LLM not configured. Falling back to the first search result.")
            return results[0]
            
        if len(results) == 1:
            return results[0]
            
        system_prompt = (
            "You are an expert librarian assistant. The user searched for a book with a specific query. "
            "We found multiple potential matches on Google Books. Your task is to select the index of the "
            "book that best matches the user's intent based on the titles, authors, descriptions, and page counts. "
            "If absolutely none of the options are even close to what the user meant, return -1."
        )
        
        books_context = []
        for i, b in enumerate(results):
            author_str = ", ".join(b.authors) if b.authors else "Unknown Author"
            # Truncate description to save passing enormous tokens to LLM
            desc = b.description[:300] + "..." if b.description and len(b.description) > 300 else b.description
            
            books_context.append(
                f"[{i}] Title: {b.title}\n"
                f"    Author(s): {author_str}\n"
                f"    Pages: {b.page_count}\n"
                f"    Desc: {desc or 'None'}"
            )
            
        books_str = "\n\n".join(books_context)
        
        try:
            structured_llm = self.llm.with_structured_output(BestMatchSelection)
            messages = [
                ("system", system_prompt),
                ("user", f"User query: '{raw_query}'\n\nSearch Results:\n{books_str}")
            ]
            
            response = await structured_llm.ainvoke(messages)
            idx = response.selected_index
            
            if 0 <= idx < len(results):
                logger.info(f"LLM selected result index {idx}: '{results[idx].title}' for query '{raw_query}'.")
                return results[idx]
            else:
                logger.info(f"LLM determined no results matched the query '{raw_query}'.")
                return None
                
        except Exception as e:
            logger.error(f"Failed to select best match with LLM: {e}")
            return results[0]  # Fallback to the first result
