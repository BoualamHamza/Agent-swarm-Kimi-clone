"""Pluggable shared-memory backends.

`run_swarm` hydrates `shared_memory` from the store at the start of a run and
treats the in-process dict as a write-through cache. Persisted backends keep
findings around across swarm runs (and process restarts), keyed by `session_id`.

Default backend is `InMemoryStore` — equivalent to today's behavior. Set
`SWARM_MEMORY_BACKEND=sqlite` (with optional `SWARM_MEMORY_PATH`) to swap.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol, runtime_checkable

import aiosqlite


@runtime_checkable
class SharedMemoryStore(Protocol):
    async def get_all(self, session_id: str) -> dict[str, str]: ...
    async def put(self, session_id: str, key: str, value: str) -> None: ...


class InMemoryStore:
    """Process-local; sessions die with the process. Default backend."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()

    async def get_all(self, session_id: str) -> dict[str, str]:
        async with self._lock:
            return dict(self._data.get(session_id, {}))

    async def put(self, session_id: str, key: str, value: str) -> None:
        async with self._lock:
            self._data.setdefault(session_id, {})[key] = value


class SQLiteStore:
    """Persistent; survives process restart. One write at a time per file."""

    def __init__(self, path: str = "swarm_memory.db") -> None:
        self._path = path
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _ensure_schema(self, db: aiosqlite.Connection) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await db.execute(
                "CREATE TABLE IF NOT EXISTS memory ("
                "  session_id TEXT NOT NULL,"
                "  key        TEXT NOT NULL,"
                "  value      TEXT NOT NULL,"
                "  updated_at TEXT NOT NULL,"
                "  PRIMARY KEY (session_id, key)"
                ")"
            )
            await db.commit()
            self._initialized = True

    async def get_all(self, session_id: str) -> dict[str, str]:
        async with aiosqlite.connect(self._path) as db:
            await self._ensure_schema(db)
            cursor = await db.execute(
                "SELECT key, value FROM memory WHERE session_id = ?", (session_id,)
            )
            rows = await cursor.fetchall()
            return {k: v for k, v in rows}

    async def put(self, session_id: str, key: str, value: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await self._ensure_schema(db)
            await db.execute(
                "INSERT OR REPLACE INTO memory(session_id, key, value, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, key, value, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()


@lru_cache(maxsize=1)
def get_store() -> SharedMemoryStore:
    """Return the process-wide store, selected by env var.

    Mirrors the get_openrouter() / get_tavily() pattern so the FastAPI app
    shares one store across requests.
    """
    backend = os.getenv("SWARM_MEMORY_BACKEND", "inmemory").lower()
    if backend == "sqlite":
        return SQLiteStore(os.getenv("SWARM_MEMORY_PATH", "swarm_memory.db"))
    return InMemoryStore()
