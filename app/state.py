"""Pydantic state types — orchestrator I/O, worker records, swarm events.

SwarmEvent is a discriminated union; consumers (SSE clients, tests) dispatch on
the `type` field. Each event self-describes via Literal type tags.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Worker spec ─────────────────────────────────────────────────────────────


class AgentSpec(BaseModel):
    """A single worker definition. ``id`` is assigned by the swarm when the
    worker is spawned (orchestrator does not pick it)."""
    id: str = Field(description="Short unique id like 'w3'")
    name: str = Field(description="Short PascalCase agent name")
    role: str = Field(description="One-line specialist description")
    task: str = Field(description="Specific subtask to execute")
    # Forward-compat: per-agent skill curation. v1 ignores this — every worker
    # sees every installed skill. The orchestrator can populate it later.
    skills: list[str] | None = None


class WorkerSpec(BaseModel):
    """The shape the orchestrator emits inside `spawn_workers(specs=[...])`.

    Identical to AgentSpec minus `id` — the swarm assigns ids centrally so the
    orchestrator never has to track them.
    """
    name: str = Field(description="Short PascalCase agent name")
    role: str = Field(description="One-line specialist description")
    task: str = Field(description="Specific subtask to execute")
    skills: list[str] | None = None


# ─── Worker primitives ───────────────────────────────────────────────────────


class ToolCallRecord(BaseModel):
    name: str
    input: dict[str, Any]
    result: str


# Outcome of a single worker / loop run. Distinguishes "produced a real answer"
# from soft-failure modes so the orchestrator can ignore garbage text and the
# SSE stream can surface the failure.
WorkerStatus = Literal[
    "ok",                # produced a final text response
    "max_iterations",    # exhausted iteration cap mid-tool-loop
    "length_truncated",  # finish_reason="length" with empty content (reasoning ate all the tokens)
    "empty",             # model stopped but returned no text
    "error",             # exception during the loop (e.g. RateLimitError after retries exhausted)
]


class WorkerResult(BaseModel):
    spec: AgentSpec
    text: str
    status: WorkerStatus = "ok"
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class LoopOutcome(BaseModel):
    """Return type of `tool_use_loop`. Replaces the old 3-tuple so we can extend
    without breaking call sites."""
    text: str
    status: WorkerStatus
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class SpawnSummary(BaseModel):
    """Per-worker summary returned to the orchestrator from `spawn_workers`.

    Only the short summary (the worker's final assistant text) travels back to
    the orchestrator — full worker output stays in shared memory under
    `worker:<agent_id>:output`.
    """
    agent_id: str
    name: str
    role: str
    status: WorkerStatus
    summary: str


class SpawnResult(BaseModel):
    """Aggregate result of one `spawn_workers` tool call."""
    workers: list[SpawnSummary]


# ─── Swarm events (discriminated union) ──────────────────────────────────────


class _EventBase(BaseModel):
    timestamp: datetime = Field(default_factory=_now)


class PhaseStart(_EventBase):
    type: Literal["phase_start"] = "phase_start"
    # Free-form so the orchestrator can emit phases like
    # "orchestrator-iteration-1", "orchestrator-iteration-2", etc.
    # Well-known values: "orchestrating", "executing", "complete".
    phase: str


class OrchestratorReasoning(_EventBase):
    type: Literal["orchestrator_reasoning"] = "orchestrator_reasoning"
    reasoning: str


class AgentSpawned(_EventBase):
    type: Literal["agent_spawned"] = "agent_spawned"
    spec: AgentSpec
    # Retained for back-compat with the TUI; the new orchestrator always sets False.
    is_handoff: bool = False


class AgentRunning(_EventBase):
    type: Literal["agent_running"] = "agent_running"
    agent_id: str


class ToolCallEvent(_EventBase):
    type: Literal["tool_call"] = "tool_call"
    agent_id: str
    name: str
    input: dict[str, Any]


class ToolResultEvent(_EventBase):
    type: Literal["tool_result"] = "tool_result"
    agent_id: str
    name: str
    result: str


class MemoryWrite(_EventBase):
    type: Literal["memory_write"] = "memory_write"
    agent_id: str
    key: str
    value: str


class AgentComplete(_EventBase):
    type: Literal["agent_complete"] = "agent_complete"
    agent_id: str
    text: str
    status: WorkerStatus = "ok"


class FinalResult(_EventBase):
    type: Literal["final_result"] = "final_result"
    text: str
    agents_total: int
    iterations_total: int = 0
    memory_entries: int = 0


class ArtifactEmitted(_EventBase):
    """A user-facing deliverable harvested from the sandbox after the loop terminates.

    The conductor downloads each file from ``/home/user/workspace/artifacts/``
    to ``~/.agent-swarm/artifacts/{session_id}/`` and emits one of these per
    file. The TUI renders them in a dedicated panel.
    """
    type: Literal["artifact_emitted"] = "artifact_emitted"
    identifier: str       # f"{session_id}/{filename}"
    title: str            # filename without extension
    mime_type: str        # "image/png" / "text/csv" / "application/octet-stream" etc.
    local_path: str       # absolute path on the host
    sandbox_path: str     # absolute path inside the e2b sandbox
    size_bytes: int


class ErrorEvent(_EventBase):
    type: Literal["error"] = "error"
    message: str
    phase: str | None = None


SwarmEvent = Annotated[
    Union[
        PhaseStart,
        OrchestratorReasoning,
        AgentSpawned,
        AgentRunning,
        ToolCallEvent,
        ToolResultEvent,
        MemoryWrite,
        AgentComplete,
        FinalResult,
        ArtifactEmitted,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]
