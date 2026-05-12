"""SwarmComputer — the right pane.

Two tabbed views share this pane:
  * **Computer** — phase header, agent grid, shared-memory drawer
  * **Artifacts** — list of harvested deliverables with an inline preview

Tabs can be switched by clicking the tab header or via the app-level
keyboard bindings (``F1`` / ``F2``).
"""
from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static, TabbedContent, TabPane

from app.tui.widgets.agent_grid import AgentGrid
from app.tui.widgets.artifacts_view import ArtifactsView
from app.tui.widgets.memory_drawer import MemoryDrawer


_PHASE_LABEL = {
    "idle":          "idle",
    "orchestrating": "Orchestrating",
    "executing":     "Executing",
    "handoffs":      "Handoffs",
    "aggregating":   "Aggregating",
    "complete":      "Complete",
}

_ARTIFACTS_TAB_ID = "tab-artifacts"
_COMPUTER_TAB_ID = "tab-computer"


class ComputerHeader(Static):
    """``Swarm Computer · 4/6 · Phase: Executing`` header strip."""

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
    """Right pane — tabbed between the live compute view and the artifacts view."""

    def __init__(self) -> None:
        super().__init__(id="swarm-computer")
        self.header = ComputerHeader()
        self.grid = AgentGrid()
        self.memory = MemoryDrawer()
        self.artifacts_view = ArtifactsView()
        self._tabs = TabbedContent(id="computer-tabs")
        # Wire the count callback so the artifacts tab title stays in sync.
        self.artifacts_view.on_count_change = self._update_artifacts_tab_title

    def compose(self):
        # Header is rendered above the tabs so the phase indicator stays
        # visible no matter which tab is active.
        yield self.header
        with self._tabs:
            with TabPane("💻 Computer", id=_COMPUTER_TAB_ID):
                yield self.grid
                yield self.memory
            with TabPane("📦 Artifacts (0)", id=_ARTIFACTS_TAB_ID):
                yield self.artifacts_view

    # ─── Tab control ────────────────────────────────────────────────────────

    def show_artifacts(self) -> None:
        """Programmatically switch to the artifacts tab."""
        try:
            self._tabs.active = _ARTIFACTS_TAB_ID
        except Exception:
            pass

    def show_computer(self) -> None:
        """Programmatically switch back to the compute view."""
        try:
            self._tabs.active = _COMPUTER_TAB_ID
        except Exception:
            pass

    # ─── Internals ──────────────────────────────────────────────────────────

    def _update_artifacts_tab_title(self, count: int) -> None:
        try:
            tab = self._tabs.get_tab(_ARTIFACTS_TAB_ID)
        except Exception:
            return
        if count == 0:
            tab.label = "📦 Artifacts (0)"  # type: ignore[assignment]
        else:
            tab.label = f"[b green]📦 Artifacts ({count})[/b green]"  # type: ignore[assignment]
