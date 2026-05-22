"""Kimi-style orchestrator loop.

The orchestrator is the only voice to the user. It runs an OpenAI tool-use
loop with a small, dedicated tool surface:

  - spawn_workers(specs)      → blocks until all spawned workers finish;
                                returns a per-worker short summary list.
                                Raw worker output stays in shared memory.
  - read_shared_memory(key)   → "all" for the full dump, otherwise the value.
  - list_artifacts()          → bare filenames under the artifacts dir.

The loop terminates when the model returns an assistant message with no tool
calls; that text is the user-facing final answer. If the iteration cap is hit
or the model emits empty content, the swarm falls back to inline-merging
worker summaries into a usable final answer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Awaitable, Callable

from langsmith import traceable
from pydantic import ValidationError

from app.client import get_openrouter
from app.memory import SharedMemoryStore
from app.models import MODELS
from app.sandbox import SwarmSandbox
from app.skills_loader import skills_orchestrator_section
from app.state import (
    AgentComplete,
    AgentRunning,
    AgentSpawned,
    AgentSpec,
    OrchestratorReasoning,
    SpawnResult,
    SpawnSummary,
    SwarmEvent,
    ToolCallEvent,
    ToolResultEvent,
    WorkerResult,
    WorkerSpec,
)
from app.worker import run_worker

logger = logging.getLogger(__name__)

EventEmitter = Callable[[SwarmEvent], Awaitable[None]]

_ARTIFACTS_DIR = "/home/user/workspace/artifacts"

# Defaults — overridable via env vars / kwargs. See plan §"Iteration Bounds".
DEFAULT_MAX_ITERATIONS = int(os.getenv("SWARM_MAX_ITERATIONS",    "6"))
DEFAULT_MAX_TOTAL_WORKERS = int(os.getenv("SWARM_MAX_TOTAL_WORKERS", "30"))
DEFAULT_MAX_PER_CALL = int(os.getenv("SWARM_MAX_PER_CALL",      "8"))
DEFAULT_CONCURRENCY = int(os.getenv("SWARM_CONCURRENCY",       "10"))


ORCHESTRATOR_SYSTEM = """You are the orchestrator of an agent swarm. You are the ONLY voice to the user — your last assistant message (with no tool calls) IS the user's final answer.

You decompose the user's task into specialist workers, spawn them in parallel waves, read their summaries from shared memory, and decide when the work is done.

How the loop works:
- You call `spawn_workers(specs=[...])` with 1-{max_per_call} worker specs at a time. Workers in one call run truly in parallel (up to {concurrency} at once; more queue into waves). The call BLOCKS until every spawned worker finishes; you then receive a short summary per worker.
- Each worker's FULL output is written to shared memory under `worker:<agent_id>:output`. Use `read_shared_memory(key=...)` to pull it on demand (or `key="all"` for the whole dump).
- Workers also write structured findings to their own shared-memory keys. Read those too if relevant.
- Workers cannot see each other inside one cohort, but they can read shared memory written by PRIOR iterations. So research-then-build is a natural two-iteration pattern.
- Use `list_artifacts()` to confirm builder workers actually produced their deliverable files (under {artifacts_dir}). Reference filenames in your final answer when relevant.

Iteration discipline — this is the single most important rule:

A cohort = workers spawned in ONE `spawn_workers` call. They run in PARALLEL and CANNOT see each other's shared-memory writes. They can only read what PRIOR iterations wrote.

⛔ NEVER put a worker that needs data from another worker in the SAME cohort.
⛔ Putting a researcher and a builder in the same cohort is the #1 failure mode. The builder will read empty memory and produce a useless empty template.

Typical patterns:
    Pattern A — single all-rounder: 1 worker that owns the whole pipeline (use for simple/linear tasks).
    Pattern B — research → build:   Iter 1 spawns N research workers in parallel; Iter 2 spawns 1-2 builder workers that read iter-1 shared memory and produce artifacts.
    Pattern C — research → build → reconcile: Iter 3 spawns a reconciler if findings disagreed.

