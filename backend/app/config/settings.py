from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
from typing import Optional

# Placeholder values that must never reach a running app. Signing JWTs with a
# value that appears in the repo lets anyone forge a token for any user.
_INSECURE_SECRETS = {
    "",
    "your-secret-key",
    "replace-with-a-random-32-byte-string",
    "changeme",
    "secret",
}


class Settings(BaseSettings):
    database_url: str = Field(default="postgresql+asyncpg://user:password@localhost:5433/readledger")

    # Auth — no default on purpose: see _reject_insecure_jwt_secret below.
    jwt_secret_key: str = Field(default="")
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
        extra="ignore",
    )

    @model_validator(mode="after")
    def _reject_insecure_jwt_secret(self) -> "Settings":
        """Fail at startup rather than silently signing tokens with a known key.

        This used to default to "your-secret-key", which meant a misconfigured
        deployment booted successfully and issued forgeable tokens with no
        warning anywhere. Refusing to start is the safer failure mode.
        """
        if self.jwt_secret_key.strip() in _INSECURE_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY is missing or set to a placeholder value. "
                "Generate one with:\n"
                '  python -c "import secrets; print(secrets.token_urlsafe(32))"\n'
                "then set it in backend/.env (see backend/.env.example)."
            )
        if len(self.jwt_secret_key) < 32:
            raise ValueError(
                f"JWT_SECRET_KEY is too short ({len(self.jwt_secret_key)} chars). "
                "Use at least 32 characters."
            )
        return self


settings = Settings()
