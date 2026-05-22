"""Tests for the Kimi-style orchestrator tool-use loop.

We stub out the OpenAI client via respx so the orchestrator drives a fully
deterministic sequence of tool calls. Worker spawning is exercised by patching
`run_worker` to return canned WorkerResults — that way we don't need a real
LLM for the workers either.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import respx

from app.orchestrator import run_orchestrator
from app.state import AgentSpec, ToolCallRecord, WorkerResult

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


def _msg(*, content: str | None = None, tool_calls: list[dict] | None = None,
         finish: str = "stop") -> dict:
    m: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [{"index": 0, "message": m, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _tc(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _spawn_specs(*specs: tuple[str, str, str]) -> dict:
    return {"specs": [{"name": n, "role": r, "task": t} for n, r, t in specs]}


def _patch_worker(monkeypatch, *, summary_by_name: dict[str, str] | None = None,
                  capture: list[AgentSpec] | None = None):
    """Replace app.orchestrator.run_worker with a stub that returns canned
    WorkerResults. The spec it was called with is appended to ``capture``
    when provided.
    """
    async def fake_run_worker(*, spec: AgentSpec, **_kwargs) -> WorkerResult:
        if capture is not None:
            capture.append(spec)
        text = (summary_by_name or {}).get(spec.name, f"{spec.name} done.")
        # Persist to shared memory the way real workers do.
        sm = _kwargs["shared_memory"]
        lock = _kwargs["lock"]
        async with lock:
            sm[f"worker:{spec.id}:output"] = text
        return WorkerResult(spec=spec, text=text, status="ok")

    monkeypatch.setattr("app.orchestrator.run_worker", fake_run_worker)


# ─── Single iteration ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_single_iteration_terminates_with_final_text(monkeypatch):
    """Orchestrator decides the task is done after one cohort, then emits a
    final assistant message with no tool calls."""
    _patch_worker(monkeypatch)

    route = respx.post(OPENROUTER)
    route.side_effect = [
        # Iter 1: spawn one worker
        httpx.Response(200, json=_msg(
            content=None,
            finish="tool_calls",
            tool_calls=[_tc("c1", "spawn_workers",
                            _spawn_specs(("Solo", "all-rounder", "do the thing")))],
        )),
        # Iter 2: final answer, no tool calls
        httpx.Response(200, json=_msg(content="Final answer from orchestrator.", finish="stop")),
    ]

    run = await run_orchestrator(
        task="t",
        shared_memory={},
        lock=asyncio.Lock(),
    )
    assert run.final_text == "Final answer from orchestrator."
    assert run.iterations == 2
    assert len(run.results) == 1
    assert run.results[0].spec.name == "Solo"
    assert run.results[0].spec.id == "w1"


# ─── Multi-iteration ────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_multi_iteration_research_then_build(monkeypatch):
    """Orchestrator spawns a research wave, then a build wave, then terminates."""
    captured: list[AgentSpec] = []
    _patch_worker(monkeypatch, capture=captured, summary_by_name={
        "OrangeResearcher": "Orange offers summary",
        "FreeResearcher":   "Free offers summary",
        "ExcelBuilder":     "Wrote /home/user/workspace/artifacts/compare.xlsx",
    })

    route = respx.post(OPENROUTER)
    route.side_effect = [
        # Iter 1: research cohort (2 parallel)
        httpx.Response(200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c1", "spawn_workers", _spawn_specs(
                ("OrangeResearcher", "ISP research", "scrape Orange offers"),
                ("FreeResearcher",   "ISP research", "scrape Free offers"),
            ))],
        )),
        # Iter 2: builder cohort (1)
        httpx.Response(200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c2", "spawn_workers", _spawn_specs(
                ("ExcelBuilder", "xlsx", "build comparison dashboard"),
            ))],
        )),
        # Iter 3: final answer
        httpx.Response(200, json=_msg(content="Comparison complete: see compare.xlsx.", finish="stop")),
    ]

    run = await run_orchestrator(task="t", shared_memory={}, lock=asyncio.Lock())

    assert run.iterations == 3
    assert run.final_text.startswith("Comparison complete")
    # 2 from iter1 + 1 from iter2 = 3 workers spawned
    assert [a.name for a in captured] == ["OrangeResearcher", "FreeResearcher", "ExcelBuilder"]
    # IDs auto-assigned w1..w3 across iterations
    assert [a.id for a in captured] == ["w1", "w2", "w3"]
    assert len(run.results) == 3


# ─── Iteration cap fallback ─────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_iteration_cap_triggers_fallback(monkeypatch):
    """Orchestrator that keeps calling spawn_workers indefinitely is killed at
    the cap; a fallback message is produced from worker summaries."""
    _patch_worker(monkeypatch, summary_by_name={"Looper": "Looper summary"})

    # Always return a spawn call — orchestrator never emits a final.
    respx.post(OPENROUTER).mock(return_value=httpx.Response(
        200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c1", "spawn_workers",
                            _spawn_specs(("Looper", "loop", "loop forever")))],
        ),
    ))

    run = await run_orchestrator(
        task="t",
        shared_memory={},
        lock=asyncio.Lock(),
        max_iterations=2,
    )
    assert run.iterations == 2
    assert "Partial result" in run.final_text
    assert "Looper" in run.final_text
    # Both iterations spawned one worker each
    assert len(run.results) == 2


# ─── Summary truncation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_spawn_result_summary_truncates_full_worker_text(monkeypatch):
    """The orchestrator sees a *truncated* summary in the tool result; full
    output stays in shared memory."""
    long_output = "X" * 5000
    _patch_worker(monkeypatch, summary_by_name={"BigTalker": long_output})

    # Capture the second LLM call's `messages` payload so we can inspect the
    # tool result the orchestrator just received.
    second_call_body: dict[str, Any] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "tool_choice" not in body and len(body["messages"]) >= 4:
            # Second call carries the tool result message we want.
            second_call_body.update(body)
            return httpx.Response(200, json=_msg(content="done", finish="stop"))
        # First call: spawn one worker
        return httpx.Response(200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c1", "spawn_workers",
                            _spawn_specs(("BigTalker", "verbose", "talk a lot")))],
        ))

    respx.post(OPENROUTER).mock(side_effect=_record)

    shared: dict[str, str] = {}
    run = await run_orchestrator(task="t", shared_memory=shared, lock=asyncio.Lock())

    assert run.final_text == "done"

    # The full output is in shared memory…
    assert shared["worker:w1:output"] == long_output

    # …but the orchestrator's tool result was capped.
    tool_msg = next(m for m in second_call_body["messages"] if m["role"] == "tool")
    payload = json.loads(tool_msg["content"])
    summary = payload["workers"][0]["summary"]
    assert summary.endswith("[truncated]")
    assert len(summary) < len(long_output)


# ─── read_shared_memory + list_artifacts ────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_read_shared_memory_tool_returns_dump(monkeypatch):
    _patch_worker(monkeypatch)
    route = respx.post(OPENROUTER)
    route.side_effect = [
        # Iter 1: spawn one worker
        httpx.Response(200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c1", "spawn_workers",
                            _spawn_specs(("W", "r", "t")))],
        )),
        # Iter 2: call read_shared_memory(key="all")
        httpx.Response(200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c2", "read_shared_memory", {"key": "all"})],
        )),
        # Iter 3: final
        httpx.Response(200, json=_msg(content="ok", finish="stop")),
    ]
    run = await run_orchestrator(task="t", shared_memory={}, lock=asyncio.Lock())
    assert run.iterations == 3
    assert run.final_text == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_maxed_out_worker_with_no_persist_gets_warning_banner(monkeypatch):
    """A worker that hits max_iterations and wrote nothing to shared memory
    must surface a ⚠ banner in its SpawnSummary so the orchestrator can react."""
    async def fake_run_worker(*, spec, **_kwargs):
        # Simulate a researcher that scraped a bunch but never persisted.
        sm = _kwargs["shared_memory"]
        lock = _kwargs["lock"]
        async with lock:
            sm[f"worker:{spec.id}:output"] = "(max iterations reached: 15)"
        return WorkerResult(
            spec=spec,
            text="(max iterations reached: 15)",
            status="max_iterations",
            tool_calls=[
                ToolCallRecord(name="web_search", input={"query": "x"}, result="..."),
                ToolCallRecord(name="scrape_url", input={"url": "u"},  result="..."),
            ],
        )
    monkeypatch.setattr("app.orchestrator.run_worker", fake_run_worker)

    captured: dict[str, Any] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if len(body["messages"]) >= 4:
            captured.update(body)
            return httpx.Response(200, json=_msg(content="done", finish="stop"))
        return httpx.Response(200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c1", "spawn_workers",
                            _spawn_specs(("Loser", "research", "scrape pricing")))],
        ))
    respx.post(OPENROUTER).mock(side_effect=_record)

    await run_orchestrator(task="t", shared_memory={}, lock=asyncio.Lock())

    tool_msg = next(m for m in captured["messages"] if m["role"] == "tool")
    payload = json.loads(tool_msg["content"])
    summary = payload["workers"][0]["summary"]
    assert "⚠" in summary
    assert "persisted NOTHING" in summary
    assert "max_iterations" in summary


@pytest.mark.asyncio
@respx.mock
async def test_maxed_out_worker_with_writes_does_not_warn(monkeypatch):
    """A failed worker that DID write to shared memory should not get the banner."""
    async def fake_run_worker(*, spec, **_kwargs):
        sm = _kwargs["shared_memory"]
        lock = _kwargs["lock"]
        async with lock:
            sm["orange:offers"] = "partial findings"
            sm[f"worker:{spec.id}:output"] = "ran out of iterations"
        return WorkerResult(
            spec=spec, text="ran out of iterations", status="max_iterations",
            tool_calls=[
                ToolCallRecord(name="write_to_shared_memory",
                               input={"key": "orange:offers", "value": "..."},
                               result="ok"),
            ],
        )
    monkeypatch.setattr("app.orchestrator.run_worker", fake_run_worker)

    captured: dict[str, Any] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if len(body["messages"]) >= 4:
            captured.update(body)
            return httpx.Response(200, json=_msg(content="done", finish="stop"))
        return httpx.Response(200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c1", "spawn_workers",
                            _spawn_specs(("Persister", "research", "scrape")))],
        ))
    respx.post(OPENROUTER).mock(side_effect=_record)

    await run_orchestrator(task="t", shared_memory={}, lock=asyncio.Lock())

    tool_msg = next(m for m in captured["messages"] if m["role"] == "tool")
    payload = json.loads(tool_msg["content"])
    summary = payload["workers"][0]["summary"]
    assert "⚠" not in summary
    assert "persisted NOTHING" not in summary


@pytest.mark.asyncio
@respx.mock
async def test_orchestrator_emits_events_for_silent_tools(monkeypatch):
    """read_shared_memory / list_artifacts were silent — they must now emit
    tool_call + tool_result events tagged 'orchestrator', and reasoning text
    accompanying tool calls must surface as orchestrator_reasoning."""
    _patch_worker(monkeypatch)
    route = respx.post(OPENROUTER)
    route.side_effect = [
        httpx.Response(200, json=_msg(
            content="Spawning a researcher first.",
            finish="tool_calls",
            tool_calls=[_tc("c1", "spawn_workers", _spawn_specs(("W", "r", "t")))],
        )),
        httpx.Response(200, json=_msg(
            content="Checking what the worker persisted.",
            finish="tool_calls",
            tool_calls=[_tc("c2", "read_shared_memory", {"key": "all"})],
        )),
        httpx.Response(200, json=_msg(content="ok", finish="stop")),
    ]

    events: list[Any] = []

    async def collect(e):
        events.append(e)

    run = await run_orchestrator(
        task="t", shared_memory={}, lock=asyncio.Lock(), on_event=collect,
    )
    assert run.final_text == "ok"

    orch_calls = [e for e in events if e.type == "tool_call" and e.agent_id == "orchestrator"]
    assert [e.name for e in orch_calls] == ["read_shared_memory"]

    orch_results = [e for e in events if e.type == "tool_result" and e.agent_id == "orchestrator"]
    assert [e.name for e in orch_results] == ["read_shared_memory"]

    reasoning = {e.reasoning for e in events if e.type == "orchestrator_reasoning"}
    assert "Spawning a researcher first." in reasoning
    assert "Checking what the worker persisted." in reasoning

    # spawn_workers keeps its own events — no duplicate tool_call for it.
    assert not any(e.type == "tool_call" and e.name == "spawn_workers" for e in events)


@pytest.mark.asyncio
@respx.mock
async def test_list_artifacts_without_sandbox_returns_safe_message(monkeypatch):
    _patch_worker(monkeypatch)
    route = respx.post(OPENROUTER)
    route.side_effect = [
        httpx.Response(200, json=_msg(
            content=None, finish="tool_calls",
            tool_calls=[_tc("c1", "list_artifacts", {})],
        )),
        httpx.Response(200, json=_msg(content="done", finish="stop")),
    ]
    run = await run_orchestrator(task="t", shared_memory={}, lock=asyncio.Lock())
    assert run.final_text == "done"
