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
from typing import Any

from langsmith import traceable
from pydantic import ValidationError

from app.client import get_openrouter
from app.models import MODELS
from app.state import AgentSpec, OrchestratorOutput

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM = """You are a swarm orchestrator. Your job is to decompose a user task into 3-4 PARALLEL subtasks, each handled by a specialist agent.

Rules:
- Subtasks must be genuinely parallel — no agent depends on another agent's output.
- Each agent has a distinct role; do not overlap.
- Use short PascalCase names (e.g. MarketAnalyst, TechArchitect, RiskAssessor).
- Use ids "a1", "a2", "a3", "a4".

Output JSON matching the provided schema."""


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

    user_msg = f"Decompose this task: {task}"
    last_content = ""
    last_error: Exception | None = None

    strategies: list[tuple[str, dict[str, Any] | None, str]] = [
        ("json_schema", {"type": "json_schema",
         "json_schema": _schema()}, ORCHESTRATOR_SYSTEM),
        ("json_object", {"type": "json_object"},
         _system_with_schema(ORCHESTRATOR_SYSTEM)),
        ("plain",       None,
         _system_with_schema(ORCHESTRATOR_SYSTEM)),
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
