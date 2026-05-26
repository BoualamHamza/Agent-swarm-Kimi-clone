"""AgentStrip — single horizontal line of compact agent pills.

Each pill is one line:

    [● Hemingway] [● Barthes] [✓ Newton] [○ Shannon]

State is conveyed via CSS classes (-running, -done, -error) so the border /
background of each pill colour-codes the agent's status. Clicking a pill
focuses that agent in the main stage.
"""
from __future__ import annotations

from textual.containers import HorizontalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

from app.tui.avatars import Character


_STATUS_ICONS = {
    "idle":    "○",
    "running": "●",
    "done":    "✓",
    "error":   "✗",
}


class AgentPill(Static):
    """One agent on the strip. Reactive `status` drives icon + CSS class."""

    status: reactive[str] = reactive("idle")

    class Clicked(Message):
        """Bubbled when the user clicks the pill — strip handles focus."""

        def __init__(self, agent_id: str) -> None:
            super().__init__()
            self.agent_id = agent_id

    def __init__(self, agent_id: str, character: Character, role: str) -> None:
        super().__init__("", classes="agent-pill")
        self.agent_id = agent_id
        self.character = character
        self.role = role
        # Accent border so the user can match a pill to its log prefix colour.
        self.styles.border = ("solid", character.accent)
        self._refresh_label()

    def watch_status(self, status: str) -> None:
        for cls in ("-running", "-done", "-error"):
            self.remove_class(cls)
        if status == "running":
            self.add_class("-running")
        elif status == "done":
            self.add_class("-done")
        elif status == "error":
            self.add_class("-error")
        self._refresh_label()

    def _refresh_label(self) -> None:
        icon = _STATUS_ICONS.get(self.status, "○")
        self.update(f"🤖 {self.character.name} {icon}")

    def on_click(self) -> None:
        self.post_message(self.Clicked(self.agent_id))


class AgentStrip(HorizontalScroll):
    """Top-of-stage horizontal row of AgentPills.

    Scrolls horizontally so large swarms (the orchestrator may spawn up to 20
    agents) stay reachable without clipping.
    """

    def __init__(self) -> None:
        super().__init__(id="strip")
        self._pills: dict[str, AgentPill] = {}
        self._empty = Static(
            "[dim italic]Waiting for swarm…[/dim italic]",
            id="strip-empty",
        )

    def compose(self):
        yield self._empty

    def add_agent(
        self, agent_id: str, character: Character, role: str
    ) -> AgentPill:
        pill = AgentPill(agent_id, character, role)
        self._pills[agent_id] = pill
        # Hide the empty placeholder on first arrival.
        self._empty.display = False
        self.mount(pill)
        return pill

    def get_pill(self, agent_id: str) -> AgentPill | None:
        return self._pills.get(agent_id)
