"""Tests for the run_python tool (E2B sandbox integration).

The E2B SDK is stubbed via monkeypatch — we never hit the real E2B API.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest


# ─── Stub AsyncSandbox ───────────────────────────────────────────────────────


class StubSandbox:
    """Records run_code/kill calls and returns crafted Execution results."""

    def __init__(self) -> None:
        self.run_calls: list[tuple[str, int]] = []
        self.killed = False
        self.next_result: Any = SimpleNamespace(
            text="",
            logs=SimpleNamespace(stdout=[], stderr=[]),
            error=None,
        )
        self.next_exc: BaseException | None = None

    async def run_code(self, code: str, *, timeout: int = 30, **_: Any) -> Any:
        self.run_calls.append((code, timeout))
        if self.next_exc is not None:
            raise self.next_exc
        return self.next_result

    async def kill(self) -> None:
        self.killed = True


@pytest.fixture
def stub_sandbox(monkeypatch):
    sb = StubSandbox()
    counter = {"created": 0}

    class _AsyncSandbox:
        @staticmethod
        async def create(**_: Any) -> StubSandbox:
            counter["created"] += 1
            return sb

    monkeypatch.setattr("app.tools.AsyncSandbox", _AsyncSandbox)
    return sb, counter


# ─── Schema ──────────────────────────────────────────────────────────────────


def test_run_python_schema_is_registered():
    from app.tools import TOOL_SCHEMAS

    schemas = {s["function"]["name"]: s for s in TOOL_SCHEMAS}
    assert "run_python" in schemas
    fn = schemas["run_python"]["function"]
    assert "code" in fn["parameters"]["required"]


# ─── Happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_python_formats_stdout_and_result(stub_sandbox):
    from app.tools import ToolExecutor

    sb, _ = stub_sandbox
    sb.next_result = SimpleNamespace(
        text="42",
        logs=SimpleNamespace(stdout=["hello\n"], stderr=[]),
        error=None,
    )

    ex = ToolExecutor({}, asyncio.Lock())
    out = await ex.execute("run_python", {"code": "print('hello'); 42"})
    await ex.close()

    assert "hello" in out
    assert "42" in out
    assert sb.run_calls == [("print('hello'); 42", 30)]


# ─── Lazy + reuse ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sandbox_is_lazy_and_reused(stub_sandbox):
    from app.tools import ToolExecutor

    sb, counter = stub_sandbox
    ex = ToolExecutor({}, asyncio.Lock())

    assert counter["created"] == 0

    await ex.execute("get_current_date", {})
    assert counter["created"] == 0  # non-python tools don't spin up the sandbox

    await ex.execute("run_python", {"code": "1"})
    assert counter["created"] == 1

    await ex.execute("run_python", {"code": "2"})
    assert counter["created"] == 1  # reused
    assert len(sb.run_calls) == 2

    await ex.close()


# ─── close() ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_kills_sandbox(stub_sandbox):
    from app.tools import ToolExecutor

    sb, _ = stub_sandbox
    ex = ToolExecutor({}, asyncio.Lock())
    await ex.execute("run_python", {"code": "1"})
    assert sb.killed is False
    await ex.close()
    assert sb.killed is True


@pytest.mark.asyncio
async def test_close_noop_when_sandbox_never_created(stub_sandbox):
    from app.tools import ToolExecutor

    _, counter = stub_sandbox
    ex = ToolExecutor({}, asyncio.Lock())
    await ex.close()
    assert counter["created"] == 0


@pytest.mark.asyncio
async def test_close_is_idempotent(stub_sandbox):
    from app.tools import ToolExecutor

    sb, _ = stub_sandbox
    ex = ToolExecutor({}, asyncio.Lock())
    await ex.execute("run_python", {"code": "1"})
    await ex.close()
    await ex.close()  # must not raise
    assert sb.killed is True


# ─── Edge cases ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_python_empty_code_short_circuits(stub_sandbox):
    from app.tools import ToolExecutor

    _, counter = stub_sandbox
    ex = ToolExecutor({}, asyncio.Lock())
    out = await ex.execute("run_python", {"code": "   "})
    assert "empty code" in out.lower()
    assert counter["created"] == 0


@pytest.mark.asyncio
async def test_run_python_clamps_timeout(stub_sandbox):
    from app.tools import ToolExecutor

    sb, _ = stub_sandbox
    ex = ToolExecutor({}, asyncio.Lock())

    await ex.execute("run_python", {"code": "1", "timeout": 0})
    await ex.execute("run_python", {"code": "2", "timeout": 9999})

    assert sb.run_calls[0][1] == 1
    assert sb.run_calls[1][1] == 120

    await ex.close()


@pytest.mark.asyncio
async def test_run_python_handles_timeout_exception(stub_sandbox):
    from e2b import TimeoutException

    from app.tools import ToolExecutor

    sb, _ = stub_sandbox
    sb.next_exc = TimeoutException("too slow")

    ex = ToolExecutor({}, asyncio.Lock())
    out = await ex.execute("run_python", {"code": "import time; time.sleep(99)", "timeout": 5})
    assert "timeout" in out.lower()
    await ex.close()


@pytest.mark.asyncio
async def test_run_python_handles_sandbox_exception(stub_sandbox):
    from e2b import SandboxException

    from app.tools import ToolExecutor

    sb, _ = stub_sandbox
    sb.next_exc = SandboxException("vm dead")

    ex = ToolExecutor({}, asyncio.Lock())
    out = await ex.execute("run_python", {"code": "1"})
    assert "sandbox" in out.lower()
    assert "vm dead" in out
    await ex.close()


@pytest.mark.asyncio
async def test_run_python_surfaces_execution_error(stub_sandbox):
    from app.tools import ToolExecutor

    sb, _ = stub_sandbox
    sb.next_result = SimpleNamespace(
        text="",
        logs=SimpleNamespace(stdout=[], stderr=[]),
        error=SimpleNamespace(
            name="ZeroDivisionError",
            value="division by zero",
            traceback="Traceback (most recent call last):\n  ...",
        ),
    )

    ex = ToolExecutor({}, asyncio.Lock())
    out = await ex.execute("run_python", {"code": "1/0"})
    assert "ZeroDivisionError" in out
    assert "division by zero" in out
    await ex.close()
