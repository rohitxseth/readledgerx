from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config.settings import settings

async_engine = create_async_engine(
    settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20
)


async def get_db() -> AsyncIterator[AsyncConnection]:
    async with async_engine.begin() as conn:
        yield conn
