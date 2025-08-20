import asyncio
from contextlib import ExitStack

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pytest_postgresql import factories
from pytest_postgresql.janitor import DatabaseJanitor

from mcpuniverse.app.server import init_app
from mcpuniverse.app.db.database import get_connection, sessionmanager
from mcpuniverse.app.db.sqlc.models_sqlalchemy import *


@pytest.fixture(autouse=True)
def app():
    with ExitStack():
        yield init_app(is_test=True)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


test_db = factories.postgresql_proc(port=None, dbname="test_db")


@pytest.fixture(scope="session")
def event_loop(request):
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def connection_test(test_db, event_loop):
    pg_host = test_db.host
    pg_port = test_db.port
    pg_user = test_db.user
    pg_db = test_db.dbname
    pg_password = test_db.password

    with DatabaseJanitor(
            user=pg_user, host=pg_host, port=pg_port, version=test_db.version, dbname=pg_db, password=pg_password
    ):
        connection_str = f"postgresql+psycopg://{pg_user}:@{pg_host}:{pg_port}/{pg_db}"
        sessionmanager.init(connection_str)
        yield
        await sessionmanager.close()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def create_tables(connection_test):
    async with sessionmanager.connect() as connection:
        await sessionmanager.drop_all(connection)
        await sessionmanager.create_all(connection)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def connection_override(app, connection_test):
    async def get_connection_override():
        async with sessionmanager.connect() as conn:
            yield conn

    app.dependency_overrides[get_connection] = get_connection_override
