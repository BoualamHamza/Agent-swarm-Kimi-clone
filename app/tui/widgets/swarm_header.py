"""SwarmHeader — top-of-screen status dashboard.

    🐝 Untitled Swarm  │  ● 2 running  ○ 1 queued  ✓ 1 done  │  Phase: Executing

Reactive properties bind to live state; the override of ``render()`` is called
on every refresh so just bump the counters and Textual repaints the line.
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


_PHASE_LABEL = {
    "idle":          "Idle",
    "orchestrating": "Orchestrating",
    "executing":     "Executing",
    "complete":      "Complete",
}


class SwarmHeader(Static):
    swarm_name: reactive[str] = reactive("Untitled Swarm")
    running: reactive[int] = reactive(0)
    queued: reactive[int] = reactive(0)
    done: reactive[int] = reactive(0)
    phase: reactive[str] = reactive("idle")

    def __init__(self) -> None:
        super().__init__(id="swarm-header")

    # ─── Mutators called by EventRouter ─────────────────────────────────────
    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self._sync_class()

    def increment_queued(self) -> None:
        self.queued += 1

    def mark_running(self) -> None:
        if self.queued > 0:
            self.queued -= 1
        self.running += 1

    def increment_completed(self) -> None:
        if self.running > 0:
            self.running -= 1
        self.done += 1

    # ─── Rendering ──────────────────────────────────────────────────────────
    def _sync_class(self) -> None:
        if self.phase == "complete":
            self.set_class(True, "-complete")
            self.set_class(False, "-running")
        elif self.phase == "executing":
            self.set_class(True, "-running")
            self.set_class(False, "-complete")
        else:
            self.set_class(False, "-running")
            self.set_class(False, "-complete")

    def render(self) -> str:
        phase = _PHASE_LABEL.get(self.phase, self.phase.title())
        return (
            f"🐝 [b]{self.swarm_name}[/b]   │   "
            f"[#ffcc55]●[/#ffcc55] {self.running} running   "
            f"[dim]○[/dim] {self.queued} queued   "
            f"[#7eebdc]✓[/#7eebdc] {self.done} done   │   "
            f"Phase: [b]{phase}[/b]"
        )
