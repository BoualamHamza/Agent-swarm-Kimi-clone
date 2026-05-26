"""Scripted demo event stream for `agent-swarm --demo`.

Yields a plausible math-benchmark-creation swarm run over ~30s. No API keys
required — same event-router consumes it as a real `run_swarm()`, so the UI
is exercised end-to-end.

The script is hand-written rather than recorded: it covers every event variant
in the new Kimi-style orchestrator loop (two iterations: a 4-worker research
cohort, then a 1-worker reconciler), drives multiple tool icons, and produces
a final synthesized answer.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from app.state import (
    AgentComplete,
    AgentRunning,
    AgentSpawned,
    AgentSpec,
    ArtifactEmitted,
    FinalResult,
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

    yield PhaseStart(phase="orchestrating")
    await asyncio.sleep(_MED)

    yield OrchestratorReasoning(reasoning=(
        "I'll run two iterations: first spawn four parallel designers — one "
        "per math domain — to draft problem sets in shared memory, then spawn "
        "a single reviewer to consolidate them into a benchmark."
    ))
    await asyncio.sleep(_MED)

    # ─── Iteration 1 — four parallel research designers ─────────────────────
    yield PhaseStart(phase="orchestrator-iteration-1")
    await asyncio.sleep(_FAST)

    w1 = AgentSpec(id="w1", name="ArithmeticDesigner", role="arithmetic problems",
                   task="Generate 5 arithmetic word problems with step-by-step solutions")
    w2 = AgentSpec(id="w2", name="AlgebraDesigner",    role="algebra problems",
                   task="Generate 5 algebra word problems with step-by-step solutions")
    w3 = AgentSpec(id="w3", name="GeometryDesigner",   role="geometry problems",
                   task="Generate 5 geometry word problems with step-by-step solutions")
    w4 = AgentSpec(id="w4", name="CalculusDesigner",   role="calculus problems",
                   task="Generate 5 calculus word problems with step-by-step solutions")

    for spec in (w1, w2, w3, w4):
        yield AgentSpawned(spec=spec)
        await asyncio.sleep(_FAST)

    for sid in ("w1", "w2", "w3", "w4"):
        yield AgentRunning(agent_id=sid)
        await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w1", name="get_current_date", input={})
    await asyncio.sleep(_FAST)
    yield ToolResultEvent(agent_id="w1", name="get_current_date",
                          result="2026-05-11T18:30:00+00:00")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w2", name="calculate", input={"expression": "3 * pi"})
    await asyncio.sleep(_MED)
    yield ToolResultEvent(agent_id="w2", name="calculate", result="3 * pi = 9.42477...")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w3", name="web_search",
                        input={"query": "geometry word problems for middle school", "max_results": 5})
    await asyncio.sleep(_SLOW)
    yield ToolResultEvent(agent_id="w3", name="web_search", result="5 results found...")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w1", name="write_to_shared_memory",
                        input={"key": "arithmetic_problems", "value": "5 problems generated"})
    await asyncio.sleep(_FAST)
    yield MemoryWrite(agent_id="w1", key="arithmetic_problems",
                      value="Q1: A bakery sold 24 loaves on Monday and 31 on Tuesday. Total? (Answer: 55)")
    await asyncio.sleep(_FAST)
    yield ToolResultEvent(agent_id="w1", name="write_to_shared_memory",
                          result='Stored under key "arithmetic_problems".')
    await asyncio.sleep(_MED)

    yield ToolCallEvent(agent_id="w3", name="run_python",
                        input={"code": "from math import pi; print(round(pi*7**2, 2))", "timeout": 5})
    await asyncio.sleep(_SLOW)
    yield ToolResultEvent(agent_id="w3", name="run_python", result="stdout:\n153.94")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w3", name="write_to_shared_memory",
                        input={"key": "geometry_problems", "value": "..."})
    await asyncio.sleep(_FAST)
    yield MemoryWrite(agent_id="w3", key="geometry_problems",
                      value="Q1: A circular garden has radius 7m. Area? (Answer: 153.94 m²)")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w2", name="write_to_shared_memory",
                        input={"key": "algebra_problems", "value": "..."})
    await asyncio.sleep(_FAST)
    yield MemoryWrite(agent_id="w2", key="algebra_problems",
                      value="Q1: Solve 2x + 3 = 11. (Answer: x = 4)")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w4", name="calculate", input={"expression": "6*1 + 2"})
    await asyncio.sleep(_MED)
    yield ToolResultEvent(agent_id="w4", name="calculate", result="6*1 + 2 = 8")
    await asyncio.sleep(_FAST)
    yield ToolCallEvent(agent_id="w4", name="write_to_shared_memory",
                        input={"key": "calculus_problem", "value": "..."})
    await asyncio.sleep(_FAST)
    yield MemoryWrite(agent_id="w4", key="calculus_problem",
                      value="Q5: d/dx(3x²+2x) = 6x+2. At x=1, slope = 8.")
    await asyncio.sleep(_FAST)

    for sid, text in (
        ("w1", "5 arithmetic problems generated and stored."),
        ("w2", "5 algebra problems generated and stored."),
        ("w3", "5 geometry problems generated and stored."),
        ("w4", "5 calculus problems generated and stored."),
    ):
        yield AgentComplete(agent_id=sid, text=text, status="ok")
        await asyncio.sleep(_FAST)

    # ─── Iteration 2 — single reconciler/reviewer ───────────────────────────
    yield PhaseStart(phase="orchestrator-iteration-2")
    await asyncio.sleep(_FAST)

    w5 = AgentSpec(id="w5", name="BenchmarkReviewer", role="quality reviewer",
                   task="Read all designer findings from shared memory and synthesize a final benchmark file")
    yield AgentSpawned(spec=w5)
    await asyncio.sleep(_FAST)
    yield AgentRunning(agent_id="w5")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w5", name="read_shared_memory", input={"key": "all"})
    await asyncio.sleep(_MED)
    yield ToolResultEvent(agent_id="w5", name="read_shared_memory",
                          result="[arithmetic_problems]: ...\n[algebra_problems]: ...\n[geometry_problems]: ...\n[calculus_problem]: ...")
    await asyncio.sleep(_FAST)

    yield ToolCallEvent(agent_id="w5", name="write_file",
                        input={"path": "workspace/artifacts/benchmark.csv", "content": "problem_id,domain,..."})
    await asyncio.sleep(_MED)
    yield ToolResultEvent(agent_id="w5", name="write_file",
                          result="Wrote /home/user/workspace/artifacts/benchmark.csv")
    await asyncio.sleep(_FAST)

    yield AgentComplete(agent_id="w5",
                        text="Benchmark consolidated and saved to /home/user/workspace/artifacts/benchmark.csv.",
                        status="ok")
    await asyncio.sleep(_MED)

    # ─── Final synthesized answer (no separate aggregator phase) ────────────
    final_text = (
        "## Math Word-Problem Benchmark (20 problems)\n\n"
        "**Arithmetic (5)** — by ArithmeticDesigner\n"
        "**Algebra (5)** — by AlgebraDesigner\n"
        "**Geometry (5)** — by GeometryDesigner\n"
        "**Calculus (5)** — by CalculusDesigner\n\n"
        "All problems include step-by-step solutions and were consolidated "
        "by BenchmarkReviewer into `benchmark.csv`."
    )
    yield FinalResult(text=final_text, agents_total=5, iterations_total=2, memory_entries=4)
    await asyncio.sleep(_FAST)

    # ─── Artifacts (scripted) ───────────────────────────────────────────────
    demo_dir = Path.cwd() / ".agent-swarm" / "artifacts" / "demo"
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
        b"20 problems across arithmetic, algebra, geometry, and calculus.\n\n"
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
