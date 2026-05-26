"""AgentDetailView — per-agent focus mode shown inside the main-stage ContentSwitcher.

Layout (vertical):

    ┌─ detail-header ───────────────────────────────────────┐
    │ 🤖 Hemingway  ●  Status: Running  Steps: 12/20  Runtime: 00:14 │
    ├─ detail-logs (RichLog) ───────────────────────────────┤
    │ [Hemingway] starting…                                 │
    │ [Hemingway] tool: web_search(...)                     │
    │ [Hemingway] write_file(report.md)                     │
    ├─ detail-tools ────────────────────────────────────────┤
    │ 1. web_search(query='market sizing')          ✓       │
    │ 2. write_file(report.md)                      ✓       │
    │ 3. calculate(2+2)                             ✗ error │
    └───────────────────────────────────────────────────────┘

Owned by SwarmComputer; populated from `app.focused_agent` (set via roster
Enter or pill click).
"""
from __future__ import annotations

from time import monotonic

from textual.containers import Vertical
from textual.widgets import RichLog, Static

from app.tui.avatars import Character


class _AgentTrace:
    """Per-agent rolling buffer used to populate the detail view on focus."""

    def __init__(self) -> None:
        self.started_at: float | None = None
        self.status: str = "idle"
        self.steps: int = 0
        self.steps_cap: int = 20  # cosmetic ceiling for the stats line
        self.log_lines: list[str] = []
        self.tool_calls: list[tuple[str, str, str]] = []  # (name, snippet, outcome)


class AgentDetailView(Vertical):
    """The 'agent-detail' tab in the main stage."""

    def __init__(self) -> None:
        super().__init__(id="agent-detail")
        self._header = Static("", id="detail-header")
        self._logs = RichLog(id="detail-logs", highlight=True, wrap=False, markup=True)
        self._tools = Static("", id="detail-tools")
        self._traces: dict[str, _AgentTrace] = {}
        self._characters: dict[str, Character] = {}
        self._roles: dict[str, str] = {}
        self._current: str | None = None

    def compose(self):
        yield self._header
        yield self._logs
        yield self._tools

    # ─── Tracking (called by EventRouter on every relevant event) ───────────

    def register(self, agent_id: str, character: Character, role: str) -> None:
        self._traces.setdefault(agent_id, _AgentTrace())
        self._characters[agent_id] = character
        self._roles[agent_id] = role

    def trace_running(self, agent_id: str) -> None:
        t = self._traces.setdefault(agent_id, _AgentTrace())
        t.status = "running"
        t.started_at = monotonic()
        self._append_log(agent_id, "starting…")
        self._refresh_if_focused(agent_id)

    def trace_tool_call(self, agent_id: str, name: str, snippet: str) -> None:
        t = self._traces.setdefault(agent_id, _AgentTrace())
        t.steps += 1
        if t.steps > t.steps_cap:
            t.steps_cap = t.steps + 4
        t.tool_calls.append((name, snippet, "…"))
        self._append_log(agent_id, f"→ {name}({snippet})")
        self._refresh_if_focused(agent_id)

    def trace_tool_result(self, agent_id: str, name: str, outcome: str) -> None:
        t = self._traces.get(agent_id)
        if t and t.tool_calls:
            last_name, last_snip, _ = t.tool_calls[-1]
            if last_name == name:
                t.tool_calls[-1] = (last_name, last_snip, outcome)
        self._refresh_if_focused(agent_id)

    def trace_complete(self, agent_id: str, status: str) -> None:
        t = self._traces.setdefault(agent_id, _AgentTrace())
        t.status = "done" if status == "ok" else "error"
        self._append_log(agent_id, f"finished ({status})")
        self._refresh_if_focused(agent_id)

    # ─── Focus control ──────────────────────────────────────────────────────

    def focus_agent(self, agent_id: str) -> None:
        if agent_id not in self._traces:
            return
        self._current = agent_id
        self._render_header()
        self._render_tools()
        # Replay this agent's full log into the RichLog.
        self._logs.clear()
        for line in self._traces[agent_id].log_lines:
            self._logs.write(line)

    def unfocus(self) -> None:
        self._current = None

    # ─── Internals ──────────────────────────────────────────────────────────

    def _append_log(self, agent_id: str, msg: str) -> None:
        char = self._characters.get(agent_id)
        prefix = f"[{char.name}]" if char else f"[{agent_id}]"
        colour = char.accent if char else "white"
        self._traces[agent_id].log_lines.append(f"[{colour}]{prefix}[/{colour}] {msg}")

    def _refresh_if_focused(self, agent_id: str) -> None:
        if self._current == agent_id:
            self._render_header()
            self._render_tools()
            line = self._traces[agent_id].log_lines[-1] if self._traces[agent_id].log_lines else ""
            if line:
                self._logs.write(line)

    def _render_header(self) -> None:
        if self._current is None:
            self._header.update("")
            return
        agent_id = self._current
        t = self._traces[agent_id]
        char = self._characters.get(agent_id)
        role = self._roles.get(agent_id, "")
        name = char.name if char else agent_id
        color = char.accent if char else "white"
        status_icon = {
            "running": "[#ffcc55]●[/#ffcc55] Running",
            "done":    "[#7eebdc]✓[/#7eebdc] Done",
            "error":   "[red]✗[/red] Error",
            "idle":    "[dim]○ Idle[/dim]",
        }.get(t.status, "○ Idle")
        runtime = self._runtime(t)
        self._header.update(
            f"[{color}]🤖 [b]{name}[/b][/{color}]  [dim]· {role}[/dim]\n"
            f"Status: {status_icon}   │   "
            f"Steps: [b]{t.steps}/{t.steps_cap}[/b]   │   "
            f"Runtime: [b]{runtime}[/b]"
        )

    def _render_tools(self) -> None:
        if self._current is None:
            self._tools.update("")
            return
        t = self._traces[self._current]
        if not t.tool_calls:
            self._tools.update("[dim italic]No tool calls yet.[/dim italic]")
            return
        lines = []
        for i, (name, snippet, outcome) in enumerate(t.tool_calls, 1):
            mark = "✓" if outcome and outcome not in {"…", "error"} else ("…" if outcome == "…" else "[red]✗[/red]")
            arg = f" [dim]{snippet}[/dim]" if snippet else ""
            lines.append(f"  {i:2d}. [b]{name}[/b]{arg}   {mark}")
        self._tools.update("\n".join(lines))

    def _runtime(self, t: _AgentTrace) -> str:
        if t.started_at is None:
            return "00:00"
        secs = int(monotonic() - t.started_at)
        return f"{secs // 60:02d}:{secs % 60:02d}"
