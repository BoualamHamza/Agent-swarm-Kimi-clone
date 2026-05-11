"""MemoryDrawer — live shared-memory key→value list below the agent grid.

Each `memory_write` upserts a row; new/updated rows briefly highlight via the
`-flash` CSS class (removed after a short delay).
"""
from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static


class MemoryDrawer(Container):
    """Live key→value display of shared memory."""

    def __init__(self) -> None:
        super().__init__(id="memory-drawer")
        self._rows: dict[str, Static] = {}
        self._title = Static("▾ Memory · 0 keys", classes="mem-title")

    def compose(self):
        yield self._title

    def upsert(self, key: str, value: str) -> None:
        snippet = value.replace("\n", " ").strip()
        if len(snippet) > 48:
            snippet = snippet[:47] + "…"
        text = f"[b][{key}][/b] {snippet}"
        row = self._rows.get(key)
        if row is None:
            row = Static(text, classes="mem-row")
            self._rows[key] = row
            self.mount(row)
        else:
            row.update(text)
        row.add_class("-flash")
        self.set_timer(1.2, lambda r=row: r.remove_class("-flash"))
        self._title.update(f"▾ Memory · {len(self._rows)} keys")
