import os
import tempfile

# must happen before anything from app is imported, settings are read on import
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/restaurant_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["DATABASE_URL_DIRECT"] = ""
os.environ["ENVIRONMENT"] = "local"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_UPLOAD_DIR"] = tempfile.mkdtemp(prefix="restaurant-test-uploads-")

import asyncio  # noqa: E402
from collections.abc import AsyncIterator, Awaitable, Callable  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import NullPool, text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings, to_asyncpg_url  # noqa: E402
from app.core.database import get_session  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User, UserRole  # noqa: E402

DEFAULT_PASSWORD = "Password123"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    url = to_asyncpg_url(TEST_DATABASE_URL)
    if not url.database or not url.database.endswith("_test"):
        raise RuntimeError("refusing to run tests against a database not ending in _test")

    async def create_db() -> None:
        conn = await asyncpg.connect(
            user=url.username,
            password=url.password,
            host=url.host,
            port=url.port,
            database="postgres",
        )
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", url.database
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{url.database}"')
        finally:
            await conn.close()

    asyncio.run(create_db())
    # run the real migrations, so they get tested too
    command.upgrade(Config("alembic.ini"), "head")


# NullPool: every test runs in its own event loop, pooled connections can't be shared
test_engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
TestSession = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)


async def _override_session() -> AsyncIterator[AsyncSession]:
    async with TestSession() as session:
        yield session


app.dependency_overrides[get_session] = _override_session


@pytest.fixture(autouse=True)
async def _clean_tables(anyio_backend: str) -> AsyncIterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with test_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with TestSession() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        yield client


type UserFactory = Callable[..., Awaitable[User]]


@pytest.fixture
def make_user(session: AsyncSession) -> UserFactory:
    counter = 0

    async def factory(role: UserRole = UserRole.WAITER, **kwargs) -> User:
        nonlocal counter
        counter += 1
        user = User(
            email=kwargs.pop("email", f"user{counter}@example.com"),
            password_hash=hash_password(kwargs.pop("password", DEFAULT_PASSWORD)),
            first_name=kwargs.pop("first_name", "Test"),
            last_name=kwargs.pop("last_name", f"User{counter}"),
            role=role,
            **kwargs,
        )
        session.add(user)
        await session.commit()
        return user

    return factory


def auth_header(user: User) -> dict[str, str]:
    token, _ = create_access_token(user.id, user.role)
    return {"Authorization": f"Bearer {token}"}
