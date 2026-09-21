import logging

from app.config.settings import settings

logger = logging.getLogger(__name__)


# =====================================================================
# LangChain LLM (used by the router agent / tool-calling architecture)
# =====================================================================

_langchain_llm = None


def get_langchain_llm():
    """Return a LangChain chat model configured from settings.

    Supports Azure OpenAI and OpenAI. Returns None if no credentials are set.
    The instance is lazily created and cached.
    """
    global _langchain_llm
    if _langchain_llm is not None:
        return _langchain_llm

    if settings.azure_openai_endpoint and settings.azure_openai_api_key and settings.azure_openai_deployment:
        from langchain_openai import AzureChatOpenAI

        _langchain_llm = AzureChatOpenAI(
            openai_api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            azure_deployment=settings.azure_openai_deployment,
            model_name=settings.azure_openai_deployment,
            temperature=settings.llm_temperature,
            streaming=True,
        )
        logger.info("LangChain LLM: Azure OpenAI (deployment=%s)", settings.azure_openai_deployment)
        return _langchain_llm

    if settings.openai_api_key and settings.openai_api_key.startswith("sk-"):
        from langchain_openai import ChatOpenAI

        _langchain_llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=settings.llm_temperature,
            streaming=True,
        )
        logger.info("LangChain LLM: OpenAI (model=%s)", settings.openai_model)
        return _langchain_llm

    logger.warning("No LLM credentials found — router agent will be unavailable")
    return None
