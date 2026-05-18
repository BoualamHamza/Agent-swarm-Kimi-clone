"""SwarmEvent → widget dispatcher.

A single class consumes every SwarmEvent variant and pokes the right widgets.
Keeping the dispatch in one file means there's exactly one place to look when
a new event type is added in ``app/state.py``.

Spawn staggering
----------------
The orchestrator returns all AgentSpec rows in a single batch, so the
underlying event stream emits ``agent_spawned`` events in rapid succession.
We pace them out visually with ``_SPAWN_STAGGER`` between reveals so the user
sees agents arrive one at a time. Events targeting an agent that hasn't been
revealed yet are buffered and replayed when the reveal fires.
"""
from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING, Any

from app.state import (
    AgentComplete,
    AgentRunning,
    AgentSpawned,
    ArtifactEmitted,
    ErrorEvent,
    FinalResult,
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


_SPAWN_STAGGER = 0.6


class EventRouter:
    """Dispatches one SwarmEvent at a time to the live widget tree."""

    def __init__(self, app: SwarmApp) -> None:
        self.app = app
        self.pool = AvatarPool()
        self._revealed: set[str] = set()
        self._pending: dict[str, list[SwarmEvent]] = {}
        self._next_reveal_at: float = 0.0

    # ─── Entry point ────────────────────────────────────────────────────────

    def dispatch(self, ev: SwarmEvent) -> None:
        kind = getattr(ev, "type", "")
        handler = self._handlers.get(kind)
        if handler is None:
            return
        if kind != "agent_spawned":
            agent_id = getattr(ev, "agent_id", None)
            if agent_id is not None and agent_id not in self._revealed:
                self._pending.setdefault(agent_id, []).append(ev)
                return
        handler(self, ev)

    # ─── Convenience: agent-coloured log line ───────────────────────────────

    def _log_line(self, agent_id: str | None, text: str) -> None:
        sc = self.app.swarm_computer
        if agent_id is None:
            sc.logs.write(f"[dim]{text}[/dim]")
            return
        char = self.pool.lookup(agent_id)
        if char is None:
            sc.logs.write(f"[{agent_id}] {text}")
            return
        sc.logs.write(f"[{char.accent}]\\[{char.name}][/{char.accent}] {text}")

    # ─── Handlers ──────────────────────────────────────────────────────────

    def _on_phase_start(self, ev: PhaseStart) -> None:
        self.app.swarm_header.set_phase(ev.phase)
        if ev.phase == "complete":
            self._log_line(None, "── swarm complete ──")
            try:
                self.app.notify("Swarm complete", title="Phase", timeout=3)
            except Exception:
                pass
        else:
            self._log_line(None, f"── phase: {ev.phase} ──")

    def _on_reasoning(self, ev: OrchestratorReasoning) -> None:
        self.app.chat_pane.set_thinking(ev.reasoning)
        self._log_line(None, f"orchestrator: {ev.reasoning}")

    def _on_spawned(self, ev: AgentSpawned) -> None:
        # Track header `queued` immediately so the dashboard updates before
        # the visual stagger reveals the pill.
        self.app.swarm_header.increment_queued()
        now = monotonic()
        target = max(now, self._next_reveal_at)
        delay = target - now
        self._next_reveal_at = target + _SPAWN_STAGGER
        if delay <= 0.01:
            self._reveal_agent(ev)
        else:
            self.app.set_timer(delay, lambda: self._reveal_agent(ev))

    def _reveal_agent(self, ev: AgentSpawned) -> None:
        char = self.pool.assign(ev.spec.id)
        sc = self.app.swarm_computer
        sc.strip.add_agent(ev.spec.id, char, ev.spec.role)
        sc.agent_detail.register(ev.spec.id, char, ev.spec.role)
        self.app.chat_pane.roster.add_agent(
            ev.spec.id, char.name, ev.spec.role, ev.spec.task,
        )
        self._revealed.add(ev.spec.id)
        self._log_line(ev.spec.id, f"spawned · {ev.spec.role}")
        for buffered in self._pending.pop(ev.spec.id, []):
            self.dispatch(buffered)

    def _on_running(self, ev: AgentRunning) -> None:
        pill = self.app.swarm_computer.strip.get_pill(ev.agent_id)
        if pill is not None:
            pill.status = "running"
        row = self.app.chat_pane.roster.get_row(ev.agent_id)
        if row is not None:
            row.mark_running()
        self.app.swarm_header.mark_running()
        self.app.swarm_computer.agent_detail.trace_running(ev.agent_id)
        self._log_line(ev.agent_id, "running")

    def _on_tool_call(self, ev: ToolCallEvent) -> None:
        snippet = _short_input(ev.input)
        row = self.app.chat_pane.roster.get_row(ev.agent_id)
        if row is not None:
            row.bump_progress()
        self.app.swarm_computer.agent_detail.trace_tool_call(
            ev.agent_id, ev.name, snippet
        )
        suffix = f" {snippet}" if snippet else ""
        self._log_line(ev.agent_id, f"→ {ev.name}{suffix}")

    def _on_tool_result(self, ev: ToolResultEvent) -> None:
        # Truncate the tool result so RichLog doesn't get a 4KB blob per line.
        snippet = (ev.result or "").replace("\n", " ⏎ ")
        if len(snippet) > 120:
            snippet = snippet[:119] + "…"
        self.app.swarm_computer.agent_detail.trace_tool_result(
            ev.agent_id, ev.name, snippet or "ok"
        )
        self._log_line(ev.agent_id, f"  ← {ev.name}: {snippet}")

    def _on_memory_write(self, ev: MemoryWrite) -> None:
        self.app.swarm_computer.memory.upsert(ev.key, ev.value)
        self._log_line(ev.agent_id, f"memory[{ev.key}] ← {ev.value[:40]}")

    def _on_complete(self, ev: AgentComplete) -> None:
        pill = self.app.swarm_computer.strip.get_pill(ev.agent_id)
        if pill is not None:
            pill.status = "done" if ev.status == "ok" else "error"
        row = self.app.chat_pane.roster.get_row(ev.agent_id)
        if row is not None:
            if ev.status == "ok":
                row.mark_complete()
            else:
                row.mark_error()
        self.app.swarm_header.increment_completed()
        self.app.swarm_computer.agent_detail.trace_complete(ev.agent_id, ev.status)
        name = self.pool.lookup(ev.agent_id)
        if name is not None:
            try:
                self.app.notify(f"{name.name} finished", title="Agent", timeout=2)
            except Exception:
                pass
        self._log_line(ev.agent_id, f"complete · {ev.status}")

    def _on_final(self, ev: FinalResult) -> None:
        self.app.chat_pane.set_answer(ev.text)
        self.app.chat_pane.set_thinking("")
        # Promote the final answer to the Preview tab so it gets the big space.
        try:
            self.app.swarm_computer.preview.update(ev.text)
        except Exception:
            pass
        self._log_line(None, "final answer ready")

    def _on_artifact(self, ev: ArtifactEmitted) -> None:
        sc = self.app.swarm_computer
        sc.artifacts_view.add(ev)
        if len(sc.artifacts_view._rows) == 1:
            sc.show_artifacts()
        self._log_line(None, f"artifact · {ev.title} ({ev.mime_type})")

    def _on_error(self, ev: ErrorEvent) -> None:
        self.app.chat_pane.set_thinking(f"[b red]Error:[/b red] {ev.message}")
        self._log_line(None, f"[red]error: {ev.message}[/red]")

    _handlers: dict[str, Any] = {
        "phase_start":           _on_phase_start,
        "orchestrator_reasoning": _on_reasoning,
        "agent_spawned":         _on_spawned,
        "agent_running":         _on_running,
        "tool_call":             _on_tool_call,
        "tool_result":           _on_tool_result,
        "memory_write":          _on_memory_write,
        "agent_complete":        _on_complete,
        "final_result":          _on_final,
        "artifact_emitted":      _on_artifact,
        "error":                 _on_error,
    }


def _short_input(d: dict[str, Any]) -> str:
    """Compact a tool input dict for the log line / agent detail."""
    if not d:
        return ""
    for key in ("query", "expression", "key", "to_role", "code", "path"):
        if key in d:
            val = str(d[key]).replace("\n", " ")
            return val[:48]
    try:
        val = str(next(iter(d.values()))).replace("\n", " ")
        return val[:48]
    except StopIteration:
        return ""
