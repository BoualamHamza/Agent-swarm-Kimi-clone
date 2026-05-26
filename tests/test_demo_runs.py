"""Smoke test the scripted demo end-to-end: every event drains, final state is
reached, no exceptions surface from the TUI router.
"""
from __future__ import annotations

import pytest

from app.tui.main import SwarmApp


@pytest.mark.asyncio
async def test_demo_runs_to_completion():
    app = SwarmApp(demo=True)
    async with app.run_test(size=(160, 44)) as pilot:
        # Demo runs ~28s; give it 35s to settle.
        await pilot.pause(35.0)

    header = app.swarm_header
    assert header.phase == "complete"
    assert header.running + header.queued + header.done == 5
    assert header.done == 5
    assert set(app.swarm_computer.strip._pills.keys()) == {"w1", "w2", "w3", "w4", "w5"}
    assert set(app.swarm_computer.memory._rows.keys()) == {
        "arithmetic_problems", "algebra_problems", "geometry_problems", "calculus_problem",
    }
    assert set(app.chat_pane.roster._rows.keys()) == {"w1", "w2", "w3", "w4", "w5"}
    # Demo emits two scripted artifacts at the end of the run; they're
    # surfaced in the right-pane Artifacts tab.
    view = app.swarm_computer.artifacts_view
    assert len(view._rows) == 2
    titles = {ev.title for ev in view._rows}
    assert titles == {"benchmark", "summary"}
    # After artifacts arrive the right pane auto-switches to the artifacts tab.
    assert app.swarm_computer._switcher.current == "artifacts"
