"""ChatPane — the left sidebar (30% width):

    ┌──────────────────────────┐
    │ Task: …                  │  ← TaskCard
    ├──────────────────────────┤
    │ Agent Roster · 4 tasks   │  ← TaskRoster (selectable)
    │ 01 Hemingway  ●  ▮▮▮░░  │
    │ 02 Barthes    ●  ▮▮░░░  │
    │ 03 Newton     ✓  ▮▮▮▮▮  │
    │ 04 Shannon    ○  ░░░░░  │
    ├──────────────────────────┤
    │ ▶ Final Answer (waiting…)│  ← FinalAnswerPreview (collapsible)
    └──────────────────────────┘
"""
from __future__ import annotations

from textual.containers import Container, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Markdown, Static


class TaskCard(Static):
    """Top card showing the current task."""

    def __init__(self) -> None:
        super().__init__(
            "[dim]No task yet. Type one below ↓[/dim]", id="task-card"
        )

    def set_task(self, task: str) -> None:
        self.update(f"[b]Task:[/b] {task}")


class AgentRosterRow(Static):
    """Per-agent roster card (2 lines). Click / arrow-select to focus the agent."""

    BAR_CELLS = 8
    ROLE_CHARS = 38
    TASK_CHARS = 48

    class Clicked(Message):
        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

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
        self._status = "○"
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
        self._status = "●"
        self.add_class("-running")
        self._refresh()

    def mark_complete(self) -> None:
        self._progress = self.BAR_CELLS
        self._status = "✓"
        self.remove_class("-running")
        self.add_class("-done")
        self._refresh()

    def mark_error(self) -> None:
        self._status = "✗"
        self.remove_class("-running")
        self.add_class("-error")
        self._refresh()

    def set_selected(self, selected: bool) -> None:
        self.set_class(selected, "-selected")

    # ─── Rendering ──────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        filled = "█" * self._progress
        empty = "░" * (self.BAR_CELLS - self._progress)
        bar = f"▸{filled}{empty}"
        role = _truncate(self._role, self.ROLE_CHARS) if self._role else ""
        task = _truncate(self._agent_task, self.TASK_CHARS) if self._agent_task else ""
        line1 = (
            f"[b]{self._index:02d}  {self._name}[/b]  {self._status}  "
            f"[dim]{role}[/dim]"
        )
        line2 = f"    [cyan]{bar}[/cyan]  [italic dim]{task}[/italic dim]"
        self.update(f"{line1}\n{line2}")

    def on_click(self) -> None:
        self.post_message(self.Clicked(self.agent_id))


def _truncate(text: str, n: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[: n - 1] + "…"


class TaskRoster(Container):
    """Container of AgentRosterRows. Title shows total count."""

    def __init__(self) -> None:
        super().__init__(id="task-roster")
        self._rows: dict[str, AgentRosterRow] = {}
        self._order: list[str] = []
        self._selected: str | None = None
        self._title = Static("[b]Agent Roster · 0 tasks[/b]", classes="roster-title")

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
        self._order.append(agent_id)
        self.mount(row)
        self._title.update(f"[b]Agent Roster · {len(self._rows)} tasks[/b]")
        return row

    def get_row(self, agent_id: str) -> AgentRosterRow | None:
        return self._rows.get(agent_id)

    # ─── Selection ─────────────────────────────────────────────────────────

    def select(self, agent_id: str | None) -> None:
        if self._selected is not None:
            row = self._rows.get(self._selected)
            if row is not None:
                row.set_selected(False)
        self._selected = agent_id
        if agent_id is not None:
            row = self._rows.get(agent_id)
            if row is not None:
                row.set_selected(True)

    def move_cursor(self, delta: int) -> str | None:
        """Move the selection up (delta=-1) or down (delta=+1). Returns new id."""
        if not self._order:
            return None
        if self._selected is None:
            target = 0 if delta >= 0 else len(self._order) - 1
        else:
            try:
                idx = self._order.index(self._selected)
            except ValueError:
                idx = 0
            target = max(0, min(len(self._order) - 1, idx + delta))
        new_id = self._order[target]
        self.select(new_id)
        return new_id


class FinalAnswerPreview(Vertical):
    """Collapsible final-answer pane anchored at the bottom of the sidebar."""

    expanded: reactive[bool] = reactive(False)
    has_content: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__(id="final-answer", classes="collapsed")
        self._title = Static(
            "[dim]▶ Final Answer (waiting…)[/dim]",
            id="final-title",
        )
        self._body = Markdown("", id="final-body")

    def compose(self):
        yield self._title
        yield self._body

    def on_mount(self) -> None:
        self._body.display = False

    # ─── State mutation ─────────────────────────────────────────────────────

    def set_content(self, text: str) -> None:
        self.has_content = bool(text)
        if text:
            self._body.update(text)
            self.expanded = True

    def toggle(self) -> None:
        if not self.has_content:
            return
        self.expanded = not self.expanded

    def watch_expanded(self, expanded: bool) -> None:
        self.set_class(not expanded, "collapsed")
        self._body.display = expanded
        self._refresh_title()

    def watch_has_content(self, _: bool) -> None:
        self._refresh_title()

    def _refresh_title(self) -> None:
        if not self.has_content:
            self._title.update("[dim]▶ Final Answer (waiting…)[/dim]")
            return
        arrow = "▼" if self.expanded else "▶"
        hint = "[dim](F to collapse)[/dim]" if self.expanded else "[dim](F to expand)[/dim]"
        self._title.update(f"[b green]{arrow} ✓ Final Answer[/b green]  {hint}")


class ChatPane(Container):
    """Left sidebar: task header, roster, collapsible final answer."""

    def __init__(self) -> None:
        super().__init__(id="chat-pane")
        self.task_card = TaskCard()
        self.thinking = Static("", id="thinking")
        self.roster = TaskRoster()
        self.final = FinalAnswerPreview()

    def compose(self):
        yield self.task_card
        yield self.thinking
        yield self.roster
        yield self.final

    def set_thinking(self, text: str) -> None:
        if not text:
            self.thinking.update("")
            return
        snippet = text.replace("\n", " ").strip()
        if len(snippet) > 240:
            snippet = snippet[:239] + "…"
        self.thinking.update(f"[dim italic]🧠 {snippet}[/dim italic]")

    def set_answer(self, text: str) -> None:
        self.final.set_content(text)
