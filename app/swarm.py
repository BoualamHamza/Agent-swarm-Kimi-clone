"""The four-phase conductor — `run_swarm(task)` is an async generator that
yields SwarmEvents in real time as the swarm progresses.

Concurrency model:
  * Phase 2 workers run concurrently, gated by an asyncio.Semaphore.
  * Workers emit events via an asyncio.Queue (the `on_event` callback puts to it).
  * The conductor awaits the queue and yields events to the caller.
  * A `watcher` task awaits all worker tasks and pushes a None sentinel when done.

Phase 3 (handoffs) runs sequentially — handoff agents typically depend on prior
work and there are usually only one or two of them.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from langsmith import traceable

from app.aggregator import aggregate
from app.orchestrator import orchestrate
from app.state import (
    AgentComplete,
    AgentHandedOff,
    AgentRunning,
    AgentSpawned,
    AgentSpec,
    ErrorEvent,
    FinalResult,
    OrchestratorReasoning,
    PhaseStart,
    SwarmEvent,
    WorkerResult,
)
from app.worker import run_handoff_worker, run_worker

logger = logging.getLogger(__name__)

CONCURRENCY = 4


@traceable(name="run_swarm", run_type="chain")
async def run_swarm(task: str) -> AsyncIterator[SwarmEvent]:  # type: ignore[misc]
    """Run a full swarm and yield events as they happen.

    NOTE: @traceable wraps async generators correctly in langsmith>=0.3.
    """
    try:
        # ─── Phase 1 — Orchestrate ───────────────────────────────────────────
        yield PhaseStart(phase="orchestrating")
        orch = await orchestrate(task)
        yield OrchestratorReasoning(reasoning=orch.reasoning)
        for spec in orch.agents:
            yield AgentSpawned(spec=spec, is_handoff=False)

        # ─── Phase 2 — Parallel workers ──────────────────────────────────────
        yield PhaseStart(phase="executing")

        sem = asyncio.Semaphore(CONCURRENCY)
        shared_memory: dict[str, str] = {}
        lock = asyncio.Lock()
        queue: asyncio.Queue[SwarmEvent | None] = asyncio.Queue()

        async def runner(spec: AgentSpec) -> WorkerResult:
            async with sem:
                await queue.put(AgentRunning(agent_id=spec.id))
                try:
                    result = await run_worker(
                        spec=spec,
                        task=task,
                        roster=orch.agents,
                        shared_memory=shared_memory,
                        lock=lock,
                        on_event=queue.put,
                    )
                except Exception as e:
                    # Contain per-worker failures (e.g. RateLimitError after retries
                    # exhausted) — one bad worker should not kill the whole swarm.
                    logger.warning("worker[%s] crashed: %s", spec.id, e)
                    result = WorkerResult(
                        spec=spec,
                        text=f"({type(e).__name__}: {e})",
                        status="error",
                    )
                if result.handoff:
                    await queue.put(AgentHandedOff(
                        agent_id=spec.id, text=result.text, handoff=result.handoff,
                    ))
                else:
                    await queue.put(AgentComplete(
                        agent_id=spec.id, text=result.text, status=result.status,
                    ))
                return result

        worker_tasks = [asyncio.create_task(runner(s)) for s in orch.agents]

        async def watcher() -> None:
            try:
                await asyncio.gather(*worker_tasks)
            finally:
                await queue.put(None)

        watcher_task = asyncio.create_task(watcher())

        # Drain events until watcher signals done
        while True:
            evt = await queue.get()
            if evt is None:
                break
            yield evt

        await watcher_task  # surface any watcher exceptions
        worker_results: list[WorkerResult] = [t.result() for t in worker_tasks]

        # ─── Phase 3 — Handoffs (sequential) ─────────────────────────────────
        handoff_results: list[WorkerResult] = []
        pending = [r for r in worker_results if r.handoff]

        if pending:
            yield PhaseStart(phase="handoffs")
            for i, originator_result in enumerate(pending, start=1):
                handoff = originator_result.handoff
                assert handoff is not None  # type narrowing

                hspec = AgentSpec(
                    id=f"h{i}",
                    name=_handoff_name(handoff.to_role),
                    role=handoff.to_role,
                    task=handoff.context,
                )
                yield AgentSpawned(spec=hspec, is_handoff=True)
                yield AgentRunning(agent_id=hspec.id)

                hresult = await run_handoff_worker(
                    spec=hspec,
                    originator=originator_result.spec,
                    originator_text=originator_result.text,
                    handoff=handoff,
                    task=task,
                    shared_memory=shared_memory,
                    lock=lock,
                    on_event=queue.put,
                )
                # Drain any events the handoff worker queued
                while not queue.empty():
                    evt = queue.get_nowait()
                    if evt is not None:
                        yield evt

                yield AgentComplete(
                    agent_id=hspec.id, text=hresult.text, status=hresult.status,
                )
                handoff_results.append(hresult)

        # ─── Phase 4 — Aggregate ─────────────────────────────────────────────
        yield PhaseStart(phase="aggregating")
        try:
            final = await aggregate(
                task=task,
                results=worker_results + handoff_results,
                shared_memory=shared_memory,
            )
        except Exception as e:
            # Don't throw away the swarm's work if the aggregator's own LLM call
            # rate-limits or errors — emit a fallback final containing the raw
            # worker outputs + memory dump so the user gets *something* usable.
            logger.warning("aggregator failed: %s — emitting fallback final", e)
            final = _fallback_final(task, worker_results + handoff_results, shared_memory, error=e)

        yield FinalResult(
            text=final,
            agents_total=len(orch.agents) + len(handoff_results),
            handoffs_total=len(handoff_results),
            memory_entries=len(shared_memory),
        )
        yield PhaseStart(phase="complete")

    except Exception as e:
        yield ErrorEvent(message=f"{type(e).__name__}: {e}")


def _handoff_name(to_role: str) -> str:
    parts = [p for p in to_role.split() if p]
    return "".join(p[0].upper() + p[1:] for p in parts) + "Agent"


def _fallback_final(
    task: str,
    results: list[WorkerResult],
    shared_memory: dict[str, str],
    error: Exception,
) -> str:
    """Concatenate worker outputs + memory into a usable fallback when the
    aggregator's own LLM call fails (e.g. rate-limited)."""
    lines: list[str] = [
        f"# Partial result for: {task}",
        "",
        f"_Aggregator synthesis failed ({type(error).__name__}: {error}). "
        "Showing raw agent outputs and shared memory below._",
        "",
    ]
    if shared_memory:
        lines.append("## Shared memory")
        for k, v in shared_memory.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")
    ok_results = [r for r in results if r.status == "ok" and r.text.strip()]
    if ok_results:
        lines.append("## Agent outputs")
        for r in ok_results:
            lines.append(f"### {r.spec.name} — {r.spec.role}")
            lines.append(r.text)
            lines.append("")
    return "\n".join(lines)