Worked example — "Compare Orange vs Free internet pricing → Excel dashboard" (DO THIS):
    Iter 1: spawn_workers([
        {{name: "OrangeResearcher", role: "ISP research", task: "Scrape Orange consumer internet offers; write each finding to shared memory under keys orange:offers, orange:fibre_prices, orange:fees as you go."}},
        {{name: "FreeResearcher",   role: "ISP research", task: "Scrape Free consumer internet offers; write to keys free:offers, free:freebox_prices, free:fees as you go."}},
    ])
    → wait for both; read shared memory; verify the researchers actually wrote data
    Iter 2: spawn_workers([
        {{name: "ExcelBuilder", role: "xlsx", task: "Read orange:* and free:* keys from shared memory and build a comparison .xlsx using the xlsx skill. Save to /home/user/workspace/artifacts/."}},
    ])
    → call list_artifacts() to confirm the file was written
    Iter 3: emit final answer referencing the artifact filename.

ANTI-example — what NOT to do (this produces empty templates):
    Iter 1: spawn_workers([
        {{name: "Researcher", task: "scrape pricing"}},
        {{name: "Builder",    task: "build the xlsx"}},   ← runs in parallel, sees empty memory, fails silently
    ])

After spawn_workers returns, look at every worker's `summary`. If you see "⚠ worker hit max_iterations without persisting any findings" or status != "ok" on a research worker, that worker's data is LOST. Either re-run the research (with a tighter task) or proceed knowing that builder workers will have less to work with.

Worker spec shape: name (PascalCase, e.g. MarketAnalyst), role (one line), task (specific subtask). Mention a skill by name in the `task` field when one clearly applies (the workers see a skills catalogue).

Caps: at most {max_iterations} iterations and {max_total_workers} workers total across the whole run. Stay efficient.

