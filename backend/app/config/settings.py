from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS = {
    "",
    "your-secret-key",
    "replace-with-a-random-32-byte-string",
    "changeme",
    "secret",
}


class Settings(BaseSettings):
    database_url: str = Field(default="postgresql+asyncpg://user:password@localhost:5433/readledger")

    jwt_secret_key: str = Field(default="")
    algorithm: str = Field(default="HS256")

    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = Field(default="2024-02-15-preview")
    openai_api_key: str | None = None
    openai_model: str = Field(default="gpt-4")
    llm_temperature: float = Field(default=0.0)
    google_books_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _reject_insecure_jwt_secret(self) -> "Settings":
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
