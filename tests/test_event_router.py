"""EventRouter — verify every SwarmEvent variant produces a UI effect with no
exceptions. Uses the scripted demo as a comprehensive event source.
"""
from __future__ import annotations

import pytest

from app.state import (
    AgentComplete,
    AgentRunning,
    AgentSpawned,
    AgentSpec,
    ArtifactEmitted,
    ErrorEvent,
    MemoryWrite,
    OrchestratorReasoning,
    PhaseStart,
    ToolCallEvent,
)
from app.tui.demo import scripted_events
from app.tui.main import SwarmApp


@pytest.mark.asyncio
async def test_every_event_type_dispatches_without_error():
    """Run scripted_events synchronously through the router and check that
    every emitted SwarmEvent.type matches a handler in EventRouter._handlers.
    """
    app = SwarmApp(demo=False)
    async with app.run_test(size=(140, 40)) as pilot:
        # Manually pump the demo events into the router so we don't have to
        # sleep through the entire 28s schedule.
        seen_types: set[str] = set()
        async for ev in scripted_events():
            seen_types.add(ev.type)
            app.router.dispatch(ev)  # type: ignore[union-attr]
        await pilot.pause(0.5)

    # All 12 non-error variants should appear in the scripted demo.
    expected = {
        "phase_start", "orchestrator_reasoning", "agent_spawned", "agent_running",
        "tool_call", "tool_result", "memory_write", "handoff_requested",
        "agent_complete", "agent_handed_off", "final_result",
        "artifact_emitted",
    }
    assert expected.issubset(seen_types), f"missing: {expected - seen_types}"
    # The router knows about every type the demo emits plus the error variant.
    from app.tui.event_router import EventRouter
    assert seen_types.issubset(set(EventRouter._handlers.keys()))


@pytest.mark.asyncio
async def test_router_handles_error_event():
    app = SwarmApp(demo=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.router.dispatch(ErrorEvent(message="rate limited"))  # type: ignore[union-attr]
        await pilot.pause(0.2)
    # No exception is the assertion; the chat pane should also have updated
    # thinking text — but rendering details vary, so we only check the call
    # path didn't blow up.


@pytest.mark.asyncio
async def test_artifact_event_mounts_row():
    """Dispatching an ArtifactEmitted should add a row to the artifacts view
    in the right-hand SwarmComputer pane and auto-switch to that tab."""
    app = SwarmApp(demo=False)
    async with app.run_test(size=(140, 40)) as pilot:
        view = app.swarm_computer.artifacts_view
        assert len(view._rows) == 0
        app.router.dispatch(  # type: ignore[union-attr]
            ArtifactEmitted(
                identifier="t/chart.png",
                title="chart",
                mime_type="image/png",
                local_path="/tmp/chart.png",
                sandbox_path="/home/user/workspace/artifacts/chart.png",
                size_bytes=1024,
            )
        )
        await pilot.pause(0.2)
        # First artifact triggers an auto-switch to the artifacts tab.
        assert app.swarm_computer._tabs.active == "tab-artifacts"
    assert len(view._rows) == 1
    assert view._rows[0].title == "chart"


@pytest.mark.asyncio
async def test_spawn_then_run_then_complete_flow():
    """A minimal hand-assembled sequence: spawn → run → tool → complete."""
    spec = AgentSpec(id="x1", name="TestAgent", role="test specialist", task="test task")
    events = [
        PhaseStart(phase="orchestrating"),
        OrchestratorReasoning(reasoning="testing"),
        AgentSpawned(spec=spec, is_handoff=False),
        PhaseStart(phase="executing"),
        AgentRunning(agent_id="x1"),
        ToolCallEvent(agent_id="x1", name="calculate", input={"expression": "1+1"}),
        MemoryWrite(agent_id="x1", key="result", value="2"),
        AgentComplete(agent_id="x1", text="done", status="ok"),
        PhaseStart(phase="complete"),
    ]
    app = SwarmApp(demo=False)
    async with app.run_test(size=(120, 30)) as pilot:
        for ev in events:
            app.router.dispatch(ev)  # type: ignore[union-attr]
        await pilot.pause(0.3)

        card = app.swarm_computer.grid.get_card("x1")
        assert card is not None
        assert card.working is False
        assert app.swarm_computer.memory._rows.get("result") is not None
        assert app.swarm_computer.header._completed == 1
