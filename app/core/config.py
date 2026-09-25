from functools import lru_cache
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


def _split_csv(value: Any) -> Any:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


CommaList = Annotated[list[str], NoDecode, BeforeValidator(_split_csv)]


def to_asyncpg_url(raw: str) -> URL:
    """Accept a plain libpq style URL (like the one Neon gives you) and make it asyncpg friendly."""
    url = make_url(raw)
    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+asyncpg")

    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    # asyncpg doesn't know about channel_binding, it negotiates SCRAM on its own
    query.pop("channel_binding", None)
    if sslmode and "ssl" not in query:
        query["ssl"] = sslmode
    return url.set(query=query)


DEV_SECRET = "dev-only-secret-do-not-use-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BSS Restaurant API"
    environment: Literal["local", "staging", "production"] = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"

    cors_origins: CommaList = []
    docs_enabled: bool = True

    # pooled connection for the app, direct one for migrations (falls back to the pooled one)
    database_url: str = "postgresql://postgres:postgres@localhost:5432/restaurant"
    database_url_direct: str | None = None
    db_echo: bool = False

    secret_key: str = DEV_SECRET
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    @model_validator(mode="after")
    def _check_secret(self) -> Self:
        if self.environment != "local" and (
            self.secret_key == DEV_SECRET or len(self.secret_key) < 32
        ):
            raise ValueError("SECRET_KEY must be set to a random value of at least 32 characters")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def async_database_url(self) -> URL:
        return to_asyncpg_url(self.database_url)

    @property
    def migration_database_url(self) -> URL:
        return to_asyncpg_url(self.database_url_direct or self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
