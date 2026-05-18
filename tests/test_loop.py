"""Tests for the tool-use loop.

Mocks OpenRouter via respx (HTTP-level) so we exercise the real OpenAI SDK
parsing and our loop's branching logic.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from app.loop import tool_use_loop
from app.tools import TOOL_SCHEMAS

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


def _completion(*, content: str | None = None, tool_calls: list[dict] | None = None,
                finish: str = "stop") -> dict:
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _tc(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@pytest.mark.asyncio
@respx.mock
async def test_loop_terminates_with_no_tool_use():
    respx.post(OPENROUTER).mock(return_value=httpx.Response(
        200, json=_completion(content="Hello, no tools.", finish="stop")
    ))

    out = await tool_use_loop(
        agent_id="a1", model="x/y", system="sys", user="hi",
        tools=TOOL_SCHEMAS, shared_memory={}, lock=asyncio.Lock(),
    )
    assert out.text == "Hello, no tools."
    assert out.status == "ok"
    assert out.tool_calls == []


@pytest.mark.asyncio
@respx.mock
async def test_loop_executes_tool_then_terminates():
    route = respx.post(OPENROUTER)
    route.side_effect = [
        httpx.Response(200, json=_completion(
            content=None,
            tool_calls=[_tc("c1", "write_to_shared_memory", {"key": "k", "value": "v"})],
            finish="tool_calls",
        )),
        httpx.Response(200, json=_completion(content="Done.", finish="stop")),
    ]

    mem: dict[str, str] = {}
    out = await tool_use_loop(
        agent_id="a1", model="x/y", system="sys", user="hi",
        tools=TOOL_SCHEMAS, shared_memory=mem, lock=asyncio.Lock(),
    )
    assert out.text == "Done."
    assert out.status == "ok"
    assert mem == {"k": "v"}
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "write_to_shared_memory"
    assert out.tool_calls[0].input == {"key": "k", "value": "v"}


@pytest.mark.asyncio
@respx.mock
async def test_loop_respects_max_iterations():
    respx.post(OPENROUTER).mock(return_value=httpx.Response(
        200, json=_completion(
            content=None,
            tool_calls=[_tc("c1", "get_current_date", {})],
            finish="tool_calls",
        )
    ))

    out = await tool_use_loop(
        agent_id="a1", model="x/y", system="sys", user="hi",
        tools=TOOL_SCHEMAS, shared_memory={}, lock=asyncio.Lock(),
        max_iterations=3,
    )
    assert out.status == "max_iterations"
    assert "max iterations" in out.text
    assert len(out.tool_calls) == 3  # one tool call per iteration


@pytest.mark.asyncio
@respx.mock
async def test_loop_detects_length_truncation():
    # Reasoning model exhausts max_tokens during reasoning → content=None, finish=length.
    # This was the silent failure mode that hit a4 in the live trace.
    respx.post(OPENROUTER).mock(return_value=httpx.Response(
        200, json=_completion(content=None, finish="length")
    ))

    out = await tool_use_loop(
        agent_id="a4", model="x/y", system="sys", user="hi",
        tools=TOOL_SCHEMAS, shared_memory={}, lock=asyncio.Lock(),
    )
    assert out.status == "length_truncated"
    assert "truncated" in out.text.lower()


@pytest.mark.asyncio
@respx.mock
async def test_loop_forwards_store_and_session_id_to_executor(monkeypatch):
    """tool_use_loop must thread store/session_id through to ToolExecutor so memory writes persist."""
    from app.memory import InMemoryStore

    captured: dict[str, object] = {}

    from app.tools import ToolExecutor as RealExecutor

    class CapturingExecutor(RealExecutor):
        def __init__(self, *args, **kwargs):
            captured["store"] = kwargs.get("store")
            captured["session_id"] = kwargs.get("session_id")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.loop.ToolExecutor", CapturingExecutor)

    respx.post(OPENROUTER).mock(return_value=httpx.Response(
        200, json=_completion(content="ok", finish="stop")
    ))

    store = InMemoryStore()
    await tool_use_loop(
        agent_id="a1", model="x/y", system="sys", user="hi",
        tools=TOOL_SCHEMAS, shared_memory={}, lock=asyncio.Lock(),
        store=store, session_id="session-X",
    )
    assert captured["store"] is store
    assert captured["session_id"] == "session-X"


@pytest.mark.asyncio
@respx.mock
async def test_loop_closes_executor(monkeypatch):
    """tool_use_loop must call executor.close() so sandbox resources are released."""
    from app.tools import ToolExecutor as RealExecutor

    closed = {"count": 0}

    class TrackingExecutor(RealExecutor):
        async def close(self) -> None:
            closed["count"] += 1
            await super().close()

    monkeypatch.setattr("app.loop.ToolExecutor", TrackingExecutor)

    respx.post(OPENROUTER).mock(return_value=httpx.Response(
        200, json=_completion(content="Done.", finish="stop")
    ))

    await tool_use_loop(
        agent_id="a1", model="x/y", system="sys", user="hi",
        tools=TOOL_SCHEMAS, shared_memory={}, lock=asyncio.Lock(),
    )
    assert closed["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_loop_detects_empty_content_with_stop():
    # Model says "stop" but produced no content — surface as `empty`, not silently `ok`.
    respx.post(OPENROUTER).mock(return_value=httpx.Response(
        200, json=_completion(content=None, finish="stop")
    ))

    out = await tool_use_loop(
        agent_id="a1", model="x/y", system="sys", user="hi",
        tools=TOOL_SCHEMAS, shared_memory={}, lock=asyncio.Lock(),
    )
    assert out.status == "empty"
    assert "no content" in out.text.lower()
