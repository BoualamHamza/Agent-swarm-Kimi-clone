"""AgentGrid — the floating grid of AgentCards inside the Swarm Computer pane.

Handoff arrows are rendered as labels on both the originator and the new agent
(`↦ Tesla` on the source, `← Watt` on the target). This works robustly under
layout reflow without needing a custom canvas overlay.
"""
from __future__ import annotations

from textual.containers import Container

from app.tui.avatars import Character
from app.tui.widgets.agent_card import AgentCard


class AgentGrid(Container):
    """A grid that fills with AgentCards in row-major order."""

    def __init__(self) -> None:
        super().__init__(id="agent-grid")
        self._cards: dict[str, AgentCard] = {}

    def add_agent(self, agent_id: str, character: Character, role: str) -> AgentCard:
        card = AgentCard(agent_id, character, role)
        self._cards[agent_id] = card
        self.mount(card)
        return card

    def get_card(self, agent_id: str) -> AgentCard | None:
        return self._cards.get(agent_id)

    # ─── Handoff visualization ──────────────────────────────────────────────

    def draw_handoff(self, from_id: str, to_id: str) -> None:
        """Annotate the originator and target cards with an arrow label."""
        src = self.get_card(from_id)
        dst = self.get_card(to_id)
        if src is not None and dst is not None:
            src.set_role_label(f"↦ {dst.character.name}")
            dst.set_role_label(f"← {src.character.name}")
