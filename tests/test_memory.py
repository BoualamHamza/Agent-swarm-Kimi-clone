"""Tests for the SharedMemoryStore implementations + ToolExecutor write-through."""
from __future__ import annotations

import asyncio

import pytest


# ─── InMemoryStore ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inmemory_put_then_get_all():
    from app.memory import InMemoryStore

    store = InMemoryStore()
    await store.put("s1", "k", "v")
    assert await store.get_all("s1") == {"k": "v"}


@pytest.mark.asyncio
async def test_inmemory_namespaces_by_session():
    from app.memory import InMemoryStore

    store = InMemoryStore()
    await store.put("s1", "shared_key", "value-A")
    await store.put("s2", "shared_key", "value-B")

    assert await store.get_all("s1") == {"shared_key": "value-A"}
    assert await store.get_all("s2") == {"shared_key": "value-B"}


@pytest.mark.asyncio
async def test_inmemory_get_all_empty_session():
    from app.memory import InMemoryStore

    assert await InMemoryStore().get_all("never-touched") == {}


@pytest.mark.asyncio
async def test_inmemory_put_overwrites_same_key():
    from app.memory import InMemoryStore

    store = InMemoryStore()
    await store.put("s1", "k", "first")
    await store.put("s1", "k", "second")
    assert await store.get_all("s1") == {"k": "second"}


# ─── SQLiteStore ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sqlite_put_then_get_all(tmp_path):
    from app.memory import SQLiteStore

    store = SQLiteStore(str(tmp_path / "mem.db"))
    await store.put("s1", "k", "v")
    assert await store.get_all("s1") == {"k": "v"}


@pytest.mark.asyncio
async def test_sqlite_persists_across_instances(tmp_path):
    """The whole point of SQLiteStore — survives process restart."""
    from app.memory import SQLiteStore

    db_path = str(tmp_path / "mem.db")
    s1 = SQLiteStore(db_path)
    await s1.put("session-a", "finding", "important")

    # Fresh instance, same file — must see the prior write.
    s2 = SQLiteStore(db_path)
    assert await s2.get_all("session-a") == {"finding": "important"}


@pytest.mark.asyncio
async def test_sqlite_namespaces_by_session(tmp_path):
    from app.memory import SQLiteStore

    store = SQLiteStore(str(tmp_path / "mem.db"))
    await store.put("s1", "shared_key", "value-A")
    await store.put("s2", "shared_key", "value-B")

    assert await store.get_all("s1") == {"shared_key": "value-A"}
    assert await store.get_all("s2") == {"shared_key": "value-B"}


@pytest.mark.asyncio
async def test_sqlite_put_overwrites_same_key(tmp_path):
    from app.memory import SQLiteStore

    store = SQLiteStore(str(tmp_path / "mem.db"))
    await store.put("s1", "k", "first")
    await store.put("s1", "k", "second")
    assert await store.get_all("s1") == {"k": "second"}


# ─── ToolExecutor write-through ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_writes_through_to_store():
    from app.memory import InMemoryStore
    from app.tools import ToolExecutor

    store = InMemoryStore()
    sid = "test-session"
    mem: dict[str, str] = {}
    ex = ToolExecutor(mem, asyncio.Lock(), store=store, session_id=sid)

    out = await ex.execute("write_to_shared_memory", {"key": "k", "value": "v"})
    await ex.close()

    assert "Stored" in out
    assert mem == {"k": "v"}                          # in-process cache updated
    assert await store.get_all(sid) == {"k": "v"}     # persisted


@pytest.mark.asyncio
async def test_executor_works_without_store():
    """Backwards compat — executors created without a store keep working."""
    from app.tools import ToolExecutor

    mem: dict[str, str] = {}
    ex = ToolExecutor(mem, asyncio.Lock())  # no store/session_id

    await ex.execute("write_to_shared_memory", {"key": "k", "value": "v"})
    await ex.close()

    assert mem == {"k": "v"}


@pytest.mark.asyncio
async def test_executor_store_failure_does_not_fail_tool_call(caplog):
    """A broken store must not turn every memory write into an error for the agent."""
    from app.memory import SharedMemoryStore
    from app.tools import ToolExecutor

    class BrokenStore:
        async def get_all(self, session_id: str) -> dict[str, str]:
            return {}
        async def put(self, session_id: str, key: str, value: str) -> None:
            raise RuntimeError("disk full")

    # structural typing — BrokenStore satisfies the protocol
    broken: SharedMemoryStore = BrokenStore()  # type: ignore[assignment]
    mem: dict[str, str] = {}
    ex = ToolExecutor(mem, asyncio.Lock(), store=broken, session_id="s1")

    out = await ex.execute("write_to_shared_memory", {"key": "k", "value": "v"})
    await ex.close()

    assert "Stored" in out          # tool call still succeeds for the agent
    assert mem == {"k": "v"}        # in-process write happened