Final answer:
- When the task is complete, emit your final user-facing answer as plain assistant text with NO tool calls.
- The final message should integrate worker findings, resolve disagreements (you decide; you may spawn a reconciler if needed), and reference artifact filenames where appropriate.
- Be thorough but not verbose. Use headings/sections when the answer is long."""


# ─── Tool schemas (OpenAI function-calling format) ──────────────────────────


def _orchestrator_tool_schemas(max_per_call: int) -> list[dict[str, Any]]:
    worker_spec_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "PascalCase agent name, e.g. MarketAnalyst"},
            "role": {"type": "string", "description": "One-line specialist description"},
            "task": {"type": "string", "description": "Specific subtask for this worker"},
        },
        "required": ["name", "role", "task"],
    }
    return [
        {
            "type": "function",
            "function": {
                "name": "spawn_workers",
                "description": (
                    "Spawn a cohort of workers in parallel and BLOCK until every "
                    f"worker finishes. At most {max_per_call} workers per call. "
                    "Returns a per-worker short summary. Each worker's full "
                    "output is preserved in shared memory at worker:<id>:output."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "specs": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": max_per_call,
                            "items": worker_spec_schema,
                        },
                    },
                    "required": ["specs"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_shared_memory",
                "description": (
                    "Read findings written by workers. Use key='all' for the "
                    "full dump, or a specific key (e.g. worker:w2:output) for "
                    "one entry."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Specific key or 'all'"},
                    },
                    "required": ["key"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_artifacts",
                "description": (
                    "List bare filenames currently present in "
                    f"{_ARTIFACTS_DIR}. Use to confirm a builder worker "
                    "produced its deliverable, and to reference filenames in "
                    "your final answer."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


# ─── Worker-cohort fan-out ──────────────────────────────────────────────────


async def _run_cohort(
    *,
    specs: list[WorkerSpec],
    # mutable single-element ref for unique ids across iterations
    id_counter: list[int],
    task: str,
    shared_memory: dict[str, str],
    lock: asyncio.Lock,
    on_event: EventEmitter | None,
    concurrency: int,
    store: SharedMemoryStore | None,
    session_id: str | None,
    sandbox: SwarmSandbox | None,
) -> list[WorkerResult]:
    """Spawn workers in parallel, gated by a per-cohort semaphore."""
    sem = asyncio.Semaphore(max(1, concurrency))
    agents: list[AgentSpec] = []
    for s in specs:
        id_counter[0] += 1
        agents.append(AgentSpec(
            id=f"w{id_counter[0]}",
            name=s.name, role=s.role, task=s.task, skills=s.skills,
        ))

    for a in agents:
        if on_event:
            await on_event(AgentSpawned(spec=a, is_handoff=False))

    async def _one(a: AgentSpec) -> WorkerResult:
        async with sem:
            if on_event:
                await on_event(AgentRunning(agent_id=a.id))
            try:
                result = await run_worker(
                    spec=a,
                    task=task,
                    shared_memory=shared_memory,
                    lock=lock,
                    on_event=on_event,
                    store=store,
                    session_id=session_id,
                    sandbox=sandbox,
                )
            except Exception as e:
                logger.warning("worker[%s] crashed: %s", a.id, e)
                result = WorkerResult(
                    spec=a, text=f"({type(e).__name__}: {e})", status="error",
                )
            if on_event:
                await on_event(AgentComplete(
                    agent_id=a.id, text=result.text, status=result.status,
                ))
            return result

    return await asyncio.gather(*(_one(a) for a in agents))


# ─── Public entry point ─────────────────────────────────────────────────────


@traceable(name="orchestrator_loop", run_type="chain")
async def run_orchestrator(
    *,
    task: str,
    shared_memory: dict[str, str],
    lock: asyncio.Lock,
    on_event: EventEmitter | None = None,
    sandbox: SwarmSandbox | None = None,
    store: SharedMemoryStore | None = None,
    session_id: str | None = None,
    model: str | None = None,
    max_tokens: int = 40000,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_total_workers: int = DEFAULT_MAX_TOTAL_WORKERS,
    max_per_call: int = DEFAULT_MAX_PER_CALL,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> "OrchestratorRun":
    """Run the orchestrator's tool-use loop end-to-end.

    Returns an OrchestratorRun bundle with the final answer text, the list of
    workers actually spawned (across all iterations), and the iteration count.
    """
    client = get_openrouter()
    model = model or MODELS["orchestrator"]
    today = datetime.now().strftime("%Y-%m-%d")

    system = ORCHESTRATOR_SYSTEM.format(
        max_per_call=max_per_call,
        concurrency=concurrency,
        max_iterations=max_iterations,
        max_total_workers=max_total_workers,
        artifacts_dir=_ARTIFACTS_DIR,
    ) + skills_orchestrator_section()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": f"Today's date: {today}\n\nUser task: {task}"},
    ]
    tools = _orchestrator_tool_schemas(max_per_call)

    id_counter = [0]   # shared across iterations so worker ids are unique
    all_results: list[WorkerResult] = []
    iteration = 0
    final_text: str | None = None
    finish_reason: str | None = None

    for iteration in range(1, max_iterations + 1):
        if on_event:
            from app.state import PhaseStart
            await on_event(PhaseStart(phase=f"orchestrator-iteration-{iteration}"))

        resp = await client.chat.completions.create(
            model=model,
            messages=messages,    # type: ignore[arg-type]
            tools=tools,          # type: ignore[arg-type]
            max_tokens=max_tokens,
        )
        msg = resp.choices[0].message
        finish_reason = resp.choices[0].finish_reason
        content = (msg.content or "").strip()

        # Terminal: no tool calls → final answer text
        if finish_reason != "tool_calls" or not msg.tool_calls:
            if content:
                final_text = content
            break

        # Surface the orchestrator's reasoning that accompanies its tool calls,
        # so its decision-making is visible in the trace (not just the spawns).
        if content and on_event:
            await on_event(OrchestratorReasoning(reasoning=content))

        # Otherwise, append the assistant message + execute each tool call
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args: dict[str, Any] = json.loads(
                    tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            # spawn_workers has its own AgentSpawned/Running/Complete events; the
            # read-only tools were previously silent — emit them so iterations
            # that only poll shared memory / artifacts are visible in the trace.
            if name != "spawn_workers" and on_event:
                await on_event(ToolCallEvent(agent_id="orchestrator", name=name, input=args))

            if name == "spawn_workers":
                spawn_result, cohort_results = await _handle_spawn_workers(
                    args=args,
                    id_counter=id_counter,
                    spawned_so_far=len(all_results),
                    max_total_workers=max_total_workers,
                    max_per_call=max_per_call,
                    task=task,
                    shared_memory=shared_memory,
                    lock=lock,
                    on_event=on_event,
                    concurrency=concurrency,
                    store=store,
                    session_id=session_id,
                    sandbox=sandbox,
                )
                all_results.extend(cohort_results)
                tool_payload = spawn_result.model_dump_json()
            elif name == "read_shared_memory":
                tool_payload = _read_memory(shared_memory, args.get("key", ""))
            elif name == "list_artifacts":
                tool_payload = await _list_artifacts(sandbox)
            else:
                tool_payload = f"Unknown tool: {name}"

            if name != "spawn_workers" and on_event:
                await on_event(ToolResultEvent(
                    agent_id="orchestrator", name=name, result=tool_payload))

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_payload,
            })

    if final_text is None:
        final_text = _fallback_final(
            task=task,
            results=all_results,
            shared_memory=shared_memory,
            reason=(
                "hit iteration cap" if iteration >= max_iterations
                else f"orchestrator emitted no final content (finish_reason={finish_reason!r})"
            ),
        )

    return OrchestratorRun(
        final_text=final_text,
        results=all_results,
        iterations=iteration,
    )


class OrchestratorRun:
    __slots__ = ("final_text", "results", "iterations")

    def __init__(self, *, final_text: str, results: list[WorkerResult], iterations: int):
        self.final_text = final_text
        self.results = results
        self.iterations = iterations


# ─── Tool handlers ──────────────────────────────────────────────────────────


async def _handle_spawn_workers(
    *,
    args: dict[str, Any],
    id_counter: list[int],
    spawned_so_far: int,
    max_total_workers: int,
    max_per_call: int,
    task: str,
    shared_memory: dict[str, str],
    lock: asyncio.Lock,
    on_event: EventEmitter | None,
    concurrency: int,
    store: SharedMemoryStore | None,
    session_id: str | None,
    sandbox: SwarmSandbox | None,
) -> tuple[SpawnResult, list[WorkerResult]]:
    raw_specs = args.get("specs") or []
    if not isinstance(raw_specs, list) or not raw_specs:
        return (
            SpawnResult(workers=[]),
            [],
        )

    parsed: list[WorkerSpec] = []
    errors: list[str] = []
    for i, raw in enumerate(raw_specs):
        try:
            parsed.append(WorkerSpec.model_validate(raw))
        except ValidationError as e:
            errors.append(f"specs[{i}]: {e}")

    if not parsed:
        return (
            SpawnResult(workers=[
                SpawnSummary(
                    agent_id="-", name="(rejected)", role="(invalid)",
                    status="error",
                    summary="spawn_workers rejected: " + "; ".join(errors),
                )
            ]),
            [],
        )

    # Enforce per-call cap (defensive — schema also has maxItems)
    if len(parsed) > max_per_call:
        parsed = parsed[:max_per_call]

    # Enforce total-workers cap across the run
    remaining = max(0, max_total_workers - spawned_so_far)
    if remaining == 0:
        return (
            SpawnResult(workers=[
                SpawnSummary(
                    agent_id="-", name="(rejected)", role="(capped)",
                    status="error",
                    summary=f"spawn_workers rejected: total-worker cap ({max_total_workers}) reached.",
                )
            ]),
            [],
        )
    if len(parsed) > remaining:
        parsed = parsed[:remaining]

    cohort_results = await _run_cohort(
        specs=parsed,
        id_counter=id_counter,
        task=task,
        shared_memory=shared_memory,
        lock=lock,
        on_event=on_event,
        concurrency=concurrency,
        store=store,
        session_id=session_id,
        sandbox=sandbox,
    )

    summaries = [
        SpawnSummary(
            agent_id=r.spec.id,
            name=r.spec.name,
            role=r.spec.role,
            status=r.status,
            summary=_annotate_summary(r),
        )
        for r in cohort_results
    ]
    return SpawnResult(workers=summaries), cohort_results


def _read_memory(shared_memory: dict[str, str], key: str) -> str:
    if key == "all":
        if not shared_memory:
            return "(shared memory is empty)"
        return "\n".join(f"[{k}]: {v}" for k, v in shared_memory.items())
    if key in shared_memory:
        return shared_memory[key]
    return f'Nothing found for key "{key}".'


async def _list_artifacts(sandbox: SwarmSandbox | None) -> str:
    if sandbox is None:
        return "(no sandbox — no artifacts available)"
    try:
        entries = await sandbox.list_files(_ARTIFACTS_DIR)
    except Exception as e:
        return f"(list_artifacts failed: {type(e).__name__}: {e})"
    names = [e["name"] for e in entries if not e.get("is_dir")]
    if not names:
        return "(no artifacts yet)"
    return "\n".join(names)


# ─── Helpers ────────────────────────────────────────────────────────────────


# 500 tokens ≈ ~2000 chars at roughly 4 chars/token. We cap by chars because
# we don't carry a tokenizer; the orchestrator can always read the full output
# from shared memory if it needs more.
_SUMMARY_CHAR_CAP = 2000


def _truncate_summary(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _SUMMARY_CHAR_CAP:
        return text
    return text[: _SUMMARY_CHAR_CAP - 20].rstrip() + "\n…[truncated]"


def _annotate_summary(r: WorkerResult) -> str:
    """Truncate the worker's summary and prepend warning banners that the
    orchestrator needs to see (e.g. a soft-failed worker that persisted
    nothing to shared memory — its raw data is lost).
    """
    body = _truncate_summary(r.text)
    banners: list[str] = []

    if r.status != "ok":
        wrote_memory = any(
            tc.name == "write_to_shared_memory" for tc in r.tool_calls
        )
        wrote_files = any(
            tc.name in ("write_file", "edit_file") for tc in r.tool_calls
        )
        if not wrote_memory and not wrote_files:
            banners.append(
                f"⚠ worker {r.spec.id} ({r.spec.name}) finished with status={r.status!r} "
                "and persisted NOTHING to shared memory or the workspace — its raw findings are LOST. "
                "If this worker was researching for a downstream builder, re-run it with a tighter task."
            )
        elif not wrote_memory:
            banners.append(
                f"⚠ worker {r.spec.id} ({r.spec.name}) finished with status={r.status!r} "
                "without writing to shared memory. Its files in the workspace may still be usable; "
                "shared-memory consumers will see nothing."
            )

    if not banners:
        return body
    return "\n".join(banners) + ("\n\n" + body if body else "")


def _fallback_final(
    *,
    task: str,
    results: list[WorkerResult],
    shared_memory: dict[str, str],
    reason: str,
) -> str:
    """Inline-merge worker summaries into a usable final answer when the
    orchestrator itself fails to produce one."""
    lines: list[str] = [
        f"# Partial result for: {task}",
        "",
        f"_Orchestrator did not produce a final answer ({reason}). "
        "Showing worker summaries and shared memory below._",
        "",
    ]
    ok = [r for r in results if r.status == "ok" and r.text.strip()]
    if ok:
        lines.append("## Worker summaries")
        for r in ok:
            lines.append(f"### {r.spec.name} — {r.spec.role}")
            lines.append(r.text)
            lines.append("")
    if shared_memory:
        lines.append("## Shared memory")
        for k, v in shared_memory.items():
            preview = v if len(v) <= 500 else v[:500] + "…"
            lines.append(f"- **{k}**: {preview}")
        lines.append("")
    return "\n".join(lines)
