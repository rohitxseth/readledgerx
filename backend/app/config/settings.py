from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    database_url: str = Field(default="postgresql+asyncpg://user:password@localhost:5433/readledger")
    
    # Auth
    jwt_secret_key: str = Field(default="your-secret-key")
    algorithm: str = Field(default="HS256")
    
    # LLM configurations
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_deployment: Optional[str] = None
    azure_openai_api_version: str = Field(default="2024-02-15-preview")
    openai_api_key: Optional[str] = None
    openai_model: str = Field(default="gpt-4")
    llm_temperature: float = Field(default=0.0)
    google_books_api_key: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
