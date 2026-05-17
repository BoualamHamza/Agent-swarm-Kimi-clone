"""MemoryDrawer — collapsible shared-memory drawer at the bottom of the stage.

Collapsed (default):
    ▶ Memory · 3 keys · 1.2 KB

Expanded (press M to toggle):
    ▼ Memory · 3 keys · 1.2 KB
        [arithmetic_problems] Q1: A bakery sold 24 loaves on Monday…
        [geometry_problems]   Q1: A circular garden has radius 7m…
        [algebra_problems]    Q1: Solve 2x + 3 = 11. (Answer: x=4)

Each `memory_write` upserts a row; new/updated rows briefly flash via the
`-flash` CSS class.
"""
from __future__ import annotations

from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Static


def _human_size(values: dict[str, str]) -> str:
    n = sum(len(k) + len(v) for k, v in values.items())
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KB"


class MemoryDrawer(Container):
    """Live key→value display of shared memory, collapsible to a single line."""

    collapsed: reactive[bool] = reactive(True)

    def __init__(self) -> None:
        super().__init__(id="memory-drawer", classes="collapsed")
        self._rows: dict[str, Static] = {}
        self._values: dict[str, str] = {}
        self._title = Static("", classes="mem-title")
        self._refresh_title()

    def compose(self):
        yield self._title

    # ─── Mutators ───────────────────────────────────────────────────────────

    def upsert(self, key: str, value: str) -> None:
        self._values[key] = value
        snippet = value.replace("\n", " ").strip()
        if len(snippet) > 56:
            snippet = snippet[:55] + "…"
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
        # Rows visibility follows collapsed state.
        row.display = not self.collapsed
        self._refresh_title()

    def toggle(self) -> None:
        self.collapsed = not self.collapsed

    # ─── Reactivity ────────────────────────────────────────────────────────

    def watch_collapsed(self, collapsed: bool) -> None:
        self.set_class(collapsed, "collapsed")
        for row in self._rows.values():
            row.display = not collapsed
        self._refresh_title()

    # ─── Rendering ─────────────────────────────────────────────────────────

    def _refresh_title(self) -> None:
        arrow = "▶" if self.collapsed else "▼"
        size = _human_size(self._values) if self._values else "0 B"
        hint = "[dim](M to expand)[/dim]" if self.collapsed else "[dim](M to collapse)[/dim]"
        self._title.update(
            f"{arrow} [b]Memory[/b] · {len(self._values)} keys · {size}  {hint}"
        )
