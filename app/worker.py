"""Worker agent — pure executor in the Kimi-style swarm.

Builds the per-worker system prompt, runs the tool-use loop, persists the
worker's full final output to shared memory under ``worker:<agent_id>:output``,
and returns a WorkerResult whose ``text`` is the *short summary* the
orchestrator consumes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from langsmith import traceable

from app.loop import EventEmitter, tool_use_loop
from app.memory import SharedMemoryStore
from app.models import MODELS
from app.sandbox import SwarmSandbox
from app.skills_loader import skills_prompt_section
from app.state import AgentSpec, WorkerResult
from app.tools import TOOL_SCHEMAS

logger = logging.getLogger(__name__)


_WORKSPACE_SECTION = """
Workspace — shared filesystem sandbox:
- Path: /home/user/workspace/ — ALL agents in this swarm see the same files.
- Tools: read_file, write_file, edit_file, list_files, glob_files, grep_files
  for navigating the filesystem; run_shell for commands like mkdir/mv/du;
  run_python for executing Python (each call is a fresh interpreter — persist
  state by writing to disk under /home/user/workspace/).
- Namespacing: other agents share this filesystem. To avoid collisions during
  parallel execution, prefix files you create with your agent id
  (e.g. analysis_{agent_id}.py).
- Deliverables: save user-facing outputs (charts, reports, CSVs, etc.) under
  /home/user/workspace/artifacts/ — files there are exposed to the user at
  the end of the run.
"""


def _worker_system(spec: AgentSpec, task: str) -> str:
    workspace = _WORKSPACE_SECTION.replace("{agent_id}", spec.id)
    skills = skills_prompt_section()
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""Today's date: {today}

You are {spec.name}, specialist in: {spec.role}.

Overall user goal: {task}
Your task: {spec.task}

You are a pure executor. An orchestrator decides what work needs doing and may
spawn follow-up specialists after you finish; you do not produce the user's
final answer yourself. Do your task, write findings + artifacts to the shared
sandbox, then end with a SHORT summary (200-500 tokens) describing what you
did and where to find it. Your detailed work is preserved in shared memory and
the workspace — the orchestrator reads it on demand.

{skills}
SKILL-FIRST PROTOCOL (mandatory):
- BEFORE your first tool call, scan the skills list above. If ANY skill's description matches your task — especially when the user said "skills", "skillset", or "all your skills" (they mean the SKILL.md system above, not vague capabilities) — you MUST read its playbook first via read_file("/home/user/skills/{{name}}/SKILL.md") and follow it. One extra read_file is cheap; skipping a skill and re-discovering its recipe by trial-and-error is expensive.
- If multiple skills apply, read each of their SKILL.md files before fanning out into other tools.
- If NO skill applies, say so briefly in your reasoning and proceed.

Tool budget — keep this loop short (HARD CAP: 15 iterations; you will be killed at the cap):
- At most 10 web_search calls. After that, work with what you have.
- Aim to finish within 10-12 tool calls total (skill reads do not count against this budget — they save calls).

PERSIST AS YOU GO — non-negotiable:
- Write findings to shared memory CONTINUOUSLY as you discover them, NOT only at the end. Every 2-3 research tool calls, write_to_shared_memory with whatever you've found so far. If you get killed by the iteration cap, your last write is what the swarm sees — silence means your work is lost.
- After each successful scrape_url / web_search batch, persist a structured note with what you learned + the source URL. Even a partial note is more useful than nothing.
- Concrete pattern: scrape → distill → write_to_shared_memory → repeat. Do NOT batch up 5+ scrapes and "summarize at the end" — you may never reach the end.
- Use short descriptive keys, e.g. `orange:offers`, `orange:fibre_prices`, `free:freebox_pop`. The orchestrator and downstream workers pull by key.

Tool usage:
- Start by calling read_shared_memory(key="all") to see what other agents (current and prior iterations) have already found.
- Use wait_for_memory only if you are explicitly told to wait for an upstream finding.
- Use calculate for any numeric reasoning.
- Use get_current_date if temporal context matters.
- Use web_search for current information only — do NOT search for things you can reason about.
- Use scrape_url to read the full content of a specific URL found via web_search when a snippet is not enough.
{workspace}
End with a clear, short summary of what you did and the keys/paths where the orchestrator can find your detailed output. Do not end with another tool call when your work is done."""


@traceable(name="worker", run_type="chain")
async def run_worker(
    *,
    spec: AgentSpec,
    task: str,
    shared_memory: dict[str, str],
    lock: asyncio.Lock,
    on_event: EventEmitter | None = None,
    model: str | None = None,
    store: SharedMemoryStore | None = None,
    session_id: str | None = None,
    sandbox: SwarmSandbox | None = None,
) -> WorkerResult:
    outcome = await tool_use_loop(
        agent_id=spec.id,
        model=model or MODELS["worker"],
        system=_worker_system(spec, task),
        user=f"Execute your task: {spec.task}",
        tools=TOOL_SCHEMAS,
        shared_memory=shared_memory,
        lock=lock,
        on_event=on_event,
        store=store,
        session_id=session_id,
        sandbox=sandbox,
    )

    # Persist the worker's full final output to shared memory so the
    # orchestrator (or a follow-up worker) can pull it on demand.
    output_key = f"worker:{spec.id}:output"
    async with lock:
        shared_memory[output_key] = outcome.text
    if store is not None and session_id is not None:
        try:
            await store.put(session_id, output_key, outcome.text)
        except Exception as e:
            logger.warning(
                "memory store write failed (session=%s, key=%r): %s",
                session_id, output_key, e,
            )

    return WorkerResult(
        spec=spec,
        text=outcome.text,
        status=outcome.status,
        tool_calls=outcome.tool_calls,
    )
