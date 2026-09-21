import logging
from functools import cache

from langchain_core.language_models import BaseChatModel

from app.config.settings import settings

logger = logging.getLogger(__name__)


@cache
def get_langchain_llm() -> BaseChatModel | None:
    if (
        settings.azure_openai_endpoint
        and settings.azure_openai_api_key
        and settings.azure_openai_deployment
    ):
        from langchain_openai import AzureChatOpenAI

        logger.info(
            "LLM: Azure OpenAI (deployment=%s)", settings.azure_openai_deployment
        )
        return AzureChatOpenAI(
            openai_api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            azure_deployment=settings.azure_openai_deployment,
            model_name=settings.azure_openai_deployment,
            temperature=settings.llm_temperature,
            streaming=True,
        )

    if settings.openai_api_key and settings.openai_api_key.startswith("sk-"):
        from langchain_openai import ChatOpenAI

        logger.info("LLM: OpenAI (model=%s)", settings.openai_model)
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=settings.llm_temperature,
            streaming=True,
        )

    logger.warning("No LLM credentials found; the chat agent will be unavailable")
    return None
