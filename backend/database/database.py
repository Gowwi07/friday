"""
FRIDAY — Database Connection & Session Management
Supports both SQLite (local dev) and PostgreSQL/Neon (production).
"""

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.models import Base
from config import get_settings

settings = get_settings()

# Build engine kwargs — SQLite needs check_same_thread=False, Postgres doesn't
_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # create_all does not add columns to an existing database. Keep this
        # small backwards-compatible migration here until Alembic is adopted.
        def has_memory_user_phone(sync_conn) -> bool:
            columns = inspect(sync_conn).get_columns("conversation_memory")
            return any(column["name"] == "user_phone" for column in columns)

        if not await conn.run_sync(has_memory_user_phone):
            await conn.execute(
                text("ALTER TABLE conversation_memory ADD COLUMN user_phone VARCHAR(50)")
            )


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
