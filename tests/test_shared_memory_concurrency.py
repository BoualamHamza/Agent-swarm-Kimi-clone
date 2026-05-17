"""Concurrent shared-memory smoke tests.

Motivated by a real LangSmith trace where three workers read shared memory
at startup, saw it empty (because the producer hadn't written yet), and
bailed. The shared-memory plumbing itself is correct — these tests pin that
guarantee so future refactors don't break it.

They also cover the new `wait_for_memory` tool: agents that legitimately
depend on another agent's output can block instead of giving up.
"""
from __future__ import annotations

import asyncio

import pytest

from app.tools import ToolExecutor


def _make_pool(n: int) -> tuple[dict[str, str], asyncio.Lock, list[ToolExecutor]]:
    shared: dict[str, str] = {}
    lock = asyncio.Lock()
    return shared, lock, [ToolExecutor(shared, lock) for _ in range(n)]


@pytest.mark.asyncio
async def test_all_executors_share_the_same_dict_by_reference():
    """The bedrock invariant: every ToolExecutor in a swarm run sees the
    SAME dict object, so a write by one is visible to all the others."""
    shared, _lock, executors = _make_pool(4)
    for ex in executors:
        assert ex.shared_memory is shared


@pytest.mark.asyncio
async def test_write_by_one_visible_to_all_others_immediately():
    """Concurrent reads after a write return the written value."""
    shared, _lock, (e1, e2, e3, e4) = _make_pool(4)

    await e1.execute("write_to_shared_memory", {"key": "primes", "value": "[2,3,5]"})

    results = await asyncio.gather(*(
        ex.execute("read_shared_memory", {"key": "primes"}) for ex in (e2, e3, e4)
    ))
    assert all(r == "[2,3,5]" for r in results)


@pytest.mark.asyncio
async def test_concurrent_reads_pre_write_are_empty_as_expected():
    """The trace scenario: 4 agents spawn, 3 read immediately and see empty.
    This is correct behavior, not a bug — the producer simply hasn't run yet."""
    _shared, _lock, executors = _make_pool(4)
    results = await asyncio.gather(*(
        ex.execute("read_shared_memory", {"key": "all"}) for ex in executors
    ))
    assert all("empty" in r for r in results)


@pytest.mark.asyncio
async def test_wait_for_memory_resolves_when_producer_writes():
    """Three consumers wait_for_memory(`primes`); the producer writes; all
    three resolve to the written value."""
    shared, lock, executors = _make_pool(4)
    producer, *consumers = executors

    async def consume(ex: ToolExecutor) -> str:
        return await ex.execute("wait_for_memory", {"key": "primes", "timeout_sec": 5})

    # Start the 3 consumers, give them a tick to enter the poll loop,
    # then have the producer write.
    consumer_tasks = [asyncio.create_task(consume(c)) for c in consumers]
    await asyncio.sleep(0.05)
    await producer.execute("write_to_shared_memory", {"key": "primes", "value": "[2,3,5]"})

    results = await asyncio.gather(*consumer_tasks)
    assert all(r == "[2,3,5]" for r in results)


@pytest.mark.asyncio
async def test_wait_for_memory_times_out_cleanly():
    """If the producer never writes, wait_for_memory returns a timeout error
    string — it does not raise."""
    _shared, _lock, [ex] = _make_pool(1)
    out = await ex.execute("wait_for_memory", {"key": "absent", "timeout_sec": 1})
    assert "timed out" in out.lower()
    assert "absent" in out


@pytest.mark.asyncio
async def test_wait_for_memory_returns_immediately_if_key_already_present():
    """If the key is already written when an agent calls wait_for_memory,
    it shouldn't sleep — just return."""
    shared, lock, [ex] = _make_pool(1)
    shared["primes"] = "[2,3]"

    start = asyncio.get_event_loop().time()
    out = await ex.execute("wait_for_memory", {"key": "primes", "timeout_sec": 30})
    elapsed = asyncio.get_event_loop().time() - start

    assert out == "[2,3]"
    assert elapsed < 0.2, f"wait_for_memory unexpectedly slow: {elapsed:.2f}s"
