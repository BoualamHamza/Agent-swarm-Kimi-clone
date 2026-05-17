"""Phase 1 — Orchestrator.

Single LLM call that decomposes the user task into N parallel agent specs.

Uses an **adaptive strategy ladder** because not every model on OpenRouter
supports OpenAI's strict `json_schema` response_format:

  1. `response_format = {"type": "json_schema", strict: true, ...}`     (best — guaranteed valid JSON)
  2. `response_format = {"type": "json_object"}` + schema in the prompt  (broadly supported)
  3. plain chat + schema in the prompt                                   (universal fallback)

If a strategy returns empty content or fails Pydantic validation, we fall to
the next one. We keep the last raw content + last error for diagnostics.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from langsmith import traceable
from pydantic import ValidationError

from app.client import get_openrouter
from app.models import MODELS
from app.skills_loader import skills_orchestrator_section
from app.state import AgentSpec, OrchestratorOutput

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM = """You are a swarm orchestrator. Decompose the user task into 1-20 agents that can run TRULY IN PARALLEL.

You decide how many agents the task warrants — there is no fixed count. But pick the SMALLEST number that genuinely covers the task: more agents is not better. Most tasks need 1-4; only go higher when there are genuinely many independent subtasks (e.g. "profile each of these 12 companies").

Concurrency budget: only 4 agents execute at a time — any beyond that queue and run in later waves. So 12 agents complete as 3 sequential waves of 4, not all at once. Spawning 20 narrow agents is SLOWER than 5 broad ones. Prefer fewer, broader agents unless the extra parallelism is truly warranted, and list agents in priority order (the first 4 start first).

Hard rules:
- Each agent's task MUST be independently executable WITHOUT any output produced by another agent in this run.
- An agent's task description must NOT reference another agent's output. Phrases like "given the X from agent Y", "take the array of...", "using the CSV produced by...", or "from the previous step" are forbidden.
- If the task is fundamentally a pipeline (one step feeds the next — generate→transform→export→visualize), emit a SINGLE agent that owns the whole pipeline. Do NOT fake parallelism by splitting a pipeline into dependent agents — they will all spawn at once, see empty shared memory, and bail.
- Each agent has a distinct role; no overlap.

Good decomposition (genuinely parallel):
  Task: "Research the EV market in 2026 — produce a competitive analysis."
    MarketAnalyst     — size the global EV market in 2026
    CompetitorAnalyst — profile the top 5 EV manufacturers
    RegulatoryAnalyst — summarize 2026 EV regulations in EU/US/China
    TechAnalyst       — review battery tech advances in 2026
  Each agent does its own web research; none waits on another.

Bad decomposition (a hidden pipeline — REJECT and collapse):
  Task: "Generate a CSV of the first 50 primes with gaps, then plot the gaps."
    PrimeGenerator — generate primes
    GapCalculator  — calculate gaps from PrimeGenerator's primes    ← depends on another agent
    CSVWriter      — write CSV from the primes and gaps             ← depends on two agents
    ChartMaker     — plot the gaps                                 ← depends on another agent
  Fix: emit ONE agent that does the whole thing using run_python + write_file.

When in doubt — when you can't articulate 3+ subtasks whose web searches / computations could happen in any order — emit ONE agent.

Use short PascalCase names (e.g. MarketAnalyst, TechArchitect, RiskAssessor).
Use sequential ids "a1", "a2", "a3", … in priority order.

Output JSON matching the provided schema."""

# Defensive ceiling — the prompt steers toward fewer agents, but a misbehaving
# model could return an unbounded list. Anything past this is truncated.
MAX_AGENTS = 20


def _schema() -> dict:
    """OpenAI strict JSON schema: `additionalProperties: false` everywhere."""
    return {
        "name": "orchestrator_output",
        "strict": True,
        "schema": _strictify(OrchestratorOutput.model_json_schema()),
    }


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        if node.get("type") == "object":
            node = {**node, "additionalProperties": False}
            if "properties" in node:
                node["required"] = list(node["properties"].keys())
        return {k: _strictify(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_strictify(v) for v in node]
    return node


def _strip_fences(s: str) -> str:
    """Strip markdown code fences (and an optional ```json language tag)."""
    s = s.strip()
    if not s.startswith("```"):
        return s
    rest = s[3:]
    if "\n" in rest:
        # drop the opening fence + optional ```json tag
        rest = rest.split("\n", 1)[1]
    if rest.endswith("```"):
        rest = rest[:-3]
    return rest.strip()


def _system_with_schema(base: str) -> str:
    schema_text = json.dumps(OrchestratorOutput.model_json_schema(), indent=2)
    return (
        f"{base}\n\n"
        "Return ONLY a JSON object matching this schema (no markdown fences, no prose, no explanation):\n"
        f"{schema_text}"
    )


@traceable(name="orchestrate", run_type="chain")
async def orchestrate(
    task: str,
    *,
    model: str | None = None,
    max_tokens: int = 40000,  # generous so reasoning-capable models have room to think
) -> OrchestratorOutput:
    client = get_openrouter()
    model = model or MODELS["orchestrator"]

    today = datetime.now().strftime("%Y-%m-%d")
    user_msg = f"Today's date: {today}\n\nDecompose this task: {task}"
    last_content = ""
    last_error: Exception | None = None

    system_base = ORCHESTRATOR_SYSTEM + skills_orchestrator_section()

    strategies: list[tuple[str, dict[str, Any] | None, str]] = [
        ("json_schema", {"type": "json_schema",
         "json_schema": _schema()}, system_base),
        ("json_object", {"type": "json_object"},
         _system_with_schema(system_base)),
        ("plain",       None,
         _system_with_schema(system_base)),
    ]

    for name, response_format, system in strategies:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as e:
            last_error = e
            logger.warning(
                "orchestrator '%s' strategy raised: %s — falling back", name, e)
            continue

        content = (resp.choices[0].message.content or "").strip()
        last_content = content
        if not content:
            finish = resp.choices[0].finish_reason if resp.choices else None
            usage = getattr(resp, "usage", None)
            provider = getattr(resp, "provider", None) or getattr(
                resp, "model", None)
            last_error = ValueError(
                f"empty response from model in '{name}' mode "
                f"(finish_reason={finish!r}, provider={provider!r})"
            )
            logger.warning(
                "orchestrator '%s' empty content (finish_reason=%s, provider=%s, usage=%s)",
                name, finish, provider, usage,
            )
            continue

        try:
            data = json.loads(_strip_fences(content))
            output = OrchestratorOutput.model_validate(data)
            if not output.agents:
                raise ValueError("orchestrator returned zero agents")
            if len(output.agents) > MAX_AGENTS:
                logger.warning(
                    "orchestrator returned %d agents — truncating to %d",
                    len(output.agents), MAX_AGENTS,
                )
                output.agents = output.agents[:MAX_AGENTS]
            output.agents = [
                AgentSpec(id=f"a{i+1}", name=a.name, role=a.role, task=a.task)
                for i, a in enumerate(output.agents)
            ]
            if name != "json_schema":
                logger.info(
                    "orchestrator succeeded via fallback strategy '%s'", name)
            return output
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_error = e
            logger.warning(
                "orchestrator '%s' strategy parse/validate failed (%s) — falling back", name, e)
            continue

    raise RuntimeError(
        f"Orchestrator failed across all strategies. "
        f"Last error: {type(last_error).__name__}: {last_error}. "
        f"Last raw content (first 500 chars): {last_content[:500]!r}"
    )
