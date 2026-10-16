import pytest_asyncio

from app import db


@pytest_asyncio.fixture
async def database(tmp_path):
    path = tmp_path / "finally.db"
    await db.init_db(str(path))
    return str(path)
