"""AgentCard — one agent's pixel portrait, name, role, status dot, speech bubble.

Layout (vertical):
    ┌─────────────┐
    │ 🔍 web_…    │  ← bubble slot (blank unless a tool call is active)
    │ ▄▀▀▀▄        │
    │ █◕ ◕█        │  ← portrait (4 rows from Character.portrait)
    │ █ ─ █        │
    │ ▝▄▄▄▘        │
    │ Watt    ●    │  ← name + status dot
    │ Analyst      │  ← role / handoff label
    └─────────────┘

The card adds the `-working` CSS class while the agent is in progress;
styles.tcss uses that to switch the border color into an accent glow.
"""
from __future__ import annotations

from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Static

from app.tui.avatars import Character


# ─── Tool → icon map (used by SpeechBubble for compact tool-call display) ────

TOOL_ICONS: dict[str, str] = {
    "calculate":              "🧮",
    "get_current_date":       "📅",
    "write_to_shared_memory": "💾",
    "read_shared_memory":     "📖",
    "request_handoff":        "🔄",
    "web_search":             "🔍",
    "run_python":             "🐍",
}


class AgentCard(Container):
    """One agent's portrait card. Reactive `working` toggles the glow class."""

    working: reactive[bool] = reactive(False)

    def __init__(self, agent_id: str, character: Character, role: str) -> None:
        super().__init__(classes="agent-card")
        self.agent_id = agent_id
        self.character = character
        self.role = role
        self._status_mark = "◌"  # idle
        # Style hook for per-character accent color.
        self.styles.border = ("round", character.accent)

    def compose(self):
        yield Static("", id="bubble", classes="bubble -hidden")
        yield Static(self.character.portrait, id="portrait")
        yield Static(self._name_text(), id="name")
        yield Static(self._role_text(), id="role")

    # ─── State updates ──────────────────────────────────────────────────────

    def watch_working(self, working: bool) -> None:
        self.set_class(working, "-working")

    def set_status(self, mark: str) -> None:
        """One of: ◌ idle, ● running, ✓ done, ✗ error, ↦ handed off."""
        self._status_mark = mark
        self._safe_update("#name", self._name_text())

    def show_bubble(self, tool_name: str, input_snippet: str = "", ttl: float = 1.6) -> None:
        icon = TOOL_ICONS.get(tool_name, "•")
        text = f"{icon} {tool_name}"
        if input_snippet:
            text = f"{text} {input_snippet}"
        if not self.is_mounted:
            self.call_after_refresh(self.show_bubble, tool_name, input_snippet, ttl)
            return
        try:
            bubble = self.query_one("#bubble", Static)
        except Exception:
            return
        bubble.update(text[:14])
        bubble.remove_class("-hidden")
        self.set_timer(ttl, lambda: bubble.add_class("-hidden"))

    def set_role_label(self, text: str) -> None:
        """Override the role line (used for handoff arrows: '↦ Tesla')."""
        self.role = text
        self._safe_update("#role", self._role_text())

    # ─── Internals ──────────────────────────────────────────────────────────

    def _safe_update(self, selector: str, text: str) -> None:
        """Update a child Static, deferring if the card hasn't composed yet."""
        if not self.is_mounted:
            self.call_after_refresh(self._safe_update, selector, text)
            return
        try:
            self.query_one(selector, Static).update(text)
        except Exception:
            # Child not yet in the DOM despite is_mounted — try once more later.
            self.call_after_refresh(self._safe_update, selector, text)

    # ─── Rendering helpers ──────────────────────────────────────────────────

    def _name_text(self) -> str:
        return f"[b]{self.character.name}[/b]  {self._status_mark}"

    def _role_text(self) -> str:
        return f"[dim]{self.role[:11]}[/dim]"
