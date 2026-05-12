"""The four-phase conductor — `run_swarm(task)` is an async generator that
yields SwarmEvents in real time as the swarm progresses.

Concurrency model:
  * Phase 2 workers run concurrently, gated by an asyncio.Semaphore.
  * Workers emit events via an asyncio.Queue (the `on_event` callback puts to it).
  * The conductor awaits the queue and yields events to the caller.
  * A `watcher` task awaits all worker tasks and pushes a None sentinel when done.

Phase 3 (handoffs) runs sequentially — handoff agents typically depend on prior
work and there are usually only one or two of them.

A single E2B SwarmSandbox is created once orchestration succeeds and shared
across every worker + handoff agent in this run. After aggregation, any file
saved under ``/home/user/workspace/artifacts/`` is downloaded to
``~/.agent-swarm/artifacts/{session_id}/`` and surfaced as an
``ArtifactEmitted`` event.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import uuid
from pathlib import Path
from typing import AsyncIterator

from langsmith import traceable

from app.aggregator import aggregate
from app.memory import SharedMemoryStore, get_store
from app.orchestrator import orchestrate
from app.sandbox import SwarmSandbox
from app.skills_loader import upload_skills
from app.state import (
    AgentComplete,
    AgentHandedOff,
    AgentRunning,
    AgentSpawned,
    AgentSpec,
    ArtifactEmitted,
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
_ARTIFACTS_SANDBOX_DIR = "/home/user/workspace/artifacts"
_ARTIFACTS_LOCAL_ROOT = Path.home() / ".agent-swarm" / "artifacts"


@traceable(name="run_swarm", run_type="chain")
async def run_swarm(  # type: ignore[misc]
    task: str,
    *,
    session_id: str | None = None,
    store: SharedMemoryStore | None = None,
) -> AsyncIterator[SwarmEvent]:
    """Run a full swarm and yield events as they happen.

    `session_id` namespaces the shared memory; reusing one across runs preserves
    findings (when the configured store is persistent). If omitted, an ephemeral
    id is generated. `store` defaults to the process-wide store from `get_store()`.

    NOTE: @traceable wraps async generators correctly in langsmith>=0.3.
    """
    store = store or get_store()
    session_id = session_id or f"ephemeral-{uuid.uuid4().hex[:8]}"
    sandbox: SwarmSandbox | None = None
    try:
        # ─── Phase 1 — Orchestrate ───────────────────────────────────────────
        yield PhaseStart(phase="orchestrating")
        orch = await orchestrate(task)
        yield OrchestratorReasoning(reasoning=orch.reasoning)
        for spec in orch.agents:
            yield AgentSpawned(spec=spec, is_handoff=False)

        # ─── Create the shared sandbox (best-effort) ─────────────────────────
        if os.getenv("E2B_API_KEY"):
            try:
                sandbox = await SwarmSandbox.create(
                    template_id=os.getenv("E2B_TEMPLATE_ID"),
                    timeout=int(os.getenv("E2B_SANDBOX_TIMEOUT", "600")),
                )
                await upload_skills(sandbox)
            except Exception as e:
                logger.warning("sandbox bootstrap failed: %s", e)
                yield ErrorEvent(message=f"sandbox unavailable: {e}", phase="executing")
                sandbox = None

        # ─── Phase 2 — Parallel workers ──────────────────────────────────────
        yield PhaseStart(phase="executing")

        sem = asyncio.Semaphore(CONCURRENCY)
        # Hydrate from the persistent store so prior findings in this session
        # are visible to all agents from the start.
        shared_memory: dict[str, str] = await store.get_all(session_id)
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
                        store=store,
                        session_id=session_id,
                        sandbox=sandbox,
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
                    store=store,
                    session_id=session_id,
                    sandbox=sandbox,
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

        # Peek at artifact filenames BEFORE the aggregator runs so it can
        # mention them in the final answer.
        artifact_names = await _list_artifact_names(sandbox)

        try:
            final = await aggregate(
                task=task,
                results=worker_results + handoff_results,
                shared_memory=shared_memory,
                artifacts=artifact_names,
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

        # ─── Phase 4.5 — Harvest artifacts ───────────────────────────────────
        if sandbox is not None and artifact_names:
            local_dir = _ARTIFACTS_LOCAL_ROOT / session_id
            try:
                local_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning("artifact local dir creation failed: %s", e)
            else:
                async for art_ev in _harvest_artifacts(
                    sandbox, artifact_names, session_id, local_dir,
                ):
                    yield art_ev
                logger.info("artifacts saved to %s", local_dir)

        yield PhaseStart(phase="complete")

    except Exception as e:
        yield ErrorEvent(message=f"{type(e).__name__}: {e}")
    finally:
        if sandbox is not None:
            try:
                await sandbox.close()
            except Exception as e:
                logger.warning("sandbox close failed: %s", e)


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


# ─── Artifact harvesting ─────────────────────────────────────────────────────


async def _list_artifact_names(sandbox: SwarmSandbox | None) -> list[str]:
    """Return the bare filenames of regular files inside the artifacts dir.

    Returns an empty list on any failure or if the sandbox is unavailable.
    """
    if sandbox is None:
        return []
    try:
        entries = await sandbox.list_files(_ARTIFACTS_SANDBOX_DIR)
    except Exception as e:
        logger.warning("artifact ls failed: %s", e)
        return []
    return [e["name"] for e in entries if not e.get("is_dir")]


async def _harvest_artifacts(
    sandbox: SwarmSandbox,
    names: list[str],
    session_id: str,
    local_dir: Path,
) -> AsyncIterator[ArtifactEmitted]:
    """Download each artifact and emit one ArtifactEmitted per file."""
    for name in names:
        sandbox_path = f"{_ARTIFACTS_SANDBOX_DIR}/{name}"
        try:
            data = await sandbox.read_bytes(sandbox_path)
        except Exception as e:
            logger.warning("artifact download failed for %s: %s", name, e)
            continue

        local_path = local_dir / name
        try:
            local_path.write_bytes(data)
        except Exception as e:
            logger.warning("artifact write failed for %s: %s", name, e)
            continue

        title = Path(name).stem
        yield ArtifactEmitted(
            identifier=f"{session_id}/{name}",
            title=title,
            mime_type=_guess_mime(name, data),
            local_path=str(local_path),
            sandbox_path=sandbox_path,
            size_bytes=len(data),
        )


def _guess_mime(filename: str, data: bytes) -> str:
    """Best-effort MIME detection: stdlib first, magic-byte fallback."""
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        return mime
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"
