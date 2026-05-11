"""SwarmComputer — the right pane: header with phase indicator, the AgentGrid,
and the MemoryDrawer beneath.
"""
from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static

from app.tui.widgets.agent_grid import AgentGrid
from app.tui.widgets.memory_drawer import MemoryDrawer


_PHASE_LABEL = {
    "idle":          "idle",
    "orchestrating": "Orchestrating",
    "executing":     "Executing",
    "handoffs":      "Handoffs",
    "aggregating":   "Aggregating",
    "complete":      "Complete",
}


class ComputerHeader(Static):
    """`Swarm Computer · 4/6 · Phase: Executing` header strip."""

    def __init__(self) -> None:
        super().__init__("", id="computer-header")
        self._phase = "idle"
        self._spawned = 0
        self._completed = 0
        self._refresh()

    def _refresh(self) -> None:
        phase = _PHASE_LABEL.get(self._phase, self._phase)
        self.update(
            f"  💻  Swarm Computer · [b]{self._completed}/{self._spawned}[/b]"
            f"  ·  Phase: [b]{phase}[/b]"
        )

    def set_phase(self, phase: str) -> None:
        self._phase = phase
        self._refresh()

    def increment_spawned(self) -> None:
        self._spawned += 1
        self._refresh()

    def increment_completed(self) -> None:
        self._completed += 1
        self._refresh()


class SwarmComputer(Container):
    """Right pane container — header, agent grid, memory drawer."""

    def __init__(self) -> None:
        super().__init__(id="swarm-computer")
        self.header = ComputerHeader()
        self.grid = AgentGrid()
        self.memory = MemoryDrawer()

    def compose(self):
        yield self.header
        yield self.grid
        yield self.memory
