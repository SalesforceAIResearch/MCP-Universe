"""
Database session manager.
"""
import contextlib
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class DatabaseSessionManager:
    """
    Manages asynchronous sessions and connections for a PostgreSQL database using SQLAlchemy.

    This class encapsulates the creation, management, and teardown of the SQLAlchemy engine
    and sessionmaker for asynchronous database operations.
    """

    def __init__(self):
        """
        Initialize the DatabaseSessionManager instance.
        """
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker | None = None

    def init(self, host: str):
        """
        Initialize the SQLAlchemy async engine and sessionmaker.

        Args:
            host (str): The database connection URL.
        """
        self._engine = create_async_engine(host)
        self._sessionmaker = async_sessionmaker(autocommit=False, bind=self._engine)

    async def close(self):
        """
        Close the SQLAlchemy async engine and reset the session manager.

        Raises:
            Exception: If the session manager was not initialized before calling this method.
        """
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        """
        Asynchronous context manager for acquiring a database connection.

        Yields:
            AsyncConnection: An open connection within a transaction context.

        Raises:
            Exception: If the session manager was not initialized.
        """
        if self._engine is None:
            raise Exception("DatabaseSessionManager is not initialized")

        async with self._engine.begin() as connection:
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """
        Asynchronous context manager for acquiring a database session.

        Yields:
            AsyncSession: An active SQLAlchemy async session.

        Raises:
            Exception: If the session manager was not initialized.
        """
        if self._sessionmaker is None:
            raise Exception("DatabaseSessionManager is not initialized")

        session = self._sessionmaker()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def create_all(self, connection: AsyncConnection):
        """Create all tables for testing purpose."""
        await connection.run_sync(Base.metadata.create_all)

    async def drop_all(self, connection: AsyncConnection):
        """Delete all tables for testing purpose."""
        await connection.run_sync(Base.metadata.drop_all)

    @property
    def engine(self) -> AsyncEngine:
        """Get DB engine."""
        return self._engine


sessionmanager = DatabaseSessionManager()


async def get_connection():
    """
    Dependency-like asynchronous generator that yields a database connection.

    This function can be used in contexts such as FastAPI dependencies to provide
    access to a database connection managed by the global `sessionmanager`.

    Yields:
        AsyncConnection: A SQLAlchemy asynchronous database connection.

    Raises:
        Exception: If the `sessionmanager` has not been initialized before use.
    """
    async with sessionmanager.connect() as conn:
        yield conn
