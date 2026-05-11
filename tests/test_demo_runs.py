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

    header = app.swarm_computer.header
    assert header._phase == "complete"
    assert header._spawned == 5            # 4 phase-2 + 1 phase-3 handoff
    assert header._completed == 5
    assert set(app.swarm_computer.grid._cards.keys()) == {"a1", "a2", "a3", "a4", "h1"}
    assert set(app.swarm_computer.memory._rows.keys()) == {
        "arithmetic_problems", "algebra_problems", "geometry_problems", "calculus_problem",
    }
    assert set(app.chat_pane.roster._rows.keys()) == {"a1", "a2", "a3", "a4", "h1"}
    # The handoff label was applied to the originator (a2) — it should display
    # an arrow to the handoff target's name.
    src_card = app.swarm_computer.grid.get_card("a2")
    assert src_card is not None
    assert src_card.role.startswith("↦")
