"""Phase 2/3 — Worker agent.

Builds the per-worker system prompt, runs the tool-use loop, and returns a
WorkerResult. Used both for Phase 2 (parallel workers spawned by orchestrator)
and Phase 3 (handoff specialist agents).
"""
from __future__ import annotations

import asyncio

from langsmith import traceable

from app.loop import EventEmitter, tool_use_loop
from app.models import MODELS
from app.state import AgentSpec, Handoff, WorkerResult
from app.tools import TOOL_SCHEMAS


def _worker_system(spec: AgentSpec, task: str, roster: list[AgentSpec]) -> str:
    roster_str = " | ".join(f"{a.name}({a.role})" for a in roster)
    return f"""You are {spec.name}, specialist in: {spec.role}.

Overall goal: {task}
Swarm roster: {roster_str}
Your task: {spec.task}

Tool budget — keep this loop short:
- At most 3 web_search calls. After that, work with what you have.
- After gathering enough information, write your KEY findings to shared memory and then produce your final response.
- Aim to finish within 6-8 tool calls total.

Tool usage:
- Start by calling read_shared_memory(key="all") to see what other agents have found.
- Use write_to_shared_memory to share concise findings with the swarm (short keys, concise values).
- Use calculate for any numeric reasoning.
- Use get_current_date if temporal context matters.
- Use web_search for current information only — do NOT search for things you can reason about.
- Use request_handoff ONLY if you discover work needing a genuinely different specialist.

Your final text response is your result — write it clearly and structured for synthesis. Do not end with another tool call when your investigation is done."""


def _handoff_system(handoff: Handoff, originator: AgentSpec, originator_text: str, task: str) -> str:
    return f"""You are a specialist in: {handoff.to_role}.

You were dynamically spawned via a handoff from {originator.name} ({originator.role}).
Reason for handoff: {handoff.reason}

Their findings so far:
\"\"\"
{originator_text}
\"\"\"

Your specific task: {handoff.context}
Overall goal: {task}

Start by calling read_shared_memory(key="all") to see the full swarm context, then complete your work. Use write_to_shared_memory to record key findings."""


@traceable(name="worker", run_type="chain")
async def run_worker(
    *,
    spec: AgentSpec,
    task: str,
    roster: list[AgentSpec],
    shared_memory: dict[str, str],
    lock: asyncio.Lock,
    on_event: EventEmitter | None = None,
    model: str | None = None,
) -> WorkerResult:
    outcome = await tool_use_loop(
        agent_id=spec.id,
        model=model or MODELS["worker"],
        system=_worker_system(spec, task, roster),
        user=f"Execute your task: {spec.task}",
        tools=TOOL_SCHEMAS,
        shared_memory=shared_memory,
        lock=lock,
        on_event=on_event,
    )
    return WorkerResult(
        spec=spec,
        text=outcome.text,
        status=outcome.status,
        handoff=outcome.handoff,
        tool_calls=outcome.tool_calls,
    )


@traceable(name="handoff_worker", run_type="chain")
async def run_handoff_worker(
    *,
    spec: AgentSpec,
    originator: AgentSpec,
    originator_text: str,
    handoff: Handoff,
    task: str,
    shared_memory: dict[str, str],
    lock: asyncio.Lock,
    on_event: EventEmitter | None = None,
    model: str | None = None,
) -> WorkerResult:
    outcome = await tool_use_loop(
        agent_id=spec.id,
        model=model or MODELS["worker"],
        system=_handoff_system(handoff, originator, originator_text, task),
        user=handoff.context,
        tools=TOOL_SCHEMAS,
        shared_memory=shared_memory,
        lock=lock,
        on_event=on_event,
    )
    return WorkerResult(
        spec=spec,
        text=outcome.text,
        status=outcome.status,
        handoff=None,                  # handoff agents do not chain further handoffs
        tool_calls=outcome.tool_calls,
        is_handoff=True,
    )
