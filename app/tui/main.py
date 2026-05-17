"""SwarmApp — the Textual App and ``agent-swarm`` CLI entry point.

Usage:
    agent-swarm             # interactive: type a task, swarm runs in-process
    agent-swarm --demo      # scripted demo, no API keys required
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import AsyncIterator

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Input

from app.state import SwarmEvent
from app.tui.event_router import EventRouter
from app.tui.widgets.agent_strip import AgentPill
from app.tui.widgets.chat_pane import AgentRosterRow, ChatPane
from app.tui.widgets.input_bar import InputBar
from app.tui.widgets.swarm_computer import (
    SwarmComputer,
    TAB_AGENT,
    TAB_ARTIFACTS,
    TAB_CODE,
    TAB_LOGS,
    TAB_PREVIEW,
)
from app.tui.widgets.swarm_header import SwarmHeader


class SwarmApp(App):
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("1", "switch_tab('logs')", "Logs"),
        ("2", "switch_tab('code')", "Code"),
        ("3", "switch_tab('preview')", "Preview"),
        ("4", "switch_tab('artifacts')", "Artifacts"),
        ("a", "switch_tab('artifacts')", "Artifacts"),
        ("c", "switch_tab('logs')", "Logs"),
        ("m", "toggle_memory", "Memory"),
        ("f", "toggle_final", "Final"),
        ("escape", "unfocus_agent", "Back"),
        ("up", "roster_prev", "↑ Agent"),
        ("down", "roster_next", "↓ Agent"),
        ("k", "roster_prev", "↑ Agent"),
        ("j", "roster_next", "↓ Agent"),
        ("enter", "focus_selected", "Focus"),
    ]

    def __init__(self, *, demo: bool = False) -> None:
        super().__init__()
        self._demo = demo
        self.swarm_header = SwarmHeader()
        self.chat_pane = ChatPane()
        self.swarm_computer = SwarmComputer()
        self.input_bar = InputBar()
        self.router: EventRouter | None = None
        self._run_task: asyncio.Task[None] | None = None
        self.focused_agent: str | None = None

    # ─── Layout ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield self.swarm_header
        with Horizontal(id="body"):
            yield self.chat_pane
            yield self.swarm_computer
        yield self.input_bar
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Agent Swarm"
        self.sub_title = "Mission Control · v0.2"
        self.swarm_header.swarm_name = "Untitled Swarm"
        self.router = EventRouter(self)
        if self._demo:
            self.swarm_header.swarm_name = "Math Word-Problem Benchmark"
            self._run_task = asyncio.create_task(self._run_demo())
        else:
            self.input_bar.focus_input()

    # ─── Actions / bindings ─────────────────────────────────────────────────

    def action_switch_tab(self, tab_id: str) -> None:
        if tab_id not in {TAB_LOGS, TAB_CODE, TAB_PREVIEW, TAB_ARTIFACTS, TAB_AGENT}:
            return
        self.swarm_computer.show_tab(tab_id)

    def action_toggle_memory(self) -> None:
        self.swarm_computer.memory.toggle()

    def action_toggle_final(self) -> None:
        self.chat_pane.final.toggle()

    def action_roster_prev(self) -> None:
        self.chat_pane.roster.move_cursor(-1)

    def action_roster_next(self) -> None:
        self.chat_pane.roster.move_cursor(+1)

    def action_focus_selected(self) -> None:
        sel = self.chat_pane.roster._selected
        if sel:
            self._focus_agent(sel)

    def action_unfocus_agent(self) -> None:
        if self.focused_agent is None:
            return
        self.focused_agent = None
        self.swarm_computer.agent_detail.unfocus()
        self.swarm_computer.show_tab(TAB_LOGS)

    # ─── Agent focus plumbing ──────────────────────────────────────────────

    def _focus_agent(self, agent_id: str) -> None:
        self.focused_agent = agent_id
        self.chat_pane.roster.select(agent_id)
        self.swarm_computer.agent_detail.focus_agent(agent_id)
        self.swarm_computer.show_agent_detail()

    @on(AgentPill.Clicked)
    def _on_pill_clicked(self, event: AgentPill.Clicked) -> None:
        self._focus_agent(event.agent_id)

    @on(AgentRosterRow.Clicked)
    def _on_roster_clicked(self, event: AgentRosterRow.Clicked) -> None:
        self._focus_agent(event.agent_id)

    # ─── Input handling ────────────────────────────────────────────────────

    @on(Input.Submitted, "#task-input")
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        task = event.value.strip()
        if not task:
            return
        if self._run_task and not self._run_task.done():
            return
        self.input_bar.clear()
        self._run_task = asyncio.create_task(self._run_live(task))

    # ─── Event loops ───────────────────────────────────────────────────────

    async def _run_demo(self) -> None:
        from app.tui.demo import scripted_events
        self.chat_pane.task_card.set_task("[DEMO] Math Word-Problem Benchmark")
        await self._consume(scripted_events())

    async def _run_live(self, task: str) -> None:
        from app.swarm import run_swarm
        self.chat_pane.task_card.set_task(task)
        self.swarm_header.swarm_name = task[:40]
        try:
            await self._consume(run_swarm(task))
        except Exception as e:
            self.chat_pane.set_thinking(f"[b red]Run failed:[/b red] {e}")

    async def _consume(self, stream: AsyncIterator[SwarmEvent]) -> None:
        assert self.router is not None
        async for ev in stream:
            self.router.dispatch(ev)


# ─── CLI entry ──────────────────────────────────────────────────────────────


def run() -> None:
    """Console script entrypoint (see [project.scripts] in pyproject.toml)."""
    parser = argparse.ArgumentParser(prog="agent-swarm", description="Agent Swarm TUI")
    parser.add_argument("--demo", action="store_true",
                        help="Run the scripted demo (no API keys needed)")
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    os.chdir(here.parent.parent)

    SwarmApp(demo=args.demo).run()


if __name__ == "__main__":
    run()
