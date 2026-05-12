"""SwarmEvent → widget dispatcher.

A single class consumes every SwarmEvent variant and pokes the right widgets.
Keeping the dispatch in one file means there's exactly one place to look when
a new event type is added in `app/state.py`.

Spawn staggering
----------------
The orchestrator returns all AgentSpec rows in a single batch, so the
underlying event stream emits `agent_spawned` events in rapid succession.
We pace them out visually with `_SPAWN_STAGGER` between reveals so the user
sees agents *arrive* one at a time. Events targeting an agent that hasn't
been revealed yet are buffered and replayed when the reveal fires.
"""
from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING, Any

from app.state import (
    AgentComplete,
    AgentHandedOff,
    AgentRunning,
    AgentSpawned,
    ArtifactEmitted,
    ErrorEvent,
    FinalResult,
    HandoffRequested,
    MemoryWrite,
    OrchestratorReasoning,
    PhaseStart,
    SwarmEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.tui.avatars import AvatarPool

if TYPE_CHECKING:
    from app.tui.main import SwarmApp


# Seconds between consecutive agent reveals during a burst.
_SPAWN_STAGGER = 0.6


class EventRouter:
    """Dispatches one SwarmEvent at a time to the live widget tree."""

    def __init__(self, app: SwarmApp) -> None:
        self.app = app
        self.pool = AvatarPool()
        # Track originator ids in order — used to pair handoff phase-3 spawns
        # with their phase-2 originator so we can draw the arrow.
        self._handoff_origins: list[str] = []
        # Staggered-spawn bookkeeping.
        self._revealed: set[str] = set()
        self._pending: dict[str, list[SwarmEvent]] = {}
        self._next_reveal_at: float = 0.0

    # ─── Entry point ────────────────────────────────────────────────────────

    def dispatch(self, ev: SwarmEvent) -> None:
        kind = getattr(ev, "type", "")
        handler = self._handlers.get(kind)
        if handler is None:
            return
        # Buffer agent-targeted events that arrive before the visual reveal.
        if kind != "agent_spawned":
            agent_id = getattr(ev, "agent_id", None)
            if agent_id is not None and agent_id not in self._revealed:
                self._pending.setdefault(agent_id, []).append(ev)
                return
        handler(self, ev)

    # ─── Individual handlers ────────────────────────────────────────────────

    def _on_phase_start(self, ev: PhaseStart) -> None:
        self.app.swarm_computer.header.set_phase(ev.phase)

    def _on_reasoning(self, ev: OrchestratorReasoning) -> None:
        self.app.chat_pane.set_thinking(ev.reasoning)

    def _on_spawned(self, ev: AgentSpawned) -> None:
        # Compute the visual reveal time so spawns trickle in.
        now = monotonic()
        target = max(now, self._next_reveal_at)
        delay = target - now
        self._next_reveal_at = target + _SPAWN_STAGGER
        # If the gap is essentially zero, just reveal synchronously to avoid
        # an unnecessary frame of latency.
        if delay <= 0.01:
            self._reveal_agent(ev)
        else:
            self.app.set_timer(delay, lambda: self._reveal_agent(ev))

    def _reveal_agent(self, ev: AgentSpawned) -> None:
        char = self.pool.assign(ev.spec.id)
        self.app.swarm_computer.grid.add_agent(ev.spec.id, char, ev.spec.role)
        self.app.swarm_computer.header.increment_spawned()
        self.app.chat_pane.roster.add_agent(
            ev.spec.id, char.name, ev.spec.role, ev.spec.task,
        )
        # Handoff arrow if this is a Phase-3 agent.
        if ev.is_handoff and self._handoff_origins:
            origin_id = self._handoff_origins.pop(0)
            self.app.swarm_computer.grid.draw_handoff(origin_id, ev.spec.id)
        # Drain any events that arrived for this agent before reveal.
        self._revealed.add(ev.spec.id)
        for buffered in self._pending.pop(ev.spec.id, []):
            self.dispatch(buffered)

    def _on_running(self, ev: AgentRunning) -> None:
        card = self.app.swarm_computer.grid.get_card(ev.agent_id)
        if card is not None:
            card.working = True
            card.set_status("●")
        row = self.app.chat_pane.roster.get_row(ev.agent_id)
        if row is not None:
            row.mark_running()

    def _on_tool_call(self, ev: ToolCallEvent) -> None:
        card = self.app.swarm_computer.grid.get_card(ev.agent_id)
        if card is not None:
            card.show_bubble(ev.name, _short_input(ev.input))
        row = self.app.chat_pane.roster.get_row(ev.agent_id)
        if row is not None:
            row.bump_progress()

    def _on_tool_result(self, ev: ToolResultEvent) -> None:
        # Bubble naturally times out — no-op unless we wanted to flag errors.
        return

    def _on_memory_write(self, ev: MemoryWrite) -> None:
        self.app.swarm_computer.memory.upsert(ev.key, ev.value)

    def _on_handoff_requested(self, ev: HandoffRequested) -> None:
        card = self.app.swarm_computer.grid.get_card(ev.agent_id)
        if card is not None:
            card.show_bubble("request_handoff", ev.handoff.to_role, ttl=2.4)

    def _on_complete(self, ev: AgentComplete) -> None:
        card = self.app.swarm_computer.grid.get_card(ev.agent_id)
        if card is not None:
            card.working = False
            card.set_status("✓" if ev.status == "ok" else "✗")
        row = self.app.chat_pane.roster.get_row(ev.agent_id)
        if row is not None:
            if ev.status == "ok":
                row.mark_complete()
            else:
                row.mark_error()
        self.app.swarm_computer.header.increment_completed()

    def _on_handed_off(self, ev: AgentHandedOff) -> None:
        card = self.app.swarm_computer.grid.get_card(ev.agent_id)
        if card is not None:
            card.working = False
            card.set_status("↦")
        row = self.app.chat_pane.roster.get_row(ev.agent_id)
        if row is not None:
            row.mark_handoff()
        self.app.swarm_computer.header.increment_completed()
        # Queue the originator for the next is_handoff=True spawn.
        self._handoff_origins.append(ev.agent_id)

    def _on_final(self, ev: FinalResult) -> None:
        self.app.chat_pane.set_answer(ev.text)
        # Clear the thinking line — the answer subsumes it.
        self.app.chat_pane.set_thinking("")

    def _on_artifact(self, ev: ArtifactEmitted) -> None:
        self.app.swarm_computer.artifacts_view.add(ev)
        # First artifact auto-switches to the artifacts tab so the user
        # immediately sees their deliverable land.
        if len(self.app.swarm_computer.artifacts_view._rows) == 1:
            self.app.swarm_computer.show_artifacts()

    def _on_error(self, ev: ErrorEvent) -> None:
        self.app.chat_pane.set_thinking(f"[b red]Error:[/b red] {ev.message}")

    _handlers: dict[str, Any] = {
        "phase_start":           _on_phase_start,
        "orchestrator_reasoning": _on_reasoning,
        "agent_spawned":         _on_spawned,
        "agent_running":         _on_running,
        "tool_call":             _on_tool_call,
        "tool_result":           _on_tool_result,
        "memory_write":          _on_memory_write,
        "handoff_requested":     _on_handoff_requested,
        "agent_complete":        _on_complete,
        "agent_handed_off":      _on_handed_off,
        "final_result":          _on_final,
        "artifact_emitted":      _on_artifact,
        "error":                 _on_error,
    }


def _short_input(d: dict[str, Any]) -> str:
    """Compact a tool input dict for the speech bubble (just one key value)."""
    if not d:
        return ""
    # Prefer common keys.
    for key in ("query", "expression", "key", "to_role", "code"):
        if key in d:
            val = str(d[key]).replace("\n", " ")
            return val[:24]
    # Fallback: first value.
    try:
        val = str(next(iter(d.values()))).replace("\n", " ")
        return val[:24]
    except StopIteration:
        return ""
