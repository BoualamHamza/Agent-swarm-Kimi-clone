"""ArtifactsView — split-pane view of the run's artifacts.

Layout:
    ┌─ ArtifactList ────────────┬─ ArtifactPreview ──────────┐
    │ ▸ 🖼️ chart.png  1.2 KB    │ chart.png                  │
    │   📊 report.csv  842 B    │ image/png · 1.2 KB         │
    │   📕 paper.pdf   8 MB     │ ─────────────────────────  │
    │                           │ (binary preview not        │
    │                           │  supported — open from     │
    │                           │  /local/path/chart.png)    │
    └───────────────────────────┴────────────────────────────┘

Selecting a row from the list shows that artifact in the right pane.
Text-like artifacts (text/*, application/json) are rendered inline;
binary artifacts show metadata and the local path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Label, ListItem, ListView, Static

from app.state import ArtifactEmitted


# ─── Icon + helper utilities ────────────────────────────────────────────────


_MIME_ICONS: list[tuple[str, str]] = [
    ("image/", "🖼️"),
    ("text/csv", "📊"),
    ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "📊"),
    ("application/pdf", "📕"),
    ("application/json", "🧾"),
    ("text/markdown", "📝"),
    ("text/", "📄"),
]


def icon_for(mime_type: str) -> str:
    for needle, icon in _MIME_ICONS:
        if needle in mime_type:
            return icon
    return "📎"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    size: float = float(n)
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


def filename(ev: ArtifactEmitted) -> str:
    """Resolve the canonical filename (title + extension) from sandbox path."""
    base = ev.sandbox_path.rsplit("/", 1)[-1]
    return base or ev.title


def _is_text_mime(mime: str) -> bool:
    return (
        mime.startswith("text/")
        or mime in {"application/json", "application/xml", "application/javascript"}
        or mime.endswith("+json")
        or mime.endswith("+xml")
    )


# ─── List items ─────────────────────────────────────────────────────────────


class ArtifactListItem(ListItem):
    """One artifact entry in the left list. Renders as a single line."""

    def __init__(self, ev: ArtifactEmitted) -> None:
        self.ev = ev
        label = (
            f"{icon_for(ev.mime_type)} [b]{filename(ev)}[/b]   "
            f"[dim]{human_size(ev.size_bytes)}[/dim]"
        )
        super().__init__(Label(label), classes="artifact-list-item")


# ─── Preview pane ───────────────────────────────────────────────────────────


_TEXT_PREVIEW_BYTES = 64 * 1024  # cap at 64 KB so we don't choke on huge logs


class ArtifactPreview(VerticalScroll):
    """Right side of the view — content or metadata of the selected artifact."""

    def __init__(self) -> None:
        super().__init__(id="artifact-preview")
        self._placeholder = Static(
            "[dim]Select an artifact from the list to preview it here.[/dim]",
            id="artifact-preview-placeholder",
        )
        self._header = Static("", id="artifact-preview-header", classes="-hidden")
        self._body = Static("", id="artifact-preview-body", classes="-hidden")

    def compose(self):
        yield self._placeholder
        yield self._header
        yield self._body

    def show(self, ev: ArtifactEmitted) -> None:
        """Render the artifact in the preview pane."""
        self._placeholder.display = False
        self._header.display = True
        self._body.display = True

        fname = filename(ev)
        meta = (
            f"[b]{icon_for(ev.mime_type)} {fname}[/b]\n"
            f"[dim]{ev.mime_type} · {human_size(ev.size_bytes)} · "
            f"{ev.local_path}[/dim]"
        )
        self._header.update(meta)

        body = _render_body(ev)
        self._body.update(body)


def _render_body(ev: ArtifactEmitted) -> str:
    """Build the body text for an artifact preview. Always returns markup."""
    local = Path(ev.local_path)
    if not local.is_file():
        return (
            f"[yellow]File not found on disk:[/yellow] {ev.local_path}\n\n"
            "[dim]The artifact was emitted but its bytes were never written "
            "locally — this is expected in the scripted demo.[/dim]"
        )

    if _is_text_mime(ev.mime_type):
        try:
            data = local.read_bytes()[:_TEXT_PREVIEW_BYTES]
            text = data.decode("utf-8", errors="replace")
        except OSError as e:
            return f"[red]Read failed:[/red] {e}"
        truncated = local.stat().st_size > _TEXT_PREVIEW_BYTES
        suffix = (
            f"\n\n[dim italic]…truncated to {_TEXT_PREVIEW_BYTES // 1024} KB[/dim italic]"
            if truncated else ""
        )
        # Escape markup characters in user content so brackets don't get parsed.
        safe = text.replace("[", r"\[")
        return safe + suffix

    if ev.mime_type.startswith("image/"):
        return (
            "[dim italic]Image preview is not supported in the terminal.[/dim italic]\n\n"
            f"Open this file to view it:\n  [b]{ev.local_path}[/b]"
        )

    return (
        "[dim italic]Binary content — preview not supported.[/dim italic]\n\n"
        f"Open this file with your default viewer:\n  [b]{ev.local_path}[/b]"
    )


# ─── Top-level view ─────────────────────────────────────────────────────────


class ArtifactsView(Horizontal):
    """Tabbed sub-pane: list of artifacts on the left, preview on the right."""

    def __init__(self) -> None:
        super().__init__(id="artifacts-view")
        self.list_view = ListView(id="artifact-list")
        self.preview = ArtifactPreview()
        self._rows: list[ArtifactEmitted] = []
        # Callback fired whenever the artifact count changes (used by
        # SwarmComputer to update the tab title).
        self.on_count_change: Callable[[int], None] | None = None

    def compose(self):
        yield self.list_view
        yield self.preview

    def add(self, ev: ArtifactEmitted) -> None:
        """Append a new artifact and auto-select it if it's the first."""
        self._rows.append(ev)
        item = ArtifactListItem(ev)
        try:
            self.list_view.append(item)
        except Exception:
            self.call_after_refresh(lambda: self.list_view.append(item))
        if len(self._rows) == 1:
            # Auto-select the first artifact so the preview pane isn't empty.
            try:
                self.list_view.index = 0
            except Exception:
                pass
            self.preview.show(ev)
        if self.on_count_change is not None:
            self.on_count_change(len(self._rows))

    def clear(self) -> None:
        self._rows.clear()
        self.list_view.clear()
        # Reset preview to placeholder
        self.preview._placeholder.display = True
        self.preview._header.display = False
        self.preview._body.display = False
        if self.on_count_change is not None:
            self.on_count_change(0)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Fired by Textual when the user picks a row."""
        item = event.item
        if isinstance(item, ArtifactListItem):
            self.preview.show(item.ev)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Also react to arrow-key highlights (no click required)."""
        item = event.item
        if isinstance(item, ArtifactListItem):
            self.preview.show(item.ev)
