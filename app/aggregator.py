"""Phase 4 — Aggregator.

Single LLM call (no tools) that synthesizes all worker + handoff results plus
the full shared-memory dump into one coherent answer.
"""
from __future__ import annotations

from langsmith import traceable

from app.client import get_openrouter
from app.models import MODELS
from app.state import WorkerResult

AGGREGATOR_SYSTEM = """You are the swarm aggregator. Multiple specialist agents have completed parallel work on a user task.

Your job: synthesize their outputs into ONE comprehensive, well-structured final answer for the user.

- Integrate findings from all agents.
- Incorporate relevant entries from shared memory.
- Resolve conflicts when agents disagree (note the disagreement and your judgment).
- Use clear sections / headings if the answer is long.
- Be thorough but not verbose."""


@traceable(name="aggregate", run_type="chain")
async def aggregate(
    *,
    task: str,
    results: list[WorkerResult],
    shared_memory: dict[str, str],
    model: str | None = None,
    max_tokens: int = 40000,  # reasoning-model headroom; non-reasoning models stop early
    artifacts: list[str] | None = None,
) -> str:
    client = get_openrouter()
    model = model or MODELS["aggregator"]

    # Only include text from workers that produced a real answer. Workers that
    # hit max_iterations / length truncation / empty content are intentionally
    # excluded — their contribution comes through shared_memory instead.
    ok_results = [r for r in results if r.status == "ok" and r.text.strip()]
    failed = [r for r in results if r.status != "ok"]

    outputs = "\n\n---\n\n".join(
        f"[{r.spec.name} — {r.spec.role}]\n{r.text}"
        for r in ok_results
    ) or "(no agents produced a final response — rely on shared memory)"

    failed_note = ""
    if failed:
        failed_note = "\n\nAgents that did not produce a final response (memory entries from them are still valid):\n" + "\n".join(
            f"- {r.spec.name} ({r.spec.role}) — status: {r.status}"
            for r in failed
        )

    mem_dump = (
        "\n".join(f"{k}: {v}" for k, v in shared_memory.items())
        if shared_memory else "(empty)"
    )

    artifact_note = ""
    if artifacts:
        artifact_note = (
            "\n\nDeliverable files saved to /home/user/workspace/artifacts/: "
            + ", ".join(artifacts)
            + ". Reference them by filename in your final answer when relevant."
        )

    user = (
        f"Original task: {task}\n\n"
        f"Shared memory:\n{mem_dump}\n\n"
        f"Agent outputs:\n{outputs}"
        f"{failed_note}"
        f"{artifact_note}\n\n"
        f"Synthesize a final answer."
    )

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": AGGREGATOR_SYSTEM},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()
