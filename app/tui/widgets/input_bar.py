"""InputBar — bottom input strip. Emits Input.Submitted when the user hits Enter."""
from __future__ import annotations

from textual.containers import Container
from textual.widgets import Input


class InputBar(Container):
    def __init__(self) -> None:
        super().__init__(id="input-bar")
        self.input = Input(
            placeholder="Describe a task for the swarm…  (Enter to run, q to quit)",
            id="task-input",
        )

    def compose(self):
        yield self.input

    def clear(self) -> None:
        self.input.value = ""

    def focus_input(self) -> None:
        self.input.focus()
