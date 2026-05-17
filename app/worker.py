"""Phase 2/3 — Worker agent.

Builds the per-worker system prompt, runs the tool-use loop, and returns a
WorkerResult. Used both for Phase 2 (parallel workers spawned by orchestrator)
and Phase 3 (handoff specialist agents).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from langsmith import traceable

from app.loop import EventEmitter, tool_use_loop
from app.memory import SharedMemoryStore
from app.models import MODELS
from app.sandbox import SwarmSandbox
from app.skills_loader import skills_prompt_section
from app.state import AgentSpec, Handoff, WorkerResult
from app.tools import TOOL_SCHEMAS


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


def _worker_system(spec: AgentSpec, task: str, roster: list[AgentSpec]) -> str:
    roster_str = " | ".join(f"{a.name}({a.role})" for a in roster)
    workspace = _WORKSPACE_SECTION.replace("{agent_id}", spec.id)
    skills = skills_prompt_section()
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""Today's date: {today}

You are {spec.name}, specialist in: {spec.role}.

Overall goal: {task}
Swarm roster: {roster_str}
Your task: {spec.task}

{skills}
SKILL-FIRST PROTOCOL (mandatory):
- BEFORE your first tool call, scan the skills list above. If ANY skill's description matches your task — especially when the user said "skills", "skillset", or "all your skills" (they mean the SKILL.md system above, not vague capabilities) — you MUST read its playbook first via read_file("/home/user/skills/{{name}}/SKILL.md") and follow it. One extra read_file is cheap; skipping a skill and re-discovering its recipe by trial-and-error is expensive.
- If multiple skills apply, read each of their SKILL.md files before fanning out into other tools.
- If NO skill applies, say so briefly in your reasoning and proceed.

Tool budget — keep this loop short:
- At most 10 web_search calls. After that, work with what you have.
- After gathering enough information, write your KEY findings to shared memory and then produce your final response.
- Aim to finish within 10-12 tool calls total (skill reads do not count against this budget — they save calls).

Tool usage:
- Start by calling read_shared_memory(key="all") to see what other agents have already found. Empty memory at startup is NORMAL — the swarm just spawned and nobody has written yet.
- If your task plainly depends on another agent's finding (e.g. it mentions "the primes from PrimeGenerator", "given the array of X"), DO NOT bail. Call wait_for_memory(key="that_key", timeout_sec=60) — it blocks until that agent writes the key, then returns the value. Use specific keys you expect the upstream agent to use; if unsure, wait_for_memory with the most likely key and fall back to doing the work yourself on timeout.
- Use write_to_shared_memory to share concise findings with the swarm (short keys, concise values). Other agents may be polling for your output via wait_for_memory.
- Use calculate for any numeric reasoning.
- Use get_current_date if temporal context matters.
- Use web_search for current information only — do NOT search for things you can reason about.
- Use scrape_url to read the full content of a specific URL found via web_search when a snippet is not enough.
- Use request_handoff ONLY if you discover work needing a genuinely different specialist.
{workspace}
Your final text response is your result — write it clearly and structured for synthesis. Do not end with another tool call when your investigation is done."""


def _handoff_system(handoff: Handoff, originator: AgentSpec, originator_text: str, task: str) -> str:
    skills = skills_prompt_section()
    return f"""You are a specialist in: {handoff.to_role}.

You were dynamically spawned via a handoff from {originator.name} ({originator.role}).
Reason for handoff: {handoff.reason}

Their findings so far:
\"\"\"
{originator_text}
\"\"\"

Your specific task: {handoff.context}
Overall goal: {task}

{skills}
SKILL-FIRST PROTOCOL (mandatory):
- BEFORE your first tool call, scan the skills list above. If ANY skill's description matches your task — especially when the user said "skills" or "skillset" (they mean the SKILL.md system above, not vague capabilities) — you MUST read its playbook first via read_file("/home/user/skills/{{name}}/SKILL.md") and follow it.
- If NO skill applies, proceed normally.

Start by calling read_shared_memory(key="all") to see the full swarm context, then complete your work. Use write_to_shared_memory to record key findings. The shared sandbox at /home/user/workspace/ is available — earlier agents may have left files for you (look for `artifact:*` keys in shared memory)."""


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
    store: SharedMemoryStore | None = None,
    session_id: str | None = None,
    sandbox: SwarmSandbox | None = None,
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
        store=store,
        session_id=session_id,
        sandbox=sandbox,
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
    store: SharedMemoryStore | None = None,
    session_id: str | None = None,
    sandbox: SwarmSandbox | None = None,
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
        store=store,
        session_id=session_id,
        sandbox=sandbox,
    )
    return WorkerResult(
        spec=spec,
        text=outcome.text,
        status=outcome.status,
        handoff=None,                  # handoff agents do not chain further handoffs
        tool_calls=outcome.tool_calls,
        is_handoff=True,
    )
