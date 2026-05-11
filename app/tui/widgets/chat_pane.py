"""ChatPane — the left pane: task card, orchestrator thinking, per-agent
progress roster, and the final answer.
"""
from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static


class TaskCard(Static):
    """Top card showing the current task."""

    def __init__(self) -> None:
        super().__init__("[dim]No task yet. Type one below ↓[/dim]", id="task-card")

    def set_task(self, task: str) -> None:
        self.update(f"[b]Task:[/b] {task}")


class AgentRosterRow(Static):
    """Per-agent roster card (2 lines):

        01 Watt   ●  market sizing and competitive landscape
           ▸████░░░░  Analyze TAM, SAM, SOM and key competitors…
    """

    BAR_CELLS = 8
    ROLE_CHARS = 38
    TASK_CHARS = 48

    def __init__(
        self,
        agent_id: str,
        name: str,
        index: int,
        role: str = "",
        task: str = "",
    ) -> None:
        super().__init__(classes="roster-row")
        self.agent_id = agent_id
        self._index = index
        self._progress = 0
        self._status = "·"
        self._name = name
        self._role = role
        self._agent_task = task
        self._refresh()

    # ─── Mutators ───────────────────────────────────────────────────────────

    def bump_progress(self) -> None:
        if self._progress < self.BAR_CELLS:
            self._progress += 1
            self._refresh()

    def mark_running(self) -> None:
        self._status = "⚡"
        self._refresh()

    def mark_complete(self) -> None:
        self._progress = self.BAR_CELLS
        self._status = "✓"
        self._refresh()

    def mark_error(self) -> None:
        self._status = "✗"
        self._refresh()

    def mark_handoff(self) -> None:
        self._status = "↦"
        self._refresh()

    # ─── Rendering ──────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        filled = "█" * self._progress
        empty = "░" * (self.BAR_CELLS - self._progress)
        bar = f"▸{filled}{empty}"
        role = _truncate(self._role, self.ROLE_CHARS) if self._role else ""
        task = _truncate(self._agent_task, self.TASK_CHARS) if self._agent_task else ""
        line1 = f"[b]{self._index:02d}  {self._name}[/b]  {self._status}  [dim]{role}[/dim]"
        line2 = f"    [cyan]{bar}[/cyan]  [italic dim]{task}[/italic dim]"
        self.update(f"{line1}\n{line2}")


def _truncate(text: str, n: int) -> str:
    """Single-line truncate with ellipsis."""
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[: n - 1] + "…"


class TaskRoster(Container):
    """Container of AgentRosterRows. Title shows total count."""

    def __init__(self) -> None:
        super().__init__(id="task-roster")
        self._rows: dict[str, AgentRosterRow] = {}
        self._title = Static("[b]Agent Swarm · 0 tasks[/b]", classes="roster-title")

    def compose(self):
        yield self._title

    def add_agent(
        self,
        agent_id: str,
        name: str,
        role: str = "",
        task: str = "",
    ) -> AgentRosterRow:
        index = len(self._rows) + 1
        row = AgentRosterRow(agent_id, name, index, role=role, task=task)
        self._rows[agent_id] = row
        self.mount(row)
        self._title.update(f"[b]Agent Swarm · {len(self._rows)} tasks[/b]")
        return row

    def get_row(self, agent_id: str) -> AgentRosterRow | None:
        return self._rows.get(agent_id)


class ChatPane(Container):
    """The left pane: task header, thinking ticker, roster, final answer."""

    def __init__(self) -> None:
        super().__init__(id="chat-pane")
        self.task_card = TaskCard()
        self.thinking = Static("", id="thinking")
        self.roster = TaskRoster()
        self.answer = Static("", id="answer")

    def compose(self):
        yield self.task_card
        yield self.thinking
        yield self.roster
        yield self.answer

    def set_thinking(self, text: str) -> None:
        if not text:
            self.thinking.update("")
            return
        # Truncate long reasoning so it doesn't blow up the pane.
        snippet = text.replace("\n", " ").strip()
        if len(snippet) > 240:
            snippet = snippet[:239] + "…"
        self.thinking.update(f"[dim italic]🧠 {snippet}[/dim italic]")

    def set_answer(self, text: str) -> None:
        self.answer.update(f"[b green]✓ Final answer[/b green]\n\n{text}")
