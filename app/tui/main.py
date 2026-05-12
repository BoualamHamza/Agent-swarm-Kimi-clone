"""SwarmApp — the Textual App and `agent-swarm` CLI entry point.

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
from textual.widgets import Footer, Header, Input

from app.state import SwarmEvent
from app.tui.event_router import EventRouter
from app.tui.widgets.chat_pane import ChatPane
from app.tui.widgets.input_bar import InputBar
from app.tui.widgets.swarm_computer import SwarmComputer


class SwarmApp(App):
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("f1", "show_computer", "Computer"),
        ("f2", "show_artifacts", "Artifacts"),
    ]

    def action_show_computer(self) -> None:
        self.swarm_computer.show_computer()

    def action_show_artifacts(self) -> None:
        self.swarm_computer.show_artifacts()

    def __init__(self, *, demo: bool = False) -> None:
        super().__init__()
        self._demo = demo
        self.chat_pane = ChatPane()
        self.swarm_computer = SwarmComputer()
        self.input_bar = InputBar()
        self.router: EventRouter | None = None
        self._run_task: asyncio.Task[None] | None = None

    # ─── Layout ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            yield self.chat_pane
            yield self.swarm_computer
        yield self.input_bar
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Agent Swarm"
        self.sub_title = "Kimi-style TUI · v0.1"
        self.router = EventRouter(self)
        if self._demo:
            self._run_task = asyncio.create_task(self._run_demo())
        else:
            self.input_bar.focus_input()

    # ─── Input handling ─────────────────────────────────────────────────────

    @on(Input.Submitted, "#task-input")
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        task = event.value.strip()
        if not task:
            return
        if self._run_task and not self._run_task.done():
            return  # a run is already in progress
        self.input_bar.clear()
        self._run_task = asyncio.create_task(self._run_live(task))

    # ─── Event loops ────────────────────────────────────────────────────────

    async def _run_demo(self) -> None:
        # Imported lazily so a fresh checkout without the demo file still
        # produces a useful error rather than failing at top-level import.
        from app.tui.demo import scripted_events
        self.chat_pane.task_card.set_task("[DEMO] Math Word-Problem Benchmark")
        await self._consume(scripted_events())

    async def _run_live(self, task: str) -> None:
        from app.swarm import run_swarm
        self.chat_pane.task_card.set_task(task)
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

    # Make sure relative imports / data files work when invoked from anywhere.
    here = Path(__file__).resolve().parent
    os.chdir(here.parent.parent)

    SwarmApp(demo=args.demo).run()


if __name__ == "__main__":
    run()
