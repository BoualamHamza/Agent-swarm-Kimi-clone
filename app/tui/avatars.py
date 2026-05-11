"""Curated character pool + portrait art for the swarm TUI.

The orchestrator names agents functionally (`MarketAnalyst`, `TechArchitect`).
The TUI replaces those names visually with characters drawn from this pool —
each agent gets a stable Character (name + pixel portrait + accent color)
for the lifetime of the session.

The pool is shuffled once per process and assigned round-robin; on exhaustion
it recycles (so a session can have more agents than the pool, just with repeats).
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Character:
    name: str            # Display name shown in the TUI (e.g. "Watt")
    portrait: str        # Multiline block-art portrait, ~4 rows × 7 cols
    accent: str          # Textual color token used as the avatar border / glow


# ─── Pool ────────────────────────────────────────────────────────────────────

# Accent colors — Textual color tokens. Picked for visibility on a dark theme.
_PALETTE = [
    "cyan", "magenta", "yellow", "green",
    "#ff7eb6", "#82cfff", "#a7f0ba", "#ffb784",
    "#d4bbff", "#ffa1bb", "#7eebdc", "#f3d76a",
]


def _pal(i: int) -> str:
    return _PALETTE[i % len(_PALETTE)]


# Each portrait is exactly 4 rows. Width varies slightly but stays ≤ 7 cells.
# Style uses block-drawing chars (▀▄█▌▐░▒▓) + a few geometric glyphs for
# eyes/mouths (◐◑◕◔○•╶╴╷╵─). Designed to read at terminal scale.

CHARACTER_POOL: list[Character] = [
    Character("Watt",       " ▄▀▀▀▄ \n █◕ ◕█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(0)),
    Character("Curie",      " ▄███▄ \n █◐ ◑█ \n █ ╶ █ \n ▝▄▄▄▘ ", _pal(1)),
    Character("Tesla",      " ▟███▙ \n █◔ ◔█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(2)),
    Character("Hemingway",  " ▄▀▀▀▄ \n █• •█ \n █ ╴ █ \n ▝▒▒▒▘ ", _pal(3)),
    Character("Borges",     " ▄▀▀▀▄ \n █◎ ◎█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(4)),
    Character("Bergson",    " ░▀▀▀░ \n █○ ○█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(5)),
    Character("Sartre",     " ▄▀▀▀▄ \n █◑  █ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(6)),
    Character("Barthes",    " ▓███▓ \n █◕ ◕█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(7)),
    Character("Emerson",    " ▄▀▀▀▄ \n █◐ ◑█ \n █ ◡ █ \n ▝▄▄▄▘ ", _pal(8)),
    Character("Riemann",    " ▄∑▀▀▄ \n █◔ ◔█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(9)),
    Character("Cyclops",    " ▄▀▀▀▄ \n █ ◉ █ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(10)),
    Character("Atlas",      " ▄▀▀▀▄ \n █◕ ◕█ \n █ ─ █ \n ▟▒▒▒▙ ", _pal(11)),
    Character("Hermes",     " ◢▀▀▀◣ \n █◕ ◕█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(0)),
    Character("Ada",        " ▄♥▀▀▄ \n █◐ ◑█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(1)),
    Character("Newton",     " ▄▀●▀▄ \n █◕ ◕█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(2)),
    Character("DaVinci",    " ▄▀▀▀▄ \n █◔ ◔█ \n █ ─ █ \n ▝▓▓▓▘ ", _pal(3)),
    Character("Pascal",     " ◢███◣ \n █◕ ◕█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(4)),
    Character("Euler",      " ░▀▀▀░ \n █◎ ◎█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(5)),
    Character("Lovelace",   " ▄≈▀≈▄ \n █◐ ◑█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(6)),
    Character("Turing",     " ▄▀▀▀▄ \n █◔ ◔█ \n █ ╷ █ \n ▝▄▄▄▘ ", _pal(7)),
    Character("Ramanujan",  " ▟▀▀▀▙ \n █◕ ◕█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(8)),
    Character("Galileo",    " ▄▀▀▀▄ \n █◉ ◔█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(9)),
    Character("Hypatia",    " ◜▀▀▀◝ \n █◐ ◑█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(10)),
    Character("Goedel",     " ▄▀▀▀▄ \n █◕ ◕█ \n █ ⌐ █ \n ▝▄▄▄▘ ", _pal(11)),
    Character("Boltzmann",  " ▒███▒ \n █◐ ◑█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(0)),
    Character("Heisenberg", " ▄▀▀▀▄ \n █◔ ◔█ \n █ ≈ █ \n ▝▄▄▄▘ ", _pal(1)),
    Character("Fermi",      " ▄▀▀▀▄ \n █◕ ◕█ \n █ ◔ █ \n ▝▄▄▄▘ ", _pal(2)),
    Character("Shannon",    " ▄▀▀▀▄ \n █◑ ◐█ \n █ ─ █ \n ▝▄▄▄▘ ", _pal(3)),
]


# ─── Pool allocator ──────────────────────────────────────────────────────────


class AvatarPool:
    """Stable agent_id → Character assignment for one session.

    Shuffled at construction so consecutive runs use different orderings.
    When more agents are spawned than the pool size, recycles from the top.
    """

    def __init__(self, *, seed: int | None = None) -> None:
        rng = random.Random(seed)
        self._order: list[Character] = list(CHARACTER_POOL)
        rng.shuffle(self._order)
        self._assignments: dict[str, Character] = {}
        self._cursor: int = 0

    def assign(self, agent_id: str) -> Character:
        """Return the Character for `agent_id`, allocating one on first call."""
        cached = self._assignments.get(agent_id)
        if cached is not None:
            return cached
        char = self._order[self._cursor % len(self._order)]
        self._cursor += 1
        self._assignments[agent_id] = char
        return char

    def lookup(self, agent_id: str) -> Character | None:
        """Return the Character for `agent_id` if already assigned, else None."""
        return self._assignments.get(agent_id)

    def __len__(self) -> int:
        return len(self._assignments)
