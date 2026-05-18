"""Thin conductor — `run_swarm(task)` is an async generator that yields
SwarmEvents while the Kimi-style orchestrator loop runs.

Responsibilities:
  * Boot a shared E2B sandbox and upload skills (best-effort).
  * Drive the orchestrator loop in a background task.
  * Forward events emitted by the orchestrator + each spawned worker through
    an asyncio.Queue to the caller.
  * Harvest artifacts after the loop terminates and emit ArtifactEmitted per
    file.
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

from app.memory import SharedMemoryStore, get_store
from app.orchestrator import run_orchestrator
from app.sandbox import SwarmSandbox
from app.skills_loader import upload_skills
from app.state import (
    ArtifactEmitted,
    ErrorEvent,
    FinalResult,
    PhaseStart,
    SwarmEvent,
)

logger = logging.getLogger(__name__)

_ARTIFACTS_SANDBOX_DIR = "/home/user/workspace/artifacts"
_ARTIFACTS_LOCAL_ROOT = Path.home() / ".agent-swarm" / "artifacts"


@traceable(name="run_swarm", run_type="chain")
async def run_swarm(  # type: ignore[misc]
    task: str,
    *,
    session_id: str | None = None,
    store: SharedMemoryStore | None = None,
) -> AsyncIterator[SwarmEvent]:
    """Run the orchestrator loop and yield events as they happen.

    `session_id` namespaces shared memory; reusing one across runs preserves
    findings (when the configured store is persistent). `store` defaults to
    the process-wide store from `get_store()`.

    NOTE: @traceable wraps async generators correctly in langsmith>=0.3.
    """
    store = store or get_store()
    session_id = session_id or f"ephemeral-{uuid.uuid4().hex[:8]}"
    sandbox: SwarmSandbox | None = None
    try:
        yield PhaseStart(phase="orchestrating")

        # ─── Create the shared sandbox (best-effort) ────────────────────────
        if os.getenv("E2B_API_KEY"):
            try:
                sandbox = await SwarmSandbox.create(
                    template_id=os.getenv("E2B_TEMPLATE_ID"),
                    timeout=int(os.getenv("E2B_SANDBOX_TIMEOUT", "600")),
                )
                await upload_skills(sandbox)
            except Exception as e:
                logger.warning("sandbox bootstrap failed: %s", e)
                yield ErrorEvent(message=f"sandbox unavailable: {e}", phase="orchestrating")
                sandbox = None

        # Hydrate from the persistent store so prior findings in this session
        # are visible to the orchestrator + workers from the start.
        shared_memory: dict[str, str] = await store.get_all(session_id)
        lock = asyncio.Lock()
        queue: asyncio.Queue[SwarmEvent | None] = asyncio.Queue()

        # ─── Drive the orchestrator in the background ────────────────────────
        async def driver() -> "OrchestratorRunResult":
            try:
                run = await run_orchestrator(
                    task=task,
                    shared_memory=shared_memory,
                    lock=lock,
                    on_event=queue.put,
                    sandbox=sandbox,
                    store=store,
                    session_id=session_id,
                )
                return OrchestratorRunResult(
                    final_text=run.final_text,
                    worker_count=len(run.results),
                    iterations=run.iterations,
                )
            except Exception as e:
                logger.warning("orchestrator loop crashed: %s", e)
                await queue.put(ErrorEvent(message=f"{type(e).__name__}: {e}", phase="orchestrating"))
                return OrchestratorRunResult(
                    final_text=f"(orchestrator failed: {type(e).__name__}: {e})",
                    worker_count=0,
                    iterations=0,
                )
            finally:
                await queue.put(None)

        driver_task = asyncio.create_task(driver())

        while True:
            evt = await queue.get()
            if evt is None:
                break
            yield evt

        run_result = await driver_task

        yield FinalResult(
            text=run_result.final_text,
            agents_total=run_result.worker_count,
            iterations_total=run_result.iterations,
            memory_entries=len(shared_memory),
        )

        # ─── Harvest artifacts ──────────────────────────────────────────────
        artifact_names = await _list_artifact_names(sandbox)
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


class OrchestratorRunResult:
    __slots__ = ("final_text", "worker_count", "iterations")

    def __init__(self, *, final_text: str, worker_count: int, iterations: int):
        self.final_text = final_text
        self.worker_count = worker_count
        self.iterations = iterations


# ─── Artifact harvesting ─────────────────────────────────────────────────────


async def _list_artifact_names(sandbox: SwarmSandbox | None) -> list[str]:
    """Return the bare filenames of regular files inside the artifacts dir."""
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
