from sqlalchemy.ext.asyncio import create_async_engine
from app.config.settings import settings

DATABASE_URL = settings.database_url

kwargs = {"echo": False, "pool_pre_ping": True}
if not DATABASE_URL.startswith("sqlite"):
    kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
    })

async_engine = create_async_engine(DATABASE_URL, **kwargs)


async def get_db():
    async with async_engine.begin() as conn:
        yield conn
