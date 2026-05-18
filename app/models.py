"""Per-role model defaults — cheap-and-fast preset.

Override per call via the `model=` argument on orchestrate / run_worker / aggregate,
or edit this dict directly.
"""
from __future__ import annotations

MODELS: dict[str, str] = {
    # "Cheap-smart" preset — reasoning on every role, 128K output ceilings,
    # ~0.9x the cost of the previous GPT-4.1 / 4.1-mini setup.
    "orchestrator": "openai/gpt-5.1",
    "worker":       "openai/gpt-5-mini",
    "aggregator":   "openai/gpt-5-mini",
}
