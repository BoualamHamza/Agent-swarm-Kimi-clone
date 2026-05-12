"""Scripted demo event stream for `agent-swarm --demo`.

Yields a plausible math-benchmark-creation swarm run over ~30s. No API keys
required — same event-router consumes it as a real `run_swarm()`, so the UI
is exercised end-to-end.

The script is intentionally hand-written rather than a recording: it covers
every event variant and every tool icon at least once, drives a Phase-3
handoff, and produces a final synthesized answer.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from pathlib import Path

from app.state import (
    AgentComplete,
    AgentHandedOff,
    AgentRunning,
    AgentSpawned,
    AgentSpec,
    ArtifactEmitted,
    FinalResult,
    Handoff,
    HandoffRequested,
    MemoryWrite,
    OrchestratorReasoning,
    PhaseStart,
    SwarmEvent,
    ToolCallEvent,
    ToolResultEvent,
)


# Per-event delay schedule — tuned so the whole demo runs ~28s on a typical
# terminal without feeling either jumpy or sluggish.
_FAST = 0.18
_MED  = 0.45
_SLOW = 1.2


async def scripted_events() -> AsyncIterator[SwarmEvent]:
    """Async generator producing a ~30s scripted swarm run."""

    # ─── Phase 1 — Orchestrating ────────────────────────────────────────────
    yield PhaseStart(phase="orchestrating")
    await asyncio.sleep(_MED)

    yield OrchestratorReasoning(reasoning=(
        "The task needs four parallel designers — one per math domain — plus "
        "a reviewer to consolidate problem quality. A calculus specialist may "
        "be needed if any subtask hits derivatives."
    ))
    await asyncio.sleep(_MED)

    a1 = AgentSpec(id="a1", name="ArithmeticDesigner", role="arithmetic problems",
                   task="Generate 5 arithmetic word problems with step-by-step solutions")
    a2 = AgentSpec(id="a2", name="AlgebraDesigner",    role="algebra problems",
                   task="Generate 5 algebra word problems with step-by-step solutions")
    a3 = AgentSpec(id="a3", name="GeometryDesigner",   role="geometry problems",
                   task="Generate 5 geometry word problems with step-by-step solutions")
    a4 = AgentSpec(id="a4", name="ProblemReviewer",    role="quality reviewer",
                   task="Read findings from all designers and synthesize a final benchmark")

    for spec in (a1, a2, a3, a4):
        yield AgentSpawned(spec=spec, is_handoff=False)
        await asyncio.sleep(_FAST)

    # ─── Phase 2 — Executing ────────────────────────────────────────────────
    yield PhaseStart(phase="executing")
    await asyncio.sleep(_FAST)

    for sid in ("a1", "a2", "a3", "a4"):
        yield AgentRunning(agent_id=sid)
        await asyncio.sleep(_FAST)

    # a1 calls get_current_date
    yield ToolCallEvent(agent_id="a1", name="get_current_date", input={})
    await asyncio.sleep(_FAST)
    yield ToolResultEvent(agent_id="a1", name="get_current_date",
                          result="2026-05-11T18:30:00+00:00")
    await asyncio.sleep(_FAST)

    # a2 calls calculate
    yield ToolCallEvent(agent_id="a2", name="calculate", input={"expression": "3 * pi"})
    await asyncio.sleep(_MED)
    yield ToolResultEvent(agent_id="a2", name="calculate", result="3 * pi = 9.42477...")
    await asyncio.sleep(_FAST)

    # a3 calls web_search
    yield ToolCallEvent(agent_id="a3", name="web_search",
                        input={"query": "geometry word problems for middle school", "max_results": 5})
    await asyncio.sleep(_SLOW)
    yield ToolResultEvent(agent_id="a3", name="web_search",
                          result="5 results found...")
    await asyncio.sleep(_FAST)

    # a1 writes to shared memory
    yield ToolCallEvent(agent_id="a1", name="write_to_shared_memory",
                        input={"key": "arithmetic_problems", "value": "5 problems generated"})
    await asyncio.sleep(_FAST)
    yield MemoryWrite(agent_id="a1", key="arithmetic_problems",
                      value="Q1: A bakery sold 24 loaves on Monday and 31 on Tuesday. Total? (Answer: 55)")
    await asyncio.sleep(_FAST)
    yield ToolResultEvent(agent_id="a1", name="write_to_shared_memory",
                          result='Stored under key "arithmetic_problems".')
    await asyncio.sleep(_MED)

    # a3 calls run_python
    yield ToolCallEvent(agent_id="a3", name="run_python",
                        input={"code": "from math import pi; print(round(pi*7**2, 2))", "timeout": 5})
    await asyncio.sleep(_SLOW)
    yield ToolResultEvent(agent_id="a3", name="run_python",
                          result="stdout:\n153.94")
    await asyncio.sleep(_FAST)

    # a3 writes memory
    yield ToolCallEvent(agent_id="a3", name="write_to_shared_memory",
                        input={"key": "geometry_problems", "value": "..."})
    await asyncio.sleep(_FAST)
    yield MemoryWrite(agent_id="a3", key="geometry_problems",
                      value="Q1: A circular garden has radius 7m. Area? (Answer: 153.94 m²)")
    await asyncio.sleep(_FAST)

    # a4 reads shared memory
    yield ToolCallEvent(agent_id="a4", name="read_shared_memory", input={"key": "all"})
    await asyncio.sleep(_MED)
    yield ToolResultEvent(agent_id="a4", name="read_shared_memory",
                          result="[arithmetic_problems]: ...\n[geometry_problems]: ...")
    await asyncio.sleep(_FAST)

    # a2 writes memory
    yield ToolCallEvent(agent_id="a2", name="write_to_shared_memory",
                        input={"key": "algebra_problems", "value": "..."})
    await asyncio.sleep(_FAST)
    yield MemoryWrite(agent_id="a2", key="algebra_problems",
                      value="Q1: Solve 2x + 3 = 11. (Answer: x = 4)")
    await asyncio.sleep(_FAST)

    # a2 hits a calculus subproblem — request handoff
    handoff = Handoff(
        to_role="calculus specialist",
        reason="Q5 in the set needs a derivative; outside algebra scope",
        context="Compute d/dx(3x^2 + 2x) and produce a step-by-step solution for the benchmark.",
    )
    yield ToolCallEvent(agent_id="a2", name="request_handoff",
                        input={"to_role": handoff.to_role, "reason": handoff.reason,
                               "context": handoff.context})
    await asyncio.sleep(_MED)
    yield HandoffRequested(agent_id="a2", handoff=handoff)
    await asyncio.sleep(_FAST)
    yield ToolResultEvent(agent_id="a2", name="request_handoff",
                          result='Handoff to "calculus specialist" registered.')
    await asyncio.sleep(_FAST)
    yield AgentHandedOff(agent_id="a2",
                         text="Algebra problems 1-4 complete; Q5 deferred to specialist.",
                         handoff=handoff)
    await asyncio.sleep(_MED)

    # a1, a3, a4 complete
    yield AgentComplete(agent_id="a1",
                        text="5 arithmetic problems generated and stored.",
                        status="ok")
    await asyncio.sleep(_FAST)
    yield AgentComplete(agent_id="a3",
                        text="5 geometry problems generated and stored.",
                        status="ok")
    await asyncio.sleep(_FAST)
    yield AgentComplete(agent_id="a4",
                        text="Benchmark structure reviewed; awaiting final algebra entry.",
                        status="ok")
    await asyncio.sleep(_MED)

    # ─── Phase 3 — Handoffs ─────────────────────────────────────────────────
    yield PhaseStart(phase="handoffs")
    await asyncio.sleep(_FAST)

    h1 = AgentSpec(id="h1", name="CalculusSpecialistAgent",
                   role="calculus specialist",
                   task=handoff.context)
    yield AgentSpawned(spec=h1, is_handoff=True)
    await asyncio.sleep(_FAST)
    yield AgentRunning(agent_id="h1")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="h1", name="calculate", input={"expression": "6*1 + 2"})
    await asyncio.sleep(_MED)
    yield ToolResultEvent(agent_id="h1", name="calculate", result="6*1 + 2 = 8")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="h1", name="write_to_shared_memory",
                        input={"key": "calculus_problem", "value": "..."})
    await asyncio.sleep(_FAST)
    yield MemoryWrite(agent_id="h1", key="calculus_problem",
                      value="Q5: d/dx(3x²+2x) = 6x+2. At x=1, slope = 8.")
    await asyncio.sleep(_FAST)
    yield AgentComplete(agent_id="h1",
                        text="Calculus subproblem solved and stored.",
                        status="ok")
    await asyncio.sleep(_MED)

    # ─── Phase 4 — Aggregating ──────────────────────────────────────────────
    yield PhaseStart(phase="aggregating")
    await asyncio.sleep(_SLOW)

    final_text = (
        "## Math Word-Problem Benchmark (15 problems)\n\n"
        "**Arithmetic (5)** — generated by ArithmeticDesigner\n"
        "**Algebra (5)** — 4 by AlgebraDesigner + 1 deferred to CalculusSpecialist\n"
        "**Geometry (5)** — generated by GeometryDesigner\n\n"
        "All problems include step-by-step solutions and were reviewed for "
        "difficulty consistency by ProblemReviewer."
    )
    yield FinalResult(text=final_text, agents_total=5, handoffs_total=1, memory_entries=4)
    await asyncio.sleep(_FAST)

    # ─── Phase 4.5 — Artifacts (scripted) ───────────────────────────────────
    # Write tiny demo files locally so the artifact preview pane has real
    # content to display when the user switches to the Artifacts tab.
    demo_dir = Path.home() / ".agent-swarm" / "artifacts" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    csv_path = demo_dir / "benchmark.csv"
    csv_bytes = (
        b"problem_id,domain,difficulty,answer\n"
        b"Q1,arithmetic,easy,55\n"
        b"Q2,geometry,medium,153.94\n"
        b"Q3,algebra,easy,4\n"
        b"Q4,algebra,medium,12\n"
        b"Q5,calculus,hard,8\n"
    )
    csv_path.write_bytes(csv_bytes)

    md_path = demo_dir / "summary.md"
    md_bytes = (
        b"# Math Word-Problem Benchmark\n\n"
        b"15 problems across arithmetic, algebra, geometry, and calculus.\n\n"
        b"## Coverage\n\n"
        b"- Arithmetic: 5 problems\n"
        b"- Algebra: 5 problems (1 deferred to calculus specialist)\n"
        b"- Geometry: 5 problems\n\n"
        b"Each problem includes a step-by-step solution.\n"
    )
    md_path.write_bytes(md_bytes)

    yield ArtifactEmitted(
        identifier="demo/benchmark.csv",
        title="benchmark",
        mime_type="text/csv",
        local_path=str(csv_path),
        sandbox_path="/home/user/workspace/artifacts/benchmark.csv",
        size_bytes=len(csv_bytes),
    )
    await asyncio.sleep(_FAST)
    yield ArtifactEmitted(
        identifier="demo/summary.md",
        title="summary",
        mime_type="text/markdown",
        local_path=str(md_path),
        sandbox_path="/home/user/workspace/artifacts/summary.md",
        size_bytes=len(md_bytes),
    )
    await asyncio.sleep(_FAST)

    yield PhaseStart(phase="complete")
