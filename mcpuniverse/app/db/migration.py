"""
Utilities for database migration.
"""
import os
import asyncio
import threading
from typing import Dict, List
from sqlalchemy import text
from mcpuniverse.app.db.database import sessionmanager


def _load_migration_sqls(folder: str = "") -> Dict[str, List[str]]:
    """Load migration SQLs defined in the folder."""
    if folder == "":
        folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), "migration")
    if not os.path.isdir(folder):
        raise ValueError(f"Path {folder} is not a folder")

    ups, downs = [], []
    for filename in os.listdir(folder):
        if filename.endswith("up.sql"):
            ups.append(filename)
        elif filename.endswith("down.sql"):
            downs.append(filename)
    ups = sorted(ups)
    downs = sorted(downs, reverse=True)

    up_sqls, down_sqls = [], []
    for filename in ups:
        with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
            up_sqls.append(f.read())
    for filename in downs:
        with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
            down_sqls.append(f.read())
    return {"up": up_sqls, "down": down_sqls}


def run_migration(folder: str = ""):
    """
    Run database migration.

    Args:
        folder (str): The folder including migration SQLs.
    """

    async def _migrate():
        sqls = _load_migration_sqls(folder)
        async with sessionmanager.connect() as conn:
            try:
                for sql in sqls["up"]:
                    await conn.execute(text(sql))
            except Exception:
                pass

    thread = threading.Thread(target=asyncio.run, args=(_migrate(),))
    thread.start()
    thread.join()
