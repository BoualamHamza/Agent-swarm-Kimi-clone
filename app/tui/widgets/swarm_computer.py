"""SwarmComputer — the main-stage (right pane).

Layout (top-to-bottom):

    ┌─ AgentStrip ─────────────────────────────────────────┐
    │ [🤖 Hemingway ●] [🤖 Barthes ●] [🤖 Newton ✓] [...]  │
    ├─ tab bar  Logs · Code · Preview · Artifacts ─────────┤
    │                                                      │
    │   <ContentSwitcher: logs|code|preview|artifacts|     │
    │                     agent-detail>                    │
    │                                                      │
    ├─ MemoryDrawer (collapsed) ───────────────────────────┤
    │ ▶ Memory · 3 keys · 1.2 KB  (M to expand)            │
    └──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import ContentSwitcher, Markdown, RichLog, Static

from app.tui.widgets.agent_detail import AgentDetailView
from app.tui.widgets.agent_strip import AgentStrip
from app.tui.widgets.artifacts_view import ArtifactsView
from app.tui.widgets.memory_drawer import MemoryDrawer


TAB_LOGS = "logs"
TAB_CODE = "code"
TAB_PREVIEW = "preview"
TAB_ARTIFACTS = "artifacts"
TAB_AGENT = "agent-detail"


class StageTabs(Horizontal):
    """Tab bar above the ContentSwitcher. Click a label to switch tabs."""

    def __init__(self, switcher: ContentSwitcher) -> None:
        super().__init__(id="stage-tabs")
        self._switcher = switcher
        self._labels: dict[str, Static] = {}

    def compose(self):
        yield Static("[b]Main Stage[/b]", id="stage-title")
        for tab_id, label in (
            (TAB_LOGS, "Logs"),
            (TAB_CODE, "Code"),
            (TAB_PREVIEW, "Preview"),
            (TAB_ARTIFACTS, "Artifacts"),
        ):
            tab = Static(f" {label} ", classes="stage-tab", id=f"tab-label-{tab_id}")
            tab.tab_id = tab_id  # type: ignore[attr-defined]
            self._labels[tab_id] = tab
            yield tab

    def on_mount(self) -> None:
        self._sync_active()

    def set_active(self, tab_id: str) -> None:
        self._switcher.current = tab_id
        self._sync_active()

    def _sync_active(self) -> None:
        active = self._switcher.current
        for tab_id, label in self._labels.items():
            label.set_class(tab_id == active, "-active")

    def update_artifact_count(self, count: int) -> None:
        if TAB_ARTIFACTS in self._labels:
            text = f" Artifacts ({count}) " if count else " Artifacts "
            if count:
                text = f"[b green] Artifacts ({count}) [/b green]"
            self._labels[TAB_ARTIFACTS].update(text)

    def on_click(self, event):  # noqa: D401
        target = event.control if hasattr(event, "control") else None
        if target is not None and hasattr(target, "tab_id"):
            self.set_active(target.tab_id)


class SwarmComputer(Container):
    """The right-hand main stage."""

    def __init__(self) -> None:
        super().__init__(id="swarm-computer")
        self.strip = AgentStrip()
        self.logs = RichLog(
            id=TAB_LOGS,
            highlight=True,
            wrap=False,
            markup=True,
            auto_scroll=True,
        )
        self.code = Static(
            "[dim italic]No code preview yet. Agents that write files will "
            "surface them here.[/dim italic]",
            id=TAB_CODE,
        )
        # The final answer / artifact previews are often long — wrap the
        # Markdown in a VerticalScroll so it scrolls instead of clipping. The
        # scroll wrapper carries the ContentSwitcher id; `self.preview` still
        # points at the Markdown so callers keep using `.update(...)`.
        self.preview = Markdown("")
        self._preview_pane = VerticalScroll(self.preview, id=TAB_PREVIEW)
        # ArtifactsView is what the ContentSwitcher switches to — its id must
        # match TAB_ARTIFACTS so ContentSwitcher.current=... can find it.
        self.artifacts_view = ArtifactsView(id=TAB_ARTIFACTS)
        self.agent_detail = AgentDetailView()
        self.memory = MemoryDrawer()

        self._switcher = ContentSwitcher(initial=TAB_LOGS, id="stage")
        self._tabs = StageTabs(self._switcher)

        # Wire artifact-count → tab label and ArtifactsView is the active tab.
        self.artifacts_view.on_count_change = self._on_artifact_count_change

    # ─── Layout ─────────────────────────────────────────────────────────────

    def compose(self):
        yield self.strip
        yield self._tabs
        with self._switcher:
            yield self.logs
            yield self.code
            yield self._preview_pane
            yield self.artifacts_view
            yield self.agent_detail
        yield self.memory

    def on_mount(self) -> None:
        # Seed the logs pane so it doesn't look broken at idle.
        self.logs.write("[dim italic]Waiting for swarm output…[/dim italic]")

    # ─── Tab control ────────────────────────────────────────────────────────

    def show_tab(self, tab_id: str) -> None:
        self._tabs.set_active(tab_id)

    def show_logs(self) -> None:
        self.show_tab(TAB_LOGS)

    def show_artifacts(self) -> None:
        self.show_tab(TAB_ARTIFACTS)

    def show_agent_detail(self) -> None:
        self.show_tab(TAB_AGENT)

    # ─── Compatibility shims (kept for the old test surface) ────────────────
    # The grid was replaced by the strip; expose `grid` as an alias so any
    # straggler `app.swarm_computer.grid.get_card(...)` calls keep working.
    @property
    def grid(self) -> AgentStrip:  # noqa: D401
        return self.strip

    # ─── Internals ──────────────────────────────────────────────────────────

    def _on_artifact_count_change(self, count: int) -> None:
        self._tabs.update_artifact_count(count)

    @property
    def header(self):
        # Maintained for backwards compatibility with tests that check
        # ``swarm_computer.header._phase`` etc. The reactive SwarmHeader lives
        # on the app; we delegate so callers continue to work.
        return self.app.swarm_header  # type: ignore[attr-defined]
