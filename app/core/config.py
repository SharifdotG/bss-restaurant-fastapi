from functools import lru_cache
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BeforeValidator, Field, model_validator
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
    # business days, order numbers and reports follow this timezone, not UTC
    restaurant_tz: str = "Asia/Dhaka"
    environment: Literal["local", "staging", "production"] = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"

    cors_origins: CommaList = []
    rate_limit_enabled: bool = True
    # how many proxies sit in front of the app, used to find the real client ip in
    # X-Forwarded-For. 0 means use the address of the connection itself
    trusted_proxy_hops: int = Field(0, ge=0, le=5)
    docs_enabled: bool = True

    # for neon use the pooled connection string, migrations derive the direct one from it.
    # database_url_direct is only needed for databases where that doesn't work
    database_url: str = "postgresql://postgres:postgres@localhost:5432/restaurant"
    database_url_direct: str | None = None
    db_echo: bool = False

    secret_key: str = DEV_SECRET
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # "local" saves files under local_upload_dir and serves them from /media,
    # "r2" uploads to cloudflare r2 and builds urls from r2_public_url
    storage_backend: Literal["local", "r2"] = "local"
    local_upload_dir: str = "uploads"
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_public_url: str = ""
    max_upload_mb: int = 5

    @model_validator(mode="after")
    def _check_settings(self) -> Self:
        try:
            ZoneInfo(self.restaurant_tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone: {self.restaurant_tz}") from None
        if self.environment != "local" and (
            self.secret_key == DEV_SECRET or len(self.secret_key) < 32
        ):
            raise ValueError("SECRET_KEY must be set to a random value of at least 32 characters")
        if self.storage_backend == "r2":
            required = ["r2_account_id", "r2_access_key_id", "r2_secret_access_key"]
            required += ["r2_bucket", "r2_public_url"]
            missing = [name for name in required if not getattr(self, name)]
            if missing:
                raise ValueError(f"missing r2 settings: {', '.join(missing)}")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def async_database_url(self) -> URL:
        return to_asyncpg_url(self.database_url)

    @property
    def migration_database_url(self) -> URL:
        if self.database_url_direct:
            return to_asyncpg_url(self.database_url_direct)
        url = to_asyncpg_url(self.database_url)
        # neon's pooled host is the direct host with "-pooler" added to the endpoint id,
        # migrations should skip pgbouncer
        if url.host and "-pooler." in url.host:
            url = url.set(host=url.host.replace("-pooler.", ".", 1))
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
